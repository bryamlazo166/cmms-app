"""Accion: registrar ejecucion de una ruta de inspeccion."""
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)


def register_inspection(app, data):
    """Registra ejecucion de inspeccion (resultado OK / CON_HALLAZGOS).

    Si findings_count > 0, crea automaticamente un aviso vinculado.

    Returns: (rcode, rname, notice_code, error_str | None).
    """
    from bot.resolvers import (
        fuzzy_tokens as _fuzzy_tokens,
        build_fuzzy_where as _build_fuzzy_where,
        score_fuzzy_candidates as _score_fuzzy_candidates,
        normalize_token as _normalize_token,
    )

    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        from utils.schedule_helpers import _calculate_lubrication_schedule
        try:
            route_id = data.get('route_id')
            route_code = (data.get('route_code') or '').strip()
            route_query = (data.get('route_query') or '').strip()

            row = None
            if route_id:
                row = _db.session.execute(text("""
                    SELECT ir.id, ir.code, ir.name, ir.frequency_days, ir.warning_days,
                           ir.area_id, ir.line_id, ir.equipment_id
                    FROM inspection_routes ir
                    WHERE ir.id = :id AND ir.is_active = true
                """), {"id": route_id}).fetchone()
            elif route_code:
                row = _db.session.execute(text("""
                    SELECT ir.id, ir.code, ir.name, ir.frequency_days, ir.warning_days,
                           ir.area_id, ir.line_id, ir.equipment_id
                    FROM inspection_routes ir
                    WHERE ir.code = :c AND ir.is_active = true
                """), {"c": route_code}).fetchone()
            elif route_query:
                tokens = _fuzzy_tokens(route_query)
                cols = ['ir.name', 'ir.code', 'e.name', 'e.tag']
                params = {}
                where_extra = _build_fuzzy_where(tokens, cols, params)
                base_sql = """
                    SELECT ir.id, ir.code, ir.name, ir.frequency_days, ir.warning_days,
                           ir.area_id, ir.line_id, ir.equipment_id, e.tag, e.name
                    FROM inspection_routes ir
                    LEFT JOIN equipments e ON ir.equipment_id = e.id
                    WHERE ir.is_active = true
                """
                if where_extra:
                    base_sql += " AND " + where_extra
                base_sql += " ORDER BY ir.code LIMIT 8"
                rows = _db.session.execute(text(base_sql), params).fetchall()

                # Fallback ILIKE tradicional
                if not rows:
                    q_like = f"%{route_query}%"
                    rows = _db.session.execute(text("""
                        SELECT ir.id, ir.code, ir.name, ir.frequency_days, ir.warning_days,
                               ir.area_id, ir.line_id, ir.equipment_id, e.tag, e.name
                        FROM inspection_routes ir
                        LEFT JOIN equipments e ON ir.equipment_id = e.id
                        WHERE ir.is_active = true AND (
                            ir.name ILIKE :q OR ir.code ILIKE :q OR e.name ILIKE :q OR e.tag ILIKE :q
                        )
                        LIMIT 8
                    """), {"q": q_like}).fetchall()

                if len(rows) == 1:
                    row = rows[0][:8]
                elif len(rows) > 1:
                    best, second = _score_fuzzy_candidates(
                        tokens, rows,
                        lambda r: f"{r[1] or ''} {r[2] or ''} {r[8] or ''} {r[9] or ''}"
                    )
                    if best is not None:
                        best_blob = f"{best[1] or ''} {best[2] or ''} {best[8] or ''} {best[9] or ''}".lower()
                        best_score = sum(1 for t in tokens if _normalize_token(t) in
                                         {_normalize_token(x) for x in best_blob.split()})
                        if best_score > second:
                            row = best[:8]
                    if not row:
                        options = '; '.join(f"{r[1] or r[0]}: {r[2]} [{r[8] or '-'}]" for r in rows[:5])
                        return None, None, None, f"Varias rutas coinciden con '{route_query}'. Aclara cual: {options}"

            if not row:
                return None, None, None, f"Ruta de inspeccion no encontrada para '{route_query or route_code or route_id}'. Verifica nombre/equipo o pasa el codigo (ej: INS-D8-SEM)."

            rid, rcode, rname, freq_days, warn_days, ar_id, ln_id, eq_id = row

            execution_date = (data.get('execution_date') or '').strip() or date.today().isoformat()
            executed_by = data.get('executed_by') or 'INSPECTOR'
            comments = data.get('comments')
            findings_count = int(data.get('findings_count') or 0)
            overall_result = (data.get('overall_result') or '').upper()
            if not overall_result:
                overall_result = 'CON_HALLAZGOS' if findings_count > 0 else 'OK'

            # Insert execution
            res = _db.session.execute(text("""
                INSERT INTO inspection_executions
                (route_id, execution_date, executed_by, overall_result, findings_count, comments, created_at)
                VALUES (:rid, :ed, :eb, :ores, :fc, :com, :now)
                RETURNING id
            """), {
                "rid": rid, "ed": execution_date, "eb": executed_by,
                "ores": overall_result, "fc": findings_count, "com": comments,
                "now": datetime.utcnow()
            })
            exec_id = res.scalar()

            # Auto-create notice if findings
            notice_code = None
            if findings_count > 0 and data.get('create_notice', True):
                max_id = _db.session.execute(text("SELECT COALESCE(MAX(id), 0) FROM maintenance_notices")).scalar()
                notice_code = f"AV-{str(max_id + 1).zfill(4)}"
                desc = f"[INSPECCION] {rname}: {findings_count} hallazgo(s)."
                if comments:
                    desc += f" {comments}"
                _db.session.execute(text("""
                    INSERT INTO maintenance_notices
                    (code, description, criticality, priority, request_date,
                     maintenance_type, status, reporter_name, reporter_type,
                     area_id, line_id, equipment_id, scope)
                    VALUES (:code, :desc, 'Media', 'Normal', :rd, 'Preventivo',
                            'Pendiente', :rep, 'INSPECCION',
                            :ar, :ln, :eq, 'PLAN')
                """), {
                    "code": notice_code, "desc": desc, "rd": execution_date,
                    "rep": executed_by, "ar": ar_id, "ln": ln_id, "eq": eq_id,
                })
                nid = _db.session.execute(text(
                    "SELECT id FROM maintenance_notices WHERE code = :c"
                ), {"c": notice_code}).scalar()
                _db.session.execute(text(
                    "UPDATE inspection_executions SET created_notice_id = :nid WHERE id = :id"
                ), {"nid": nid, "id": exec_id})

            # Recalculate schedule and update route
            next_due, semaphore = _calculate_lubrication_schedule(execution_date, freq_days, warn_days)
            _db.session.execute(text("""
                UPDATE inspection_routes
                SET last_execution_date = :led, next_due_date = :nd, semaphore_status = :ss
                WHERE id = :id
            """), {"led": execution_date, "nd": next_due, "ss": semaphore, "id": rid})

            _db.session.commit()
            _db.session.remove()
            return rcode or f"id:{rid}", rname, notice_code, None
        except Exception as e:
            _db.session.rollback()
            try:
                _db.session.remove()
            except Exception:
                pass
            logger.error(f"register_inspection error: {e}")
            return None, None, None, str(e)
