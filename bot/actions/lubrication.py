"""Acciones del bot sobre lubricacion + helpers asociados.

Incluye:
  - register_lubrication: registra ejecucion sobre un punto.
  - register_lubrication_batch: idem pero para varios puntos del mismo equipo.
  - edit_lubrication: edita una ejecucion existente.
  - delete_lubrication: borra una ejecucion existente.
  - Helpers: format_point_label, resolve_lub_point_fuzzy,
    refresh_lub_point_from_executions.
"""
import logging
import re as _re
from datetime import datetime, date

logger = logging.getLogger(__name__)


_LUB_SELECT_COLS = (
    "lp.id, lp.code, lp.name, lp.frequency_days, lp.warning_days, lp.quantity_unit, "
    "e.tag, e.name, ar.name AS area_name, ln.name AS line_name, "
    "s.name AS system_name, c.name AS component_name"
)
_LUB_FROM_JOIN = (
    "FROM lubrication_points lp "
    "LEFT JOIN equipments e ON lp.equipment_id = e.id "
    "LEFT JOIN areas ar ON lp.area_id = ar.id "
    "LEFT JOIN lines ln ON lp.line_id = ln.id "
    "LEFT JOIN systems s ON lp.system_id = s.id "
    "LEFT JOIN components c ON lp.component_id = c.id"
)
_LUB_EXEC_EDITABLE = {'execution_date', 'executed_by', 'quantity_used', 'quantity_unit',
                      'comments', 'leak_detected', 'anomaly_detected', 'action_type'}


def format_point_label(row):
    """Recibe una fila del matcher (12 cols) y devuelve label legible
    '[Area] LINEA · TAG (Equipo) — Componente · Sistema'."""
    if not row:
        return ''
    area = row[8] if len(row) > 8 else None
    line = row[9] if len(row) > 9 else None
    tag = row[6] if len(row) > 6 else None
    eq_name = row[7] if len(row) > 7 else None
    sys_n = row[10] if len(row) > 10 else None
    comp = row[11] if len(row) > 11 else None
    parts = []
    if area: parts.append(f"[{area}]")
    if line: parts.append(line)
    eq_part = ''
    if tag and eq_name:
        eq_part = f"{tag} ({eq_name})"
    elif tag:
        eq_part = tag
    elif eq_name:
        eq_part = eq_name
    if eq_part:
        parts.append(eq_part)
    head = ' · '.join(parts)
    tail_parts = []
    if comp: tail_parts.append(comp)
    if sys_n: tail_parts.append(sys_n)
    tail = ' · '.join(tail_parts)
    if head and tail:
        return f"{head} — {tail}"
    return head or tail or (row[2] if len(row) > 2 else '') or (row[1] if len(row) > 1 else '')


def resolve_lub_point_fuzzy(_db, text, point_query):
    """Encuentra el mejor punto de lubricacion para un query libre.

    Estrategia en cascada:
      1) AND-strict con tokens + sinonimos.
      2) Si nada o ambiguo, OR-scoring: trae candidatos amplios; rankea
         por puntos de coincidencia.
      3) Si aun ambiguo, devuelve mensaje listando top 3 sugerencias.

    Returns: (row6tuple | None, err_msg | None).
    """
    from bot.resolvers import (
        fuzzy_tokens as _fuzzy_tokens,
        build_fuzzy_where as _build_fuzzy_where,
        COMPONENT_SYNONYMS as _COMPONENT_SYNONYMS,
    )

    tokens = _fuzzy_tokens(point_query)
    if not tokens:
        return None, None

    cols = ['lp.name', 'lp.code', 'e.name', 'e.tag', 's.name', 'c.name']
    base = f"SELECT {_LUB_SELECT_COLS} {_LUB_FROM_JOIN} WHERE lp.is_active = true"

    # Paso 1: AND-strict
    params = {}
    where_extra = _build_fuzzy_where(tokens, cols, params)
    sql = base + (" AND " + where_extra if where_extra else "") + " ORDER BY lp.code LIMIT 50"
    rows = _db.session.execute(text(sql), params).fetchall()

    def pick_best(rows):
        if not rows:
            return None, None
        if len(rows) == 1:
            return rows[0], None

        def alts_for(t):
            alts = {t}
            for key, syns in _COMPONENT_SYNONYMS.items():
                if t in key or any(t in y for y in syns):
                    alts.update(syns); alts.add(key)
            return alts

        _word_cache = {}
        def _word_match(token, text_blob):
            if not token or not text_blob:
                return False
            key = (token, text_blob)
            if key in _word_cache:
                return _word_cache[key]
            pat = r'(?<![a-z0-9])' + _re.escape(token) + r'(?![a-z0-9])'
            res = bool(_re.search(pat, text_blob))
            _word_cache[key] = res
            return res

        def score_row(r):
            code = (r[1] or '').lower()
            name = (r[2] or '').lower()
            tag = (r[6] or '').lower()
            eq_name = (r[7] or '').lower()
            area_n = (r[8] or '').lower() if len(r) > 8 else ''
            sys_n = (r[10] or '').lower() if len(r) > 10 else ''
            comp = (r[11] or '').lower() if len(r) > 11 else ''
            tag_full_match = all(
                any(_word_match(a, tag) for a in alts_for(t)) for t in tokens
            ) if tag else False
            s = 0
            if tag_full_match:
                s += 5 * len(tokens)
            for t in tokens:
                t_alts = alts_for(t)
                w = 0
                if any(a == tag for a in t_alts):
                    w = max(w, 4)
                elif any(_word_match(a, tag) for a in t_alts):
                    w = max(w, 3)
                if any(_word_match(a, code) for a in t_alts):
                    w = max(w, 2)
                if any(a in name or a in eq_name or a in area_n
                       or a in sys_n or a in comp for a in t_alts):
                    w = max(w, 1)
                s += w
            return s

        scored = sorted(
            [(score_row(r), -len(r[1] or ''), r) for r in rows],
            key=lambda x: (x[0], x[1]), reverse=True
        )
        scored = [(s, r) for s, _ln, r in scored]
        if scored[0][0] == 0:
            return None, None
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1], None
        return None, scored

    best, _scored = pick_best(rows)
    if best is not None:
        return best, None

    # Paso 2: OR-scoring sobre candidatos amplios
    or_params = {}
    or_subs = []
    for i, t in enumerate(tokens):
        alts = {t}
        for key, syns in _COMPONENT_SYNONYMS.items():
            if t in key or any(t in y for y in syns):
                alts.update(syns); alts.add(key)
        for j, a in enumerate(alts):
            k = f"or{i}_{j}"
            or_params[k] = f"%{a}%"
            or_subs.append(
                f"(lp.name ILIKE :{k} OR lp.code ILIKE :{k} "
                f"OR e.name ILIKE :{k} OR e.tag ILIKE :{k} "
                f"OR s.name ILIKE :{k} OR c.name ILIKE :{k})"
            )
    if or_subs:
        sql = base + " AND (" + " OR ".join(or_subs) + ") ORDER BY lp.code LIMIT 200"
        or_rows = _db.session.execute(text(sql), or_params).fetchall()
        best, scored = pick_best(or_rows)
        if best is not None:
            return best, None
        if scored:
            top = [r for s, r in scored if s > 0][:3]
            if top:
                opts_lines = []
                for i, r in enumerate(top, 1):
                    opts_lines.append(f"  {i}) {format_point_label(r)}")
                opts = '\n' + '\n'.join(opts_lines)
                return None, (f"No identifico univocamente '{point_query}'. "
                              f"¿Cual de estos es?:{opts}")

    return None, None


def refresh_lub_point_from_executions(_db, text, point_id):
    """Recalcula lubrication_points.last_service_date/next_due/semaphore
    basado en la ultima ejecucion restante (tras edit o delete)."""
    from utils.schedule_helpers import _calculate_lubrication_schedule
    point = _db.session.execute(text("""
        SELECT id, frequency_days, warning_days FROM lubrication_points WHERE id = :id
    """), {"id": point_id}).fetchone()
    if not point:
        return
    latest = _db.session.execute(text("""
        SELECT execution_date FROM lubrication_executions
        WHERE point_id = :id ORDER BY execution_date DESC, id DESC LIMIT 1
    """), {"id": point_id}).fetchone()
    if latest:
        next_due, semaphore = _calculate_lubrication_schedule(latest[0], point[1], point[2])
        _db.session.execute(text("""
            UPDATE lubrication_points
            SET last_service_date = :lsd, next_due_date = :nd, semaphore_status = :ss
            WHERE id = :id
        """), {"lsd": latest[0], "nd": next_due, "ss": semaphore, "id": point_id})
    else:
        _db.session.execute(text("""
            UPDATE lubrication_points
            SET last_service_date = NULL, next_due_date = NULL, semaphore_status = 'PENDIENTE'
            WHERE id = :id
        """), {"id": point_id})


def register_lubrication(app, data):
    """Registra ejecucion de lubricacion sobre un punto.

    Returns: (point_code, label, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        from utils.schedule_helpers import _calculate_lubrication_schedule
        try:
            point_id = data.get('point_id')
            point_code = (data.get('point_code') or '').strip()
            point_query = (data.get('point_query') or '').strip()

            row = None
            if point_id:
                row = _db.session.execute(text(
                    f"SELECT {_LUB_SELECT_COLS} {_LUB_FROM_JOIN} "
                    "WHERE lp.id = :id AND lp.is_active = true"
                ), {"id": point_id}).fetchone()
            elif point_code:
                row = _db.session.execute(text(
                    f"SELECT {_LUB_SELECT_COLS} {_LUB_FROM_JOIN} "
                    "WHERE lp.code = :c AND lp.is_active = true"
                ), {"c": point_code}).fetchone()
            elif point_query:
                row, err_msg = resolve_lub_point_fuzzy(_db, text, point_query)
                if not row and err_msg:
                    return None, None, err_msg

            if not row:
                return None, None, f"Punto de lubricacion no encontrado para '{point_query or point_code or point_id}'. Verifica nombre/equipo o pasa el codigo (ej: LUB-D8-CHM-MOT)."

            pid = row[0]; pcode = row[1]; pname = row[2]
            freq_days = row[3]; warn_days = row[4]; qty_unit = row[5]
            label = format_point_label(row) or pname

            execution_date = data.get('execution_date') or date.today().isoformat()
            executed_by = data.get('executed_by') or 'MANTENIMIENTO'
            quantity_used = data.get('quantity_used')
            comments = data.get('comments')
            leak = bool(data.get('leak_detected', False))
            anomaly = bool(data.get('anomaly_detected', False))
            action_type = data.get('action_type') or 'SERVICIO'

            _db.session.execute(text("""
                INSERT INTO lubrication_executions
                (point_id, execution_date, action_type, quantity_used, quantity_unit,
                 executed_by, leak_detected, anomaly_detected, comments, created_at)
                VALUES (:pid, :ed, :at, :qu, :unit, :eb, :leak, :anom, :com, :now)
            """), {
                "pid": pid, "ed": execution_date, "at": action_type,
                "qu": quantity_used, "unit": data.get('quantity_unit') or qty_unit or 'L',
                "eb": executed_by, "leak": leak, "anom": anomaly, "com": comments,
                "now": datetime.utcnow()
            })

            # Solo avanza el cronograma si esta ejecucion es la mas reciente
            current_last = _db.session.execute(text(
                "SELECT last_service_date FROM lubrication_points WHERE id = :id"
            ), {"id": pid}).scalar()
            if (not current_last) or (str(execution_date) >= str(current_last)):
                next_due, semaphore = _calculate_lubrication_schedule(execution_date, freq_days, warn_days)
                _db.session.execute(text("""
                    UPDATE lubrication_points
                    SET last_service_date = :lsd, next_due_date = :nd, semaphore_status = :ss
                    WHERE id = :id
                """), {"lsd": execution_date, "nd": next_due, "ss": semaphore, "id": pid})

            _db.session.commit()
            _db.session.remove()
            return pcode or f"id:{pid}", label, None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"register_lubrication error: {e}")
            return None, None, str(e)


def register_lubrication_batch(app, data):
    """Registra lubricaciones para varios puntos del mismo equipo.

    data['points']: lista de strings (point_query) o dicts.

    Returns: ({'ok': [(code, name)], 'fail': [(query, err)]}, err | None).
    """
    points = data.get('points')
    if not isinstance(points, list) or not points:
        return None, "Falta lista 'points' con al menos un elemento."
    common = {k: v for k, v in data.items() if k != 'points'}
    ok_list = []
    fail_list = []
    for pt in points:
        if isinstance(pt, str):
            single = {**common, 'point_query': pt}
            label = pt
        elif isinstance(pt, dict):
            single = {**common, **pt}
            label = pt.get('point_query') or pt.get('point_code') or str(pt.get('point_id') or pt)
        else:
            fail_list.append((str(pt), "tipo invalido"))
            continue
        code, pname, err = register_lubrication(app, single)
        if code:
            ok_list.append((code, pname))
        else:
            fail_list.append((label, err or "error desconocido"))
    return {'ok': ok_list, 'fail': fail_list}, None


def edit_lubrication(app, data):
    """Edita campos de una ejecucion de lubricacion existente.

    Returns: (point_code, point_name, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            exec_id = data.get('exec_id') or data.get('execution_id')
            if not exec_id:
                return None, None, "Falta exec_id"
            row = _db.session.execute(text("""
                SELECT le.id, le.point_id, lp.code, lp.name
                FROM lubrication_executions le
                JOIN lubrication_points lp ON le.point_id = lp.id
                WHERE le.id = :id
            """), {"id": exec_id}).fetchone()
            if not row:
                return None, None, f"Ejecucion exec_id:{exec_id} no encontrada"

            fields = data.get('fields') or {}
            updates = {k: v for k, v in fields.items() if k in _LUB_EXEC_EDITABLE and v is not None}
            if not updates:
                return None, None, "No hay campos validos para actualizar"

            set_clause = ', '.join(f"{k} = :{k}" for k in updates)
            params = dict(updates)
            params['id'] = exec_id
            _db.session.execute(text(f"UPDATE lubrication_executions SET {set_clause} WHERE id = :id"), params)

            refresh_lub_point_from_executions(_db, text, row[1])
            _db.session.commit()
            _db.session.remove()
            return row[2] or f"id:{row[1]}", row[3], None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"edit_lubrication error: {e}")
            return None, None, str(e)


def delete_lubrication(app, data):
    """Borra una ejecucion de lubricacion por id.

    Returns: (point_code, point_name, error | None).
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            exec_id = data.get('exec_id') or data.get('execution_id')
            if not exec_id:
                return None, None, "Falta exec_id"
            row = _db.session.execute(text("""
                SELECT le.id, le.point_id, lp.code, lp.name
                FROM lubrication_executions le
                JOIN lubrication_points lp ON le.point_id = lp.id
                WHERE le.id = :id
            """), {"id": exec_id}).fetchone()
            if not row:
                return None, None, f"Ejecucion exec_id:{exec_id} no encontrada"

            _db.session.execute(text("DELETE FROM lubrication_executions WHERE id = :id"), {"id": exec_id})
            refresh_lub_point_from_executions(_db, text, row[1])
            _db.session.commit()
            _db.session.remove()
            return row[2] or f"id:{row[1]}", row[3], None
        except Exception as e:
            _db.session.rollback()
            try: _db.session.remove()
            except Exception: pass
            logger.error(f"delete_lubrication error: {e}")
            return None, None, str(e)
