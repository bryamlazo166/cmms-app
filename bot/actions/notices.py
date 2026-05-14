"""Acciones del bot sobre avisos de mantenimiento.

Cubre: crear, promover/degradar (cambiar scope), editar campos whitelisted.
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)


_NOTICE_EDITABLE = {'description', 'criticality', 'priority', 'maintenance_type',
                    'cancellation_reason', 'status', 'failure_mode', 'failure_category',
                    'closed_date',
                    'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}


def create_notice(app, data):
    """Crea un aviso nuevo, resolviendo jerarquia desde tag/nombre.

    Returns: (code, notice_id, error | None). Tambien anota
    `data['_resolved_scope']` y `data['_resolved_event_date']` para que
    el dispatcher arme el mensaje de respuesta.
    """
    from bot.resolvers import resolve_equipment as _resolve_equipment
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            max_id = _db.session.execute(text("SELECT COALESCE(MAX(id), 0) FROM maintenance_notices")).scalar()
            code = f"AV-{str(max_id + 1).zfill(4)}"

            eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = _resolve_equipment(_db, text, data)

            scope = (data.get('scope') or '').strip().upper() or None
            if scope not in {'PLAN', 'FUERA_PLAN', 'GENERAL'}:
                scope = None
            if not scope:
                scope = 'PLAN' if eq_id else 'FUERA_PLAN'
            if scope == 'PLAN' and not eq_id:
                scope = 'FUERA_PLAN'

            desc_parts = [data.get('description', 'Reporte desde Telegram')]
            if data.get('failure_mode'):
                desc_parts.append(f"[Modo de falla: {data['failure_mode']}]")
            if data.get('failure_category'):
                desc_parts.append(f"[Tipo: {data['failure_category']}]")

            free_loc = data.get('free_location')
            blockage = data.get('blockage_object')
            if blockage:
                desc_parts.append(f"[Objeto: {blockage}]")

            req_date = (data.get('event_date') or '').strip() or date.today().isoformat()
            data['_resolved_event_date'] = req_date

            _db.session.execute(text("""
                INSERT INTO maintenance_notices (code, description, criticality, priority, request_date,
                    maintenance_type, status, reporter_name, reporter_type,
                    area_id, line_id, equipment_id, system_id, component_id, rotative_asset_id, shift,
                    scope, free_location, failure_mode, failure_category, blockage_object)
                VALUES (:code, :desc, :crit, :prio, :rdate, :mtype, 'Pendiente', :reporter, 'telegram',
                    :ar, :ln, :eq, :sys, :comp, :ra, :shift, :scope, :loc, :fm, :fc, :bo)
            """), {
                "code": code, "desc": ' | '.join(desc_parts),
                "crit": data.get('criticality', 'Media'), "prio": data.get('priority', 'Normal'),
                "rdate": req_date, "mtype": data.get('maintenance_type', 'Correctivo'),
                "reporter": data.get('reporter_name', 'Bot Telegram'),
                "ar": ar_id, "ln": ln_id, "eq": eq_id, "sys": sys_id, "comp": comp_id, "ra": ra_id,
                "shift": data.get('shift'),
                "scope": scope, "loc": free_loc,
                "fm": data.get('failure_mode'), "fc": data.get('failure_category'), "bo": blockage,
            })
            _db.session.commit()
            nid = _db.session.execute(text("SELECT id FROM maintenance_notices WHERE code = :c"), {"c": code}).scalar()
            _db.session.remove()
            data['_resolved_scope'] = scope
            return code, nid, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"create_notice error: {e}")
            return None, None, str(e)


def promote_notice(app, data):
    """Cambia el scope de un aviso existente; opcionalmente lo enlaza a un equipo.

    Cuando promueve a PLAN, tambien propaga la jerarquia a todas las OTs
    vinculadas. Reversible: PLAN -> FUERA_PLAN/GENERAL pasando solo target_scope.

    Returns: (code, (current_scope, target_scope, n_ots), error | None).
    """
    from bot.resolvers import resolve_equipment as _resolve_equipment
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            code = (data.get('notice_code') or data.get('code') or '').upper()
            if not code:
                return None, None, "Falta notice_code"
            row = _db.session.execute(text("""
                SELECT id, scope FROM maintenance_notices WHERE code = :c
            """), {"c": code}).fetchone()
            if not row:
                return None, None, f"Aviso {code} no encontrado"
            nid, current_scope = row[0], row[1]

            target_scope = (data.get('target_scope') or '').strip().upper() or 'PLAN'
            if target_scope not in {'PLAN', 'FUERA_PLAN', 'GENERAL'}:
                return None, None, f"Scope invalido: {target_scope}"

            eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = _resolve_equipment(_db, text, data)

            if target_scope == 'PLAN' and not eq_id:
                return None, None, "Para promover a PLAN debes indicar un equipo (equipment_tag o equipment_id)"

            updates = {"scope": target_scope}
            if target_scope == 'PLAN':
                updates.update({
                    "area_id": ar_id, "line_id": ln_id, "equipment_id": eq_id,
                    "system_id": sys_id, "component_id": comp_id, "rotative_asset_id": ra_id,
                    "free_location": None,
                })
            elif target_scope == 'GENERAL':
                updates.update({
                    "area_id": None, "line_id": None, "equipment_id": None,
                    "system_id": None, "component_id": None, "rotative_asset_id": None,
                })
                if data.get('free_location'):
                    updates["free_location"] = data['free_location']
            else:  # FUERA_PLAN
                updates.update({
                    "area_id": None, "line_id": None, "equipment_id": None,
                    "system_id": None, "component_id": None, "rotative_asset_id": None,
                })
                if data.get('free_location'):
                    updates["free_location"] = data['free_location']

            set_clause = ', '.join(f"{k} = :{k}" for k in updates)
            params = dict(updates)
            params['nid'] = nid
            _db.session.execute(text(f"UPDATE maintenance_notices SET {set_clause} WHERE id = :nid"), params)

            wo_updates = {k: v for k, v in updates.items() if k in {
                'area_id', 'line_id', 'equipment_id', 'system_id', 'component_id', 'rotative_asset_id'
            }}
            if wo_updates:
                wo_set = ', '.join(f"{k} = :{k}" for k in wo_updates)
                wo_params = dict(wo_updates)
                wo_params['nid'] = nid
                _db.session.execute(text(f"UPDATE work_orders SET {wo_set} WHERE notice_id = :nid"), wo_params)

            _db.session.commit()
            n_ots = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE notice_id = :nid"), {"nid": nid}).scalar() or 0
            _db.session.remove()
            return code, (current_scope, target_scope, n_ots), None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"promote_notice error: {e}")
            return None, None, str(e)


def edit_notice(app, data):
    """Edita campos whitelisted de un aviso existente, propagando taxonomia a OTs.

    Returns: (code, changed_fields_list, error | None).
    """
    from bot.resolvers import resolve_taxonomy as _resolve_taxonomy
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            code = (data.get('notice_code') or data.get('code') or '').upper()
            if not code:
                return None, None, "Falta notice_code"
            row = _db.session.execute(text("SELECT id FROM maintenance_notices WHERE code = :c"), {"c": code}).fetchone()
            if not row:
                return None, None, f"Aviso {code} no encontrado"
            notice_id = row[0]

            fields = data.get('fields') or {}
            tax_resolved, tax_names, tax_err = _resolve_taxonomy(_db.session, fields)
            if tax_err:
                return None, None, tax_err
            fields.update(tax_resolved)

            updates = {k: v for k, v in fields.items() if k in _NOTICE_EDITABLE and v is not None}
            if not updates:
                return None, None, "No hay campos validos para actualizar"

            set_clause = ', '.join(f"{k} = :{k}" for k in updates)
            params = dict(updates)
            params['c'] = code
            _db.session.execute(text(f"UPDATE maintenance_notices SET {set_clause} WHERE code = :c"), params)

            tax_keys = {'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}
            tax_updates = {k: v for k, v in updates.items() if k in tax_keys}
            if tax_updates:
                ot_set = ', '.join(f"{k} = :{k}" for k in tax_updates)
                tax_params = dict(tax_updates)
                tax_params['nid'] = notice_id
                _db.session.execute(text(f"UPDATE work_orders SET {ot_set} WHERE notice_id = :nid"), tax_params)

            _db.session.commit()
            _db.session.remove()
            changed = [k for k in updates if k not in tax_keys] + tax_names
            return code, changed, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"edit_notice error: {e}")
            return None, None, str(e)
