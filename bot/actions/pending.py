"""Acciones del bot sobre pendientes (`/p`, `/listo`, `/pendientes`).

Un pendiente es lo que hay que hacer y todavia no es una OT. Se anota de
corrido y el bot le saca el plazo ("en 2 semanas"), la prioridad ("urgente") y
el equipo/componente del arbol, sin pasar por el modelo: es determinista, para
que anotar sea instantaneo y barato.

Al terminarlo (`/listo PEND-0007 ...`) pasa a HECHO con autor, fecha y
comentario: sale de la lista activa y queda como bitacora. Nunca se borra.
"""
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)


def _tag_segments(tag):
    """'SEC2-TH1' -> {'sec2-th1', 'sec2', 'th1'} para reconocerlo escrito suelto."""
    low = (tag or '').strip().lower()
    if not low:
        return set()
    parts = {low}
    parts.update(p for p in re.split(r'[-_/\s]+', low) if len(p) >= 2)
    return parts


def find_equipment_in_text(db, text_module, raw):
    """Busca el equipo nombrado en el texto. Devuelve (equipment | None, ambiguos).

    `equipment` es (id, tag, name). `ambiguos` trae los candidatos cuando el
    texto no alcanza para decidir — el bot los muestra y pide el tag exacto en
    vez de anclar el pendiente al equipo equivocado.
    """
    from bot.resolvers import fuzzy_tokens, score_fuzzy_candidates

    if not raw:
        return None, []
    low = f" {raw.lower()} "
    rows = db.session.execute(text_module("""
        SELECT e.id, e.tag, e.name, COALESCE(l.name, ''), COALESCE(a.name, '')
        FROM equipments e
        LEFT JOIN lines l ON l.id = e.line_id
        LEFT JOIN areas a ON a.id = l.area_id
    """)).fetchall()

    exact, partial = [], []
    for eid, tag, name, line_name, area_name in rows:
        cand = (eid, tag, name, line_name, area_name)
        segs = _tag_segments(tag)
        if not segs:
            continue
        full = (tag or '').strip().lower()
        if full and re.search(r'(?<![\w-])' + re.escape(full) + r'(?![\w-])', low):
            exact.append(cand)
        elif any(re.search(r'(?<![\w-])' + re.escape(s) + r'(?![\w-])', low) for s in segs):
            partial.append(cand)

    pool = exact + partial
    if not pool:
        return None, []
    if len(pool) == 1:
        return pool[0][:3], []

    # Varios equipos comparten el fragmento (TH1 existe en varias lineas):
    # decide el resto del texto ("del secador 2"), que es como habla la gente.
    # Escribir el tag completo suma, pero no gana por si solo: "el TH1 del
    # secador 2" debe caer en SEC2-TH1 aunque exista un equipo con tag TH1.
    from bot.resolvers import normalize_token
    user_tokens = {normalize_token(t) for t in fuzzy_tokens(raw)}

    def _score(cand):
        blob = f"{cand[1]} {cand[2]} {cand[3]} {cand[4]}".lower()
        cand_tokens = {normalize_token(t)
                       for t in re.split(r'[\s,;/#-]+', blob) if t}
        return len(user_tokens & cand_tokens) + (1 if cand in exact else 0)

    scored = sorted(((_score(c), c) for c in pool), key=lambda x: x[0], reverse=True)
    if scored[0][0] > scored[1][0]:
        return scored[0][1][:3], []
    # Empate: mejor no anclarlo que anclarlo mal — el bot muestra los candidatos.
    return None, [c[:3] for c in pool[:6]]


def create_pending(app, raw_text, author, source='telegram', chat_id=None):
    """Crea un pendiente desde texto libre.

    Devuelve (task_dict | None, ambiguos, error). `ambiguos` no es un error:
    el pendiente igual se crea, pero sin equipo, y el bot lo dice.
    """
    from utils.pending_helpers import parse_due_phrase, infer_priority

    body = (raw_text or '').strip()
    if not body:
        return None, [], "Escribe que hay que hacer."

    with app.app_context():
        from database import db as _db
        from sqlalchemy import text as _t
        from models import PendingTask
        try:
            due, clean = parse_due_phrase(body)
            priority = infer_priority(body)

            equipment, ambiguos = find_equipment_in_text(_db, _t, body)
            eq_id = ln_id = ar_id = sys_id = comp_id = ra_id = None
            if equipment:
                from bot.resolvers import resolve_equipment
                eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = resolve_equipment(
                    _db, _t, {'equipment_tag': equipment[1], '_user_text': body})

            # OT mencionada en el texto (OT-0034) -> queda vinculada
            wo_id = None
            m = re.search(r'\b(OT-\d{3,5})\b', body, re.I)
            if m:
                row = _db.session.execute(
                    _t("SELECT id FROM work_orders WHERE UPPER(code) = :c"),
                    {"c": m.group(1).upper()}).fetchone()
                if row:
                    wo_id = row[0]

            task = PendingTask(
                description=clean or body,
                due_date=due,
                priority=priority,
                status='Pendiente',
                area_id=ar_id, line_id=ln_id, equipment_id=eq_id,
                system_id=sys_id, component_id=comp_id, rotative_asset_id=ra_id,
                work_order_id=wo_id,
                created_by=author,
                source=source,
            )
            _db.session.add(task)
            _db.session.flush()
            task.code = f"PEND-{str(task.id).zfill(4)}"
            _db.session.commit()
            out = task.to_dict()
            _db.session.remove()
            return out, ambiguos, None
        except Exception as e:
            _db.session.rollback()
            logger.exception(f"create_pending error: {e}")
            return None, [], str(e)


def close_pending(app, code, author, comment=None, cancel=False):
    """Marca un pendiente como HECHO (o ANULADO). Devuelve (task_dict, error)."""
    from utils.pending_helpers import close_payload, PENDING_DONE, PENDING_CANCELLED

    code = (code or '').strip().upper()
    if not code.startswith('PEND-'):
        return None, "El codigo debe ser PEND-XXXX (lo ves con /pendientes)."

    with app.app_context():
        from database import db as _db
        from models import PendingTask
        try:
            task = PendingTask.query.filter_by(code=code).first()
            if not task:
                return None, f"{code} no existe."
            if task.status != 'Pendiente':
                return None, f"{code} ya estaba como {task.status.lower()}."
            payload = close_payload(
                PENDING_CANCELLED if cancel else PENDING_DONE, author, comment)
            for k, v in payload.items():
                setattr(task, k, v)
            _db.session.commit()
            out = task.to_dict()
            _db.session.remove()
            return out, None
        except Exception as e:
            _db.session.rollback()
            logger.exception(f"close_pending error: {e}")
            return None, str(e)


def list_pending(app, limit=25, only_overdue=False):
    """Pendientes abiertos: primero los vencidos, luego por fecha y prioridad."""
    from utils.pending_helpers import overdue_days

    with app.app_context():
        from database import db as _db
        from models import PendingTask
        try:
            tasks = (PendingTask.query.filter_by(status='Pendiente')
                     .order_by(PendingTask.id.desc()).all())
            rows = []
            today = date.today()
            for t in tasks:
                d = t.to_dict()
                d['overdue_days'] = overdue_days(t.due_date, today)
                rows.append(d)
            if only_overdue:
                rows = [r for r in rows if (r['overdue_days'] or -999) >= 0]
            prio_rank = {'Alta': 0, 'Normal': 1, 'Baja': 2}

            def _orden(r):
                od = r['overdue_days']
                grupo = 2 if od is None else (0 if od >= 0 else 1)
                return (grupo,                       # vencidos, luego con fecha, luego sin fecha
                        -(od if od is not None else 0),   # mas atrasado / mas proximo antes
                        prio_rank.get(r['priority'], 1),
                        -r['id'])

            rows.sort(key=_orden)
            _db.session.remove()
            return rows[:limit], len(rows)
        except Exception as e:
            logger.exception(f"list_pending error: {e}")
            return [], 0
