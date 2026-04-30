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

    # ── BACKUP DE BASE DE DATOS ──────────────────────────────────────────
    # Genera un dump JSON comprimido (gzip) de TODAS las tablas. Util para:
    #   - Snapshot manual antes de un cambio riesgoso.
    #   - Punto de restauracion local si algo se corrompe.
    # NO sustituye al backup automatico de Supabase (plan Pro), pero da
    # una salvaguarda extra controlada por el admin.

    def _is_admin():
        return getattr(current_user, 'role', None) == 'admin'

    def _list_tables():
        """Lista todas las tablas reales (no vistas) en orden alfabetico."""
        rows = db.session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)).fetchall()
        return [r[0] for r in rows]

    @app.route('/api/admin/backup/tables', methods=['GET'])
    @login_required
    def list_backup_tables():
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            tables = _list_tables()
            counts = {}
            for t in tables:
                try:
                    c = db.session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
                    counts[t] = int(c)
                except Exception:
                    counts[t] = -1
            return jsonify({
                "tables": tables,
                "counts": counts,
                "total_rows": sum(v for v in counts.values() if v >= 0),
            })
        except Exception as e:
            logger.exception('list_backup_tables error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/backup/db-dump', methods=['GET'])
    @login_required
    def download_db_dump():
        """Descarga un .json.gz con TODOS los datos. El admin puede pasar
        ?tables=t1,t2 para restringir a un subconjunto."""
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        from flask import send_file
        import json, gzip, io, datetime as _dt
        try:
            requested = (request.args.get('tables') or '').strip()
            include = set(t.strip() for t in requested.split(',') if t.strip()) if requested else None
            tables = _list_tables()
            if include:
                tables = [t for t in tables if t in include]
            dump = {
                'meta': {
                    'generated_at': _dt.datetime.utcnow().isoformat() + 'Z',
                    'app_build': app.config.get('CMMS_DB_MODE'),
                    'tables_count': len(tables),
                    'format': 'json.gz/v1',
                    'note': 'Cada tabla es una lista de dicts. Para restaurar usa POST /api/admin/backup/restore.',
                },
                'data': {},
            }
            total_rows = 0
            for t in tables:
                try:
                    rows = db.session.execute(text(f'SELECT * FROM "{t}"')).mappings().all()
                    serialized = []
                    for r in rows:
                        d = {}
                        for k, v in dict(r).items():
                            # Serializar valores no-JSON
                            if isinstance(v, (_dt.datetime, _dt.date)):
                                d[k] = v.isoformat()
                            elif hasattr(v, 'isoformat'):
                                d[k] = v.isoformat()
                            elif isinstance(v, (bytes, bytearray, memoryview)):
                                # Saltamos blobs (no deberia haber, pero por seguridad)
                                d[k] = None
                            else:
                                d[k] = v
                        serialized.append(d)
                    dump['data'][t] = serialized
                    total_rows += len(serialized)
                except Exception as te:
                    logger.warning(f"backup: tabla {t} fallo: {te}")
                    dump['data'][t] = {'_error': str(te)}
            dump['meta']['total_rows'] = total_rows

            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as gz:
                gz.write(json.dumps(dump, ensure_ascii=False, default=str).encode('utf-8'))
            buf.seek(0)
            stamp = _dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            fname = f'cmms_backup_{stamp}.json.gz'
            return send_file(buf, mimetype='application/gzip',
                             as_attachment=True, download_name=fname)
        except Exception as e:
            logger.exception('download_db_dump error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/backup/restore', methods=['POST'])
    @login_required
    def restore_db_dump():
        """Restaura datos desde un .json.gz generado por download_db_dump.
        SOLO MERGE (no DROP): inserta filas nuevas y omite las que ya
        existen por PK. Para restauracion total (limpia + reinserta) hay
        que pasar ?wipe=1, lo cual REQUIERE ALLOW_DB_RESET=true en env.

        El upload va por multipart en campo 'file'.
        """
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        import json, gzip
        wipe = request.args.get('wipe', '0') == '1'
        if wipe and (os.getenv('ALLOW_DB_RESET', 'false').strip().lower() != 'true'):
            return jsonify({"error": "wipe requiere ALLOW_DB_RESET=true en env"}), 403

        if 'file' not in request.files:
            return jsonify({"error": "Falta archivo (campo 'file')"}), 400
        f = request.files['file']
        try:
            data = json.loads(gzip.decompress(f.read()).decode('utf-8'))
        except Exception as e:
            return jsonify({"error": f"Archivo invalido: {e}"}), 400

        tables = data.get('data') or {}
        if not isinstance(tables, dict):
            return jsonify({"error": "Formato dump invalido"}), 400

        # Obtener orden topologico aproximado: padres primero
        # Estrategia simple: tablas sin FK primero, luego el resto.
        # Si hay FK violation, capturamos y reportamos.
        results = {}
        existing = set(_list_tables())
        for t, rows in tables.items():
            if t not in existing:
                results[t] = {'skipped': 'tabla no existe en BD destino', 'inserted': 0}
                continue
            if not isinstance(rows, list):
                results[t] = {'skipped': 'no es lista', 'inserted': 0}
                continue
            inserted = 0
            errors = 0
            try:
                if wipe:
                    db.session.execute(text(f'DELETE FROM "{t}"'))
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    cols = ', '.join(f'"{k}"' for k in row.keys())
                    placeholders = ', '.join(f':{k}' for k in row.keys())
                    sql = f'INSERT INTO "{t}" ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
                    try:
                        db.session.execute(text(sql), row)
                        inserted += 1
                    except Exception:
                        errors += 1
                db.session.commit()
                results[t] = {'inserted': inserted, 'errors': errors}
            except Exception as te:
                db.session.rollback()
                results[t] = {'error': str(te)}
        return jsonify({"ok": True, "wipe": wipe, "tables": results})

    @app.route('/admin/backup', methods=['GET'])
    @login_required
    def backup_page():
        if not _is_admin():
            from flask import redirect, url_for
            return redirect(url_for('index'))
        from flask import render_template
        return render_template('backup.html')
