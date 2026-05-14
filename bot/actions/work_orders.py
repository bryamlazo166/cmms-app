"""Acciones del bot sobre ordenes de trabajo (OT).

Cubre: cerrar, iniciar, agregar log, reprogramar, editar.
"""
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)


_OT_EDITABLE = {'description', 'failure_mode', 'maintenance_type', 'technician_id',
                'scheduled_date', 'estimated_duration', 'tech_count',
                'execution_comments', 'caused_downtime', 'downtime_hours',
                'report_required', 'report_due_date', 'report_url', 'status',
                'real_start_date', 'real_end_date',
                'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}


def close_ot(app, data):
    """Cierra una OT (status=Cerrada), tambien cierra el aviso vinculado.

    Returns: (ot_code, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            ot_code = data.get('ot_code', '').upper()
            row = _db.session.execute(text("SELECT id, status, notice_id FROM work_orders WHERE code = :c"), {"c": ot_code}).fetchone()
            if not row:
                return None, f"OT {ot_code} no encontrada"
            if row[1] == 'Cerrada':
                return None, f"OT {ot_code} ya esta cerrada"

            event_date = (data.get('event_date') or '').strip()
            if event_date:
                end_ts = f"{event_date}T17:00:00"
                closed_date = event_date
            else:
                end_ts = datetime.utcnow().isoformat()[:19]
                closed_date = date.today().isoformat()
            data['_resolved_event_date'] = closed_date

            comments = data.get('comments', 'Cerrada desde Telegram')
            _db.session.execute(text("""
                UPDATE work_orders SET status = 'Cerrada', real_end_date = :now, execution_comments = :c WHERE code = :code
            """), {"now": end_ts, "c": comments, "code": ot_code})

            if row[2]:
                _db.session.execute(text(
                    "UPDATE maintenance_notices SET status = 'Cerrado', closed_date = :d WHERE id = :id"
                ), {"id": row[2], "d": closed_date})

            _db.session.commit()
            _db.session.remove()
            return ot_code, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"close_ot error: {e}")
            return None, str(e)


def add_log_entry(app, data):
    """Agrega una entrada de bitacora a una OT.

    Returns: (ot_code, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            ot_code = data.get('ot_code', '').upper()
            row = _db.session.execute(text("SELECT id FROM work_orders WHERE code = :c"), {"c": ot_code}).fetchone()
            if not row:
                return None, f"OT {ot_code} no encontrada"
            ot_id = row[0]
            _db.session.execute(text("""
                INSERT INTO ot_log_entries (work_order_id, log_date, comment, log_type, created_at)
                VALUES (:wid, :d, :c, :t, NOW())
            """), {
                "wid": ot_id, "d": date.today().isoformat(),
                "c": data.get('comment', ''), "t": data.get('entry_type', 'NOTA'),
            })
            _db.session.commit()
            _db.session.remove()
            return ot_code, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"add_log_entry error: {e}")
            return None, str(e)


def start_ot(app, data):
    """Marca una OT como En Progreso, y propaga al aviso vinculado.

    Returns: (ot_code, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            ot_code = data.get('ot_code', '').upper()
            row = _db.session.execute(text("SELECT id, notice_id FROM work_orders WHERE code = :c"), {"c": ot_code}).fetchone()
            if not row:
                return None, f"OT {ot_code} no encontrada"
            now = datetime.utcnow().isoformat()[:19]
            _db.session.execute(text("UPDATE work_orders SET status = 'En Progreso', real_start_date = :now WHERE code = :c"), {"now": now, "c": ot_code})
            if row[1]:
                _db.session.execute(text("UPDATE maintenance_notices SET status = 'En Progreso', treatment_date = :d WHERE id = :id"), {"d": date.today().isoformat(), "id": row[1]})
            _db.session.commit()
            _db.session.remove()
            return ot_code, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"start_ot error: {e}")
            return None, str(e)


def reschedule_ot(app, data):
    """Reprograma una OT (cambia scheduled_date y la pone en Programada).

    Returns: (ot_code, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            ot_code = data.get('ot_code', '').upper()
            new_date = data.get('new_date', '')
            row = _db.session.execute(text("SELECT id FROM work_orders WHERE code = :c"), {"c": ot_code}).fetchone()
            if not row:
                return None, f"OT {ot_code} no encontrada"
            _db.session.execute(text("UPDATE work_orders SET scheduled_date = :d, status = 'Programada' WHERE code = :c"), {"d": new_date, "c": ot_code})
            _db.session.commit()
            _db.session.remove()
            return ot_code, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"reschedule_ot error: {e}")
            return None, str(e)


def edit_ot(app, data):
    """Edita campos whitelisted de una OT existente.

    Returns: (ot_code, changed_fields_list, error | None).
    """
    from bot.resolvers import resolve_taxonomy as _resolve_taxonomy
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            code = (data.get('ot_code') or data.get('code') or '').upper()
            if not code:
                return None, None, "Falta ot_code"
            row = _db.session.execute(text("SELECT id, notice_id FROM work_orders WHERE code = :c"), {"c": code}).fetchone()
            if not row:
                return None, None, f"OT {code} no encontrada"
            ot_id, notice_id = row[0], row[1]

            fields = data.get('fields') or {}

            tax_resolved, tax_names, tax_err = _resolve_taxonomy(_db.session, fields)
            if tax_err:
                return None, None, tax_err
            fields.update(tax_resolved)

            updates = {k: v for k, v in fields.items() if k in _OT_EDITABLE and v is not None}
            if not updates:
                return None, None, "No hay campos validos para actualizar"

            set_clause = ', '.join(f"{k} = :{k}" for k in updates)
            params = dict(updates)
            params['c'] = code
            _db.session.execute(text(f"UPDATE work_orders SET {set_clause} WHERE code = :c"), params)

            tax_keys = {'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}
            tax_updates = {k: v for k, v in updates.items() if k in tax_keys}
            if tax_updates and notice_id:
                n_set = ', '.join(f"{k} = :{k}" for k in tax_updates)
                tax_params = dict(tax_updates)
                tax_params['nid'] = notice_id
                _db.session.execute(text(f"UPDATE maintenance_notices SET {n_set} WHERE id = :nid"), tax_params)

            _db.session.commit()
            _db.session.remove()
            changed = [k for k in updates if k not in tax_keys] + tax_names
            return code, changed, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"edit_ot error: {e}")
            return None, None, str(e)
