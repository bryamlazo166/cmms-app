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

    # ── ALCANCE DE INDICADORES (include_in_kpi) ─────────────────────────
    @app.route('/configuracion-kpi', methods=['GET'])
    @login_required
    def kpi_scope_page():
        if not _is_admin():
            from flask import redirect, url_for
            return redirect(url_for('index'))
        from flask import render_template
        return render_template('kpi_scope.html')

    @app.route('/api/admin/kpi-scope/apply-defaults', methods=['POST'])
    @login_required
    def apply_kpi_default_exclusions():
        """Marca como excluidas (include_in_kpi=False) las areas y equipos que
        tipicamente no deben entrar en indicadores ni produccion: areas
        BAJA/FUERA DE SERVICIO, UTILITIES, RMP; y equipos hidrolavadoras
        en area COCCION. Idempotente."""
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            results = {'areas_excluded': [], 'equipments_excluded': []}

            # Areas: nombres conocidos a excluir
            area_patterns = ['BAJA', 'FUERA DE SERVICIO', 'BAJA / FUERA DE SERVICIO',
                            'UTILITIES', 'RMP']
            for pat in area_patterns:
                rows = db.session.execute(text("""
                    UPDATE areas SET include_in_kpi = FALSE
                    WHERE UPPER(name) LIKE :p AND include_in_kpi = TRUE
                    RETURNING id, name
                """), {"p": f'%{pat.upper()}%'}).fetchall()
                for r in rows:
                    results['areas_excluded'].append({'id': r[0], 'name': r[1], 'matched_pattern': pat})

            # Equipos: hidrolavadoras dentro del area COCCION
            rows = db.session.execute(text("""
                UPDATE equipments e SET include_in_kpi = FALSE
                FROM lines l, areas a
                WHERE e.line_id = l.id AND l.area_id = a.id
                  AND UPPER(a.name) LIKE '%COCCION%'
                  AND (UPPER(e.name) LIKE '%HIDROLAVADORA%' OR UPPER(e.tag) LIKE '%H4%')
                  AND e.include_in_kpi = TRUE
                RETURNING e.id, e.tag, e.name
            """)).fetchall()
            for r in rows:
                results['equipments_excluded'].append({'id': r[0], 'tag': r[1], 'name': r[2]})

            db.session.commit()
            results['ok'] = True
            return jsonify(results)
        except Exception as e:
            db.session.rollback()
            logger.exception('apply_kpi_default_exclusions error')
            return jsonify({"error": str(e)}), 500

    # ── BOT USAGE / TELEMETRIA DEL BOT TELEGRAM ──────────────────────────────
    @app.route('/api/admin/bot-usage', methods=['GET'])
    @login_required
    def bot_usage_summary():
        """Resumen de uso del bot. Query: ?days=7 (default).

        Devuelve totales por dia, por servicio (whisper/deepseek), por chat,
        y top errores. Util para auditar gasto y detectar abuso.
        """
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            days = int(request.args.get('days') or 7)
            days = max(1, min(days, 365))

            base_filter = "created_at >= CURRENT_TIMESTAMP - INTERVAL ':d days'" \
                if db.engine.dialect.name == 'postgresql' \
                else f"created_at >= datetime('now', '-{days} days')"
            params = {"d": days} if db.engine.dialect.name == 'postgresql' else {}

            # Totales globales
            totals = db.session.execute(text(f"""
                SELECT service,
                       COUNT(*) AS calls,
                       SUM(COALESCE(tokens_in, 0)) AS tokens_in,
                       SUM(COALESCE(tokens_out, 0)) AS tokens_out,
                       SUM(COALESCE(tokens_cached, 0)) AS tokens_cached,
                       SUM(COALESCE(audio_duration_s, 0)) AS audio_seconds,
                       SUM(COALESCE(cost_usd, 0)) AS cost_usd,
                       AVG(latency_ms) AS avg_latency_ms,
                       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
                FROM bot_usage
                WHERE {base_filter.replace(':d days', f"{days} days")}
                GROUP BY service
            """), params).fetchall()

            by_service = []
            grand_cost = 0.0
            grand_calls = 0
            for r in totals:
                cost = float(r[6] or 0)
                grand_cost += cost
                grand_calls += int(r[1] or 0)
                by_service.append({
                    'service': r[0],
                    'calls': int(r[1] or 0),
                    'tokens_in': int(r[2] or 0),
                    'tokens_out': int(r[3] or 0),
                    'tokens_cached': int(r[4] or 0),
                    'audio_seconds': float(r[5] or 0),
                    'cost_usd': round(cost, 4),
                    'avg_latency_ms': int(r[7] or 0),
                    'errors': int(r[8] or 0),
                })

            # Por dia (ultimos N dias)
            if db.engine.dialect.name == 'postgresql':
                daily_q = """
                    SELECT TO_CHAR(created_at, 'YYYY-MM-DD') AS day,
                           service,
                           COUNT(*) AS calls,
                           SUM(COALESCE(cost_usd, 0)) AS cost_usd
                    FROM bot_usage
                    WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL :i
                    GROUP BY day, service
                    ORDER BY day DESC, service
                """
                daily_rows = db.session.execute(text(daily_q), {"i": f"{days} days"}).fetchall()
            else:
                daily_q = f"""
                    SELECT strftime('%Y-%m-%d', created_at) AS day,
                           service,
                           COUNT(*) AS calls,
                           SUM(COALESCE(cost_usd, 0)) AS cost_usd
                    FROM bot_usage
                    WHERE created_at >= datetime('now', '-{days} days')
                    GROUP BY day, service
                    ORDER BY day DESC, service
                """
                daily_rows = db.session.execute(text(daily_q)).fetchall()
            by_day = [{'day': r[0], 'service': r[1], 'calls': int(r[2]), 'cost_usd': round(float(r[3] or 0), 4)} for r in daily_rows]

            # Por chat
            chat_q = f"""
                SELECT chat_id,
                       COUNT(*) AS calls,
                       SUM(COALESCE(cost_usd, 0)) AS cost_usd
                FROM bot_usage
                WHERE chat_id IS NOT NULL
                  AND { 'created_at >= CURRENT_TIMESTAMP - INTERVAL :i' if db.engine.dialect.name == 'postgresql' else f"created_at >= datetime('now', '-{days} days')" }
                GROUP BY chat_id
                ORDER BY cost_usd DESC
                LIMIT 20
            """
            chat_params = {"i": f"{days} days"} if db.engine.dialect.name == 'postgresql' else {}
            by_chat = [
                {'chat_id': r[0], 'calls': int(r[1]), 'cost_usd': round(float(r[2] or 0), 4)}
                for r in db.session.execute(text(chat_q), chat_params).fetchall()
            ]

            return jsonify({
                'period_days': days,
                'grand_totals': {
                    'calls': grand_calls,
                    'cost_usd': round(grand_cost, 4),
                },
                'by_service': by_service,
                'by_day': by_day,
                'by_chat': by_chat,
            })
        except Exception as e:
            logger.exception('bot_usage_summary error')
            return jsonify({"error": str(e)}), 500

    @app.route('/admin/bot-usage', methods=['GET'])
    @login_required
    def bot_usage_page():
        if not _is_admin():
            from flask import redirect, url_for
            return redirect(url_for('index'))
        from flask import render_template
        return render_template('bot_usage.html')

    # ── USUARIOS DEL BOT TELEGRAM (REPORTERS) ────────────────────────────────
    # Permite al admin asociar un chat_id de Telegram con un nombre y area,
    # para que al crear un aviso desde el bot el reporter_name no sea
    # genérico "Bot Telegram" sino la persona real que lo reportó.

    @app.route('/api/admin/telegram-users', methods=['GET'])
    @login_required
    def list_telegram_users():
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            rows = db.session.execute(text(
                "SELECT chat_id, nombre, area, rol, activo, notas, created_at, updated_at, created_by "
                "FROM bot_telegram_users ORDER BY activo DESC, nombre"
            )).fetchall()
            return jsonify([{
                "chat_id": r[0], "nombre": r[1], "area": r[2], "rol": r[3],
                "activo": bool(r[4]), "notas": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "updated_at": r[7].isoformat() if r[7] else None,
                "created_by": r[8],
            } for r in rows])
        except Exception as e:
            logger.exception('list_telegram_users error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/telegram-users', methods=['POST'])
    @login_required
    def create_telegram_user():
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        data = request.get_json() or {}
        try:
            chat_id = int(data.get('chat_id') or 0)
            nombre = (data.get('nombre') or '').strip()
            if not chat_id or not nombre:
                return jsonify({"error": "chat_id y nombre son obligatorios"}), 400
            rol = (data.get('rol') or 'reporter').strip().lower()
            if rol not in ('admin', 'reporter'):
                rol = 'reporter'
            area = (data.get('area') or '').strip() or None
            notas = (data.get('notas') or '').strip() or None
            activo = bool(data.get('activo', True))

            existing = db.session.execute(text(
                "SELECT 1 FROM bot_telegram_users WHERE chat_id = :c"
            ), {"c": chat_id}).scalar()
            if existing:
                return jsonify({"error": f"chat_id {chat_id} ya existe"}), 409

            db.session.execute(text(
                "INSERT INTO bot_telegram_users (chat_id, nombre, area, rol, activo, notas, created_by) "
                "VALUES (:c, :n, :a, :r, :ac, :no, :cb)"
            ), {"c": chat_id, "n": nombre, "a": area, "r": rol, "ac": activo,
                "no": notas, "cb": current_user.username})
            db.session.commit()
            return jsonify({"ok": True, "chat_id": chat_id}), 201
        except Exception as e:
            db.session.rollback()
            logger.exception('create_telegram_user error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/telegram-users/<int:chat_id>', methods=['PUT'])
    @login_required
    def update_telegram_user(chat_id):
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        data = request.get_json() or {}
        try:
            updates = {}
            if 'nombre' in data:
                v = (data['nombre'] or '').strip()
                if not v:
                    return jsonify({"error": "nombre no puede estar vacío"}), 400
                updates['nombre'] = v
            if 'area' in data:
                updates['area'] = (data['area'] or '').strip() or None
            if 'rol' in data:
                r = (data['rol'] or '').strip().lower()
                if r in ('admin', 'reporter'):
                    updates['rol'] = r
            if 'activo' in data:
                updates['activo'] = bool(data['activo'])
            if 'notas' in data:
                updates['notas'] = (data['notas'] or '').strip() or None

            if not updates:
                return jsonify({"error": "Sin campos para actualizar"}), 400

            set_clause = ", ".join(f"{k} = :{k}" for k in updates.keys())
            updates['c'] = chat_id
            result = db.session.execute(text(
                f"UPDATE bot_telegram_users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE chat_id = :c"
            ), updates)
            if result.rowcount == 0:
                db.session.rollback()
                return jsonify({"error": "No encontrado"}), 404
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.exception('update_telegram_user error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/telegram-users/<int:chat_id>', methods=['DELETE'])
    @login_required
    def delete_telegram_user(chat_id):
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            result = db.session.execute(text(
                "DELETE FROM bot_telegram_users WHERE chat_id = :c"
            ), {"c": chat_id})
            if result.rowcount == 0:
                db.session.rollback()
                return jsonify({"error": "No encontrado"}), 404
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.exception('delete_telegram_user error')
            return jsonify({"error": str(e)}), 500

    @app.route('/admin/telegram-users', methods=['GET'])
    @login_required
    def telegram_users_page():
        if not _is_admin():
            from flask import redirect, url_for
            return redirect(url_for('index'))
        from flask import render_template
        return render_template('telegram_users.html')
