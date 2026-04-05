import os

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import text


def register_admin_routes(app, db, logger):

    @app.route('/api/initialize', methods=['POST'])
    def initialize_db():
        if (os.getenv('ALLOW_DB_RESET', 'false').strip().lower() != 'true'):
            return jsonify({"error": "DB reset deshabilitado (ALLOW_DB_RESET=false)."}), 403
        admin_token = os.getenv('CMMS_ADMIN_TOKEN')
        request_token = request.headers.get('X-CMMS-ADMIN-TOKEN') or request.args.get('token')
        if not admin_token:
            return jsonify({"error": "CMMS_ADMIN_TOKEN no configurado."}), 403
        if request_token != admin_token:
            return jsonify({"error": "Token invalido para DB reset."}), 403
        try:
            with app.app_context():
                db.drop_all()
                db.create_all()
                logger.warning("Database reset executed via /api/initialize.")
            return jsonify({"message": "DB reset success"}), 201
        except Exception as e:
            logger.error(f"DB reset error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Selective DB Cleanup ───────────────────────────────────────────────

    # Tables that can be cleaned (transactional data)
    CLEANABLE_TABLES = {
        'maintenance_notices': 'Avisos',
        'work_orders': 'Ordenes de Trabajo',
        'ot_personnel': 'Personal OT',
        'ot_materials': 'Materiales OT',
        'ot_log_entries': 'Bitacora OT',
        'warehouse_movements': 'Movimientos Almacen (Kardex)',
        'purchase_requests': 'Solicitudes de Compra',
        'purchase_orders': 'Ordenes de Compra',
        'lubrication_executions': 'Ejecuciones Lubricacion',
        'inspection_executions': 'Ejecuciones Inspeccion',
        'inspection_results': 'Resultados Inspeccion',
        'monitoring_readings': 'Lecturas Monitoreo',
        'notifications': 'Notificaciones',
        'activities': 'Actividades',
        'milestones': 'Hitos',
        'rotative_asset_history': 'Historial Act. Rotativos',
    }

    # Tables that are NEVER cleaned (master data)
    PROTECTED_TABLES = [
        'users', 'role_permissions',
        'areas', 'lines', 'equipments', 'systems', 'components', 'spare_parts',
        'lubrication_points', 'inspection_routes', 'inspection_items',
        'monitoring_points',
        'rotative_assets', 'rotative_asset_specs', 'rotative_asset_bom',
        'warehouse_items', 'tools',
        'providers', 'technicians',
    ]

    @app.route('/api/admin/db-stats', methods=['GET'])
    @login_required
    def get_db_stats():
        if current_user.role != 'admin':
            return jsonify({"error": "Solo admin."}), 403
        try:
            stats = {}
            for table_name, label in CLEANABLE_TABLES.items():
                try:
                    count = db.session.execute(text(f"SELECT count(*) FROM {table_name}")).scalar()
                except Exception:
                    count = 0
                stats[table_name] = {'label': label, 'count': count}
            return jsonify(stats)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/cleanup', methods=['POST'])
    @login_required
    def cleanup_tables():
        if current_user.role != 'admin':
            return jsonify({"error": "Solo admin."}), 403

        data = request.get_json() or {}
        tables = data.get('tables', [])

        if not tables:
            return jsonify({"error": "No se selecciono ninguna tabla."}), 400

        # Validate all tables are cleanable
        for t in tables:
            if t not in CLEANABLE_TABLES:
                return jsonify({"error": f"Tabla '{t}' no permitida para limpieza."}), 400

        try:
            # Order matters: delete child tables before parent
            # Sort by dependency: children first, then parents
            PRIORITY = {
                'ot_log_entries': 0, 'ot_materials': 0, 'ot_personnel': 0,
                'inspection_results': 0, 'milestones': 0,
                'work_order_rca': 0, 'work_order_files': 0,
                'photo_attachments': 0,
                'warehouse_movements': 1, 'purchase_requests': 1, 'purchase_request': 1,
                'lubrication_executions': 1, 'inspection_executions': 1,
                'monitoring_readings': 1, 'rotative_asset_history': 1,
                'purchase_orders': 2, 'notifications': 2, 'activities': 2,
                'work_orders': 3, 'maintenance_notices': 4,
            }
            sorted_tables = sorted(tables, key=lambda t: PRIORITY.get(t, 5))

            def safe_delete(sql):
                """Execute DELETE with savepoint so failures don't break the transaction."""
                try:
                    db.session.execute(text("SAVEPOINT cleanup_sp"))
                    db.session.execute(text(sql))
                    db.session.execute(text("RELEASE SAVEPOINT cleanup_sp"))
                except Exception:
                    db.session.execute(text("ROLLBACK TO SAVEPOINT cleanup_sp"))

            deleted = {}
            for table_name in sorted_tables:
                count = db.session.execute(text(f"SELECT count(*) FROM {table_name}")).scalar()
                # Auto-clean dependent tables not in the selected list
                if table_name == 'work_orders':
                    for dep in ['work_order_rca', 'work_order_files', 'ot_log_entries',
                                'ot_materials', 'ot_personnel', 'purchase_requests',
                                'ot_bitacora']:
                        safe_delete(f"DELETE FROM {dep}")
                    safe_delete("DELETE FROM photo_attachments WHERE entity_type = 'work_order'")
                if table_name == 'maintenance_notices':
                    safe_delete("DELETE FROM photo_attachments WHERE entity_type = 'notice'")
                db.session.execute(text(f"DELETE FROM {table_name}"))
                deleted[table_name] = count
                logger.warning(f"Admin cleanup: {table_name} ({count} rows deleted) by {current_user.username}")

            # Reset sequences for PostgreSQL
            bind = db.session.get_bind()
            is_pg = bind and bind.dialect and bind.dialect.name == 'postgresql'
            if is_pg:
                for table_name in sorted_tables:
                    try:
                        db.session.execute(text(f"""
                            SELECT setval(pg_get_serial_sequence('{table_name}','id'),
                                COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)
                        """))
                    except Exception:
                        pass

            db.session.commit()
            return jsonify({
                'deleted': deleted,
                'total_rows': sum(deleted.values()),
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Cleanup error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/mantenimiento-bd')
    @login_required
    def db_maintenance_page():
        if current_user.role != 'admin':
            from flask import redirect, url_for
            return redirect(url_for('index'))
        from flask import render_template
        return render_template('db_maintenance.html')
