"""Copiloto de diagnóstico — RCA asistido por IA.

Cuando se crea un aviso (por cualquier canal: WhatsApp, Telegram o web), este
módulo arma en segundo plano un PRE-DIAGNÓSTICO para el personal de
mantenimiento cruzando el conocimiento que ya vive en el CMMS:

  · RAG semántico (utils.embeddings.semantic_search) → casos históricos
    parecidos (OTs cerradas y avisos previos, con lo que se hizo).
  · failure_catalog.recommended_action → acción recomendada del modo de falla.
  · spare_parts del componente + repuestos más usados en el historial del
    equipo → lista de repuestos probables CON su código real de la BD.
  · DeepSeek → causa raíz probable, pasos de acción y herramientas.

Reglas de privacidad (CRÍTICAS):
  · El resultado se guarda en la tabla `notice_rca`, NUNCA en
    maintenance_notices.description (ese texto se reenvía al grupo de
    producción y filtraría el diagnóstico al personal que reporta).
  · Solo sale a: (a) el grupo de WhatsApp de MANTENIMIENTO
    (WHATSAPP_MAINT_GROUP_JID) vía la cola `wa_outbox`, y (b) la ficha del
    aviso en el CMMS web (que el personal de producción no puede abrir porque
    no tiene cuenta).

Los códigos de repuesto SIEMPRE provienen de la BD; la IA solo SELECCIONA de la
lista que se le entrega (por índice), nunca inventa códigos.
"""
import os
import json
import time
import logging
import threading
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'

_tables_ready = False
_tables_lock = threading.Lock()


# ── Creación idempotente de tablas (dialect-aware: postgres + sqlite tests) ──

def ensure_rca_tables(app):
    """Crea notice_rca y wa_outbox si no existen. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return True
    with _tables_lock:
        if _tables_ready:
            return True
        try:
            from sqlalchemy import text
            from database import db as _db
            with app.app_context():
                is_pg = _db.engine.dialect.name == 'postgresql'
                id_col = "id SERIAL PRIMARY KEY" if is_pg else "id INTEGER PRIMARY KEY AUTOINCREMENT"
                _db.session.execute(text(
                    "CREATE TABLE IF NOT EXISTS notice_rca ("
                    f"{id_col}, "
                    "notice_id INTEGER UNIQUE NOT NULL, "
                    "notice_code VARCHAR(20), "
                    "payload TEXT, "
                    "summary TEXT, "
                    "model VARCHAR(40), "
                    "confidence VARCHAR(10), "
                    "status VARCHAR(12) DEFAULT 'ok', "
                    "error TEXT, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                ))
                _db.session.execute(text(
                    "CREATE TABLE IF NOT EXISTS wa_outbox ("
                    f"{id_col}, "
                    "to_jid VARCHAR(80) NOT NULL, "
                    "body TEXT NOT NULL, "
                    "media_base64 TEXT, "
                    "media_type VARCHAR(10), "
                    "context VARCHAR(60), "
                    "status VARCHAR(12) DEFAULT 'pending', "
                    "attempts INTEGER DEFAULT 0, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                    "claimed_at TIMESTAMP, "
                    "sent_at TIMESTAMP)"
                ))
                # Grupos de WhatsApp de MANTENIMIENTO a los que se reenvía el
                # RCA. Se gestiona desde /admin/whatsapp-users. Pueden ser varios.
                _db.session.execute(text(
                    "CREATE TABLE IF NOT EXISTS rca_maint_groups ("
                    f"{id_col}, "
                    "jid VARCHAR(80) UNIQUE NOT NULL, "
                    "nombre VARCHAR(120), "
                    "activo BOOLEAN DEFAULT TRUE, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                ))
                _db.session.commit()
            _tables_ready = True
            return True
        except Exception as e:
            logger.warning(f"ensure_rca_tables no pudo crear tablas: {e}")
            return False


# ── Cola de salida de WhatsApp (para envíos asíncronos al grupo mtto) ────────

def enqueue_wa_message(app, to_jid, body, context=None,
                       media_base64=None, media_type=None):
    """Encola un mensaje para que el gateway lo envíe por WhatsApp. Devuelve id o None."""
    if not to_jid or not body:
        return None
    if not ensure_rca_tables(app):
        return None
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            row = _db.session.execute(text(
                "INSERT INTO wa_outbox (to_jid, body, media_base64, media_type, context, status) "
                "VALUES (:to, :body, :mb, :mt, :ctx, 'pending')"
            ), {"to": to_jid, "body": body, "mb": media_base64,
                "mt": media_type, "ctx": context})
            _db.session.commit()
            # id del insert (portable): último pendiente a ese jid con ese context
            nid = _db.session.execute(text(
                "SELECT MAX(id) FROM wa_outbox WHERE to_jid = :to"), {"to": to_jid}).scalar()
        return nid
    except Exception as e:
        logger.error(f"enqueue_wa_message error: {e}")
        return None


def get_maint_group_jids(app):
    """JIDs de los grupos de MANTENIMIENTO activos a los que va el RCA.

    Fuente principal: tabla rca_maint_groups (gestionada desde el panel
    /admin/whatsapp-users). Fallback de compatibilidad: la env
    WHATSAPP_MAINT_GROUP_JID (uno o varios JIDs separados por coma) si la
    tabla está vacía. Devuelve lista de JIDs.
    """
    jids = []
    if ensure_rca_tables(app):
        try:
            from sqlalchemy import text
            from database import db as _db
            with app.app_context():
                rows = _db.session.execute(text(
                    "SELECT jid FROM rca_maint_groups WHERE activo = TRUE ORDER BY id"
                )).fetchall()
                jids = [r[0] for r in rows if r[0]]
        except Exception as e:
            logger.warning(f"get_maint_group_jids error: {e}")
    if not jids:
        env = (os.getenv('WHATSAPP_MAINT_GROUP_JID') or '').strip()
        if env:
            jids = [j.strip() for j in env.split(',') if j.strip()]
    return jids


def claim_outbox(app, limit=5, reclaim_seconds=180):
    """Reclama mensajes pendientes para envío (los marca 'sending').

    Devuelve lista de dicts {id, to, body, media_base64, media_type}. Antes
    de reclamar, resetea a 'pending' los 'sending' colgados (gateway caído).
    """
    if not ensure_rca_tables(app):
        return []
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            is_pg = _db.engine.dialect.name == 'postgresql'
            # 1. Reclamar 'sending' viejos (gateway murió sin hacer ack)
            if is_pg:
                _db.session.execute(text(
                    "UPDATE wa_outbox SET status='pending' WHERE status='sending' "
                    "AND claimed_at < (CURRENT_TIMESTAMP - (:s || ' seconds')::interval)"
                ), {"s": str(reclaim_seconds)})
            else:
                _db.session.execute(text(
                    "UPDATE wa_outbox SET status='pending' WHERE status='sending' "
                    "AND claimed_at < datetime('now', :s)"
                ), {"s": f'-{reclaim_seconds} seconds'})
            # 2. Seleccionar pendientes
            rows = _db.session.execute(text(
                "SELECT id, to_jid, body, media_base64, media_type FROM wa_outbox "
                "WHERE status='pending' ORDER BY id LIMIT :lim"
            ), {"lim": limit}).fetchall()
            ids = [r[0] for r in rows]
            if ids:
                # 3. Marcarlos 'sending'
                _db.session.execute(text(
                    "UPDATE wa_outbox SET status='sending', claimed_at=CURRENT_TIMESTAMP, "
                    "attempts = attempts + 1 WHERE id = ANY(:ids)" if is_pg else
                    f"UPDATE wa_outbox SET status='sending', claimed_at=CURRENT_TIMESTAMP, "
                    f"attempts = attempts + 1 WHERE id IN ({','.join(str(i) for i in ids)})"
                ), ({"ids": ids} if is_pg else {}))
                _db.session.commit()
            return [{"id": r[0], "to": r[1], "body": r[2],
                     "media_base64": r[3], "media_type": r[4]} for r in rows]
    except Exception as e:
        logger.warning(f"claim_outbox error: {e}")
        return []


def ack_outbox(app, results):
    """Marca el resultado de cada envío. results: [{id, ok}]."""
    if not results:
        return
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            for r in results:
                mid = r.get('id')
                if mid is None:
                    continue
                if r.get('ok'):
                    _db.session.execute(text(
                        "UPDATE wa_outbox SET status='sent', sent_at=CURRENT_TIMESTAMP WHERE id=:id"
                    ), {"id": mid})
                else:
                    # Reintentar hasta 3 veces; luego marcar error
                    _db.session.execute(text(
                        "UPDATE wa_outbox SET status = CASE WHEN attempts >= 3 THEN 'error' ELSE 'pending' END "
                        "WHERE id=:id"
                    ), {"id": mid})
            _db.session.commit()
    except Exception as e:
        logger.warning(f"ack_outbox error: {e}")


# ── Recolección de contexto para el diagnóstico ──────────────────────────────

def _load_notice_context(session, text, notice_id):
    """Carga el aviso + su taxonomía legible. Devuelve dict o None."""
    row = session.execute(text(
        "SELECT n.id, n.code, n.description, n.failure_mode, n.failure_category, "
        "       n.criticality, n.blockage_object, "
        "       n.equipment_id, n.component_id, n.system_id, "
        "       e.tag, e.name, l.name, a.name, c.name, s.name, n.rotative_asset_id "
        "FROM maintenance_notices n "
        "LEFT JOIN equipments e ON n.equipment_id = e.id "
        "LEFT JOIN lines l ON n.line_id = l.id "
        "LEFT JOIN areas a ON n.area_id = a.id "
        "LEFT JOIN components c ON n.component_id = c.id "
        "LEFT JOIN systems s ON n.system_id = s.id "
        "WHERE n.id = :id"
    ), {"id": notice_id}).fetchone()
    if not row:
        return None
    parts = [row[13] or '', row[12] or '', f"[{row[10]}] {row[11]}" if row[10] else (row[11] or '')]
    if row[15]:
        parts.append(row[15])
    if row[14]:
        parts.append(row[14])
    path = ' › '.join(p for p in parts if p)
    return {
        "id": row[0], "code": row[1], "description": row[2] or '',
        "failure_mode": row[3], "failure_category": row[4],
        "criticality": row[5], "blockage_object": row[6],
        "equipment_id": row[7], "component_id": row[8], "system_id": row[9],
        "equipment_tag": row[10], "equipment_name": row[11],
        "component_name": row[14], "system_name": row[15], "path": path,
        "rotative_asset_id": row[16],
    }


def _qty_int(v):
    """Normaliza una cantidad (AVG puede venir float) a entero o None."""
    try:
        n = int(round(float(v)))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _collect_hard_spares(session, text, ctx, limit=12):
    """Repuestos con CÓDIGO y CANTIDAD REALES de la BD: historial + catálogo.

    Devuelve lista de dicts {name, code, qty, source}. Del historial de OTs
    cerradas del equipo se toma la cantidad típica (promedio por OT). Los
    códigos y cantidades vienen SIEMPRE de la BD — la IA no los genera.
    """
    spares = []
    seen = set()

    def _add(name, code, source, qty=None):
        key = (name or '').strip().lower() + '|' + (code or '').strip().lower()
        if not name or key in seen:
            return
        seen.add(key)
        spares.append({"name": name.strip(), "code": (code or '').strip(),
                       "qty": qty, "source": source})

    # 1. Repuestos usados en OTs cerradas del equipo (historial) — con cantidad
    if ctx.get('equipment_id'):
        try:
            rows = session.execute(text(
                "SELECT w.name, w.code, ROUND(AVG(m.quantity)) AS qty, COUNT(*) AS n "
                "FROM ot_materials m "
                "JOIN work_orders o ON m.work_order_id = o.id "
                "JOIN warehouse_items w ON m.item_id = w.id "
                "WHERE o.equipment_id = :eq AND m.item_type = 'warehouse' AND o.status = 'Cerrada' "
                "GROUP BY w.name, w.code ORDER BY n DESC LIMIT 8"
            ), {"eq": ctx['equipment_id']}).fetchall()
            for r in rows:
                _add(r[0], r[1], 'historial', qty=_qty_int(r[2]))
        except Exception as e:
            logger.debug(f"historial repuestos lookup: {e}")

    # 2. BOM del activo rotativo vinculado (conectado a almacén, con cantidad)
    if ctx.get('rotative_asset_id'):
        try:
            rows = session.execute(text(
                "SELECT COALESCE(w.name, b.free_text) AS name, w.code, b.quantity "
                "FROM rotative_asset_bom b "
                "LEFT JOIN warehouse_items w ON b.warehouse_item_id = w.id "
                "WHERE b.rotative_asset_id = :ra ORDER BY b.id LIMIT 10"
            ), {"ra": ctx['rotative_asset_id']}).fetchall()
            for r in rows:
                _add(r[0], r[1], 'BOM', qty=_qty_int(r[2]))
        except Exception as e:
            logger.debug(f"BOM rotativo lookup: {e}")

    # 3. Catálogo de repuestos del componente (sin cantidad de uso)
    if ctx.get('component_id'):
        try:
            rows = session.execute(text(
                "SELECT name, code, brand FROM spare_parts WHERE component_id = :c ORDER BY name"
            ), {"c": ctx['component_id']}).fetchall()
            for r in rows:
                _add(r[0], r[1], 'catálogo')
        except Exception as e:
            logger.debug(f"spare_parts lookup: {e}")

    return spares[:limit]


def _collect_hard_tools(session, text, ctx, limit=10):
    """Herramientas REALES usadas en OTs cerradas del equipo (con código y cant).

    Devuelve lista de dicts {name, code, qty}. Vienen de ot_materials
    (item_type='tool') → tabla tools; la IA no inventa estos datos.
    """
    tools = []
    seen = set()
    if not ctx.get('equipment_id'):
        return tools
    try:
        rows = session.execute(text(
            "SELECT t.name, t.code, ROUND(AVG(m.quantity)) AS qty, COUNT(*) AS n "
            "FROM ot_materials m "
            "JOIN work_orders o ON m.work_order_id = o.id "
            "JOIN tools t ON m.item_id = t.id "
            "WHERE o.equipment_id = :eq AND m.item_type = 'tool' AND o.status = 'Cerrada' "
            "GROUP BY t.name, t.code ORDER BY n DESC LIMIT :lim"
        ), {"eq": ctx['equipment_id'], "lim": limit}).fetchall()
        for r in rows:
            key = (r[0] or '').strip().lower()
            if r[0] and key not in seen:
                seen.add(key)
                tools.append({"name": r[0].strip(), "code": (r[1] or '').strip(),
                              "qty": _qty_int(r[2])})
    except Exception as e:
        logger.debug(f"historial herramientas lookup: {e}")
    return tools


def _collect_similar_cases(session, text, ctx, top_k=6, min_sim=0.35):
    """Casos históricos parecidos vía RAG. Devuelve lista con code + resumen."""
    from utils.embeddings import semantic_search
    query = ' '.join(filter(None, [
        ctx.get('path'), ctx.get('failure_mode'), ctx.get('failure_category'),
        ctx.get('description'),
    ]))
    if not query.strip():
        return []
    hits = semantic_search(session, query, top_k=top_k,
                           entity_types=['work_order', 'notice'])
    cases = []
    for h in hits:
        if h.get('similarity', 0) < min_sim:
            continue
        # No incluir el propio aviso
        if h['entity_type'] == 'notice' and h.get('entity_id') == ctx.get('id'):
            continue
        code = None
        try:
            if h['entity_type'] == 'work_order':
                r = session.execute(text("SELECT code FROM work_orders WHERE id = :i"),
                                    {"i": h['entity_id']}).fetchone()
            else:
                r = session.execute(text("SELECT code FROM maintenance_notices WHERE id = :i"),
                                    {"i": h['entity_id']}).fetchone()
            code = r[0] if r else None
        except Exception:
            pass
        cases.append({
            "type": h['entity_type'], "code": code or f"#{h['entity_id']}",
            "similarity": round(h.get('similarity', 0), 2),
            "excerpt": (h.get('text_chunk') or '')[:400],
        })
    return cases


def _collect_specs(session, text, ctx, limit=18):
    """Especificaciones técnicas del equipo y componente del aviso.

    Lee equipment_specs y component_specs (clave/valor que el usuario registra
    en los activos: modelo de faja, potencia, RPM, medidas...). Ayudan a la IA
    a dar un análisis más preciso. Devuelve lista de strings "Clave: valor".
    """
    specs = []
    try:
        if ctx.get('component_id'):
            rows = session.execute(text(
                "SELECT key_name, value_text, unit FROM component_specs "
                "WHERE component_id = :c ORDER BY order_index LIMIT :lim"
            ), {"c": ctx['component_id'], "lim": limit}).fetchall()
            for r in rows:
                unit = f" {r[2]}" if r[2] else ""
                specs.append(f"[componente] {r[0]}: {r[1]}{unit}")
        if ctx.get('equipment_id') and len(specs) < limit:
            rows = session.execute(text(
                "SELECT key_name, value_text, unit FROM equipment_specs "
                "WHERE equipment_id = :e ORDER BY order_index LIMIT :lim"
            ), {"e": ctx['equipment_id'], "lim": limit - len(specs)}).fetchall()
            for r in rows:
                unit = f" {r[2]}" if r[2] else ""
                specs.append(f"[equipo] {r[0]}: {r[1]}{unit}")
    except Exception as e:
        logger.debug(f"_collect_specs lookup: {e}")
    return specs


def _recommended_action(session, text, ctx):
    """recommended_action del failure_catalog para el modo de falla del aviso."""
    fm = ctx.get('failure_mode')
    if not fm:
        return None
    try:
        r = session.execute(text(
            "SELECT recommended_action FROM failure_catalog "
            "WHERE failure_mode = :fm AND is_active = TRUE AND recommended_action IS NOT NULL "
            "LIMIT 1"
        ), {"fm": fm}).fetchone()
        return r[0] if r else None
    except Exception:
        return None


# ── Motor IA ─────────────────────────────────────────────────────────────────

_RCA_PROMPT = """Eres un ingeniero de mantenimiento senior de una planta de harina de pescado
(digestores, secadores, molinos, transportadores helicoidales). Recibes un AVISO de falla
junto con CASOS HISTÓRICOS parecidos y una lista de REPUESTOS DISPONIBLES (con su índice).

Devuelve un pre-diagnóstico en JSON ESTRICTO (sin texto fuera del JSON):
{{
  "causa_raiz": "hipótesis breve y concreta de la causa raíz probable (1-2 frases)",
  "acciones": ["paso de intervención concreto", "otro paso", ...],
  "repuestos_idx": [índices enteros de la lista de REPUESTOS DISPONIBLES que aplican],
  "herramientas_idx": [índices enteros de la lista de HERRAMIENTAS DISPONIBLES que se necesitan],
  "herramientas_extra": ["herramienta necesaria que NO esté en la lista", ...],
  "resumen": "una sola frase para el técnico",
  "confianza": "alta|media|baja"
}}

REGLAS:
- Usa los CASOS HISTÓRICOS como evidencia; si sugieren una causa o solución, priorízala.
- repuestos_idx y herramientas_idx: SOLO índices que existan en las listas dadas. Si ninguno
  aplica, []. NUNCA inventes códigos ni cantidades: eso viene de la BD.
- herramientas_extra: solo herramientas realmente necesarias que NO aparezcan en la lista de
  HERRAMIENTAS DISPONIBLES (texto simple, sin código). Si no hace falta ninguna, [].
- acciones: lista corta, cada elemento un paso concreto.
- confianza: 'alta' solo si hay casos históricos claros o la causa es evidente; 'baja' si hay poca información.
- Responde SOLO el JSON."""


def _call_llm(ctx, cases, spares, tools, rec_action, specs=None):
    """Llama a DeepSeek con el contexto. Devuelve dict o None."""
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        return None

    lines = [f"AVISO {ctx.get('code')}:"]
    if ctx.get('path'):
        lines.append(f"Ubicación: {ctx['path']}")
    if ctx.get('failure_mode'):
        lines.append(f"Modo de falla: {ctx['failure_mode']} ({ctx.get('failure_category') or '-'})")
    if ctx.get('criticality'):
        lines.append(f"Criticidad: {ctx['criticality']}")
    if ctx.get('description'):
        lines.append(f"Descripción: {ctx['description']}")
    if rec_action:
        lines.append(f"\nAcción recomendada del catálogo de fallas: {rec_action}")

    if specs:
        lines.append("\nESPECIFICACIONES TÉCNICAS registradas del equipo/componente:")
        for s in specs:
            lines.append(f"- {s}")

    if cases:
        lines.append("\nCASOS HISTÓRICOS PARECIDOS:")
        for c in cases:
            lines.append(f"- {c['code']} (sim {c['similarity']}): {c['excerpt']}")
    else:
        lines.append("\n(Sin casos históricos parecidos indexados.)")

    if spares:
        lines.append("\nREPUESTOS DISPONIBLES (índice: nombre [código] — origen):")
        for i, s in enumerate(spares):
            code = f" [{s['code']}]" if s.get('code') else ""
            lines.append(f"{i}: {s['name']}{code} — {s.get('source')}")
    else:
        lines.append("\n(Sin repuestos en catálogo ni historial para este equipo.)")

    if tools:
        lines.append("\nHERRAMIENTAS DISPONIBLES (del historial de OTs de este equipo; índice: nombre [código]):")
        for i, t in enumerate(tools):
            code = f" [{t['code']}]" if t.get('code') else ""
            lines.append(f"{i}: {t['name']}{code}")
    else:
        lines.append("\n(Sin herramientas registradas en el historial de este equipo.)")

    try:
        r = requests.post(DEEPSEEK_URL, headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }, json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': _RCA_PROMPT},
                {'role': 'user', 'content': '\n'.join(lines)},
            ],
            'max_tokens': 900, 'temperature': 0.2,
            'response_format': {'type': 'json_object'},
        }, timeout=90)
        if r.status_code != 200:
            logger.error(f"RCA DeepSeek HTTP {r.status_code}: {r.text[:200]}")
            return None
        content = r.json()['choices'][0]['message']['content']
        from bot.llm import _extract_json
        return _extract_json(content)
    except Exception as e:
        logger.error(f"RCA _call_llm error: {e}")
        return None


def _pick_by_idx(items, idxs, fields):
    """Mapea los índices elegidos por la IA a los datos duros de la BD."""
    out = []
    if not isinstance(idxs, list):
        return out
    for i in idxs:
        try:
            it = items[int(i)]
            out.append({k: it.get(k) for k in fields})
        except (ValueError, IndexError, TypeError):
            continue
    return out


def _build_payload(ctx, cases, spares, tools, rec_action, ai):
    """Combina datos duros (repuestos/herramientas con código+cantidad de BD) con la IA."""
    ai = ai or {}

    def _as_list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    # Repuestos: índices elegidos por la IA -> datos duros (nombre/código/cantidad).
    chosen_spares = _pick_by_idx(spares, ai.get('repuestos_idx'), ('name', 'code', 'qty', 'source'))
    if not chosen_spares and spares:
        # Fallback: los del catálogo del componente.
        chosen_spares = [{k: s.get(k) for k in ('name', 'code', 'qty', 'source')}
                         for s in spares if s.get('source') == 'catálogo'][:5]

    # Herramientas del historial (código+cantidad) + extras sugeridas por la IA (texto).
    chosen_tools = _pick_by_idx(tools, ai.get('herramientas_idx'), ('name', 'code', 'qty'))
    if not chosen_tools and tools:
        # Fallback: si la IA no eligió, ofrecer las del historial (limit).
        chosen_tools = [{k: t.get(k) for k in ('name', 'code', 'qty')} for t in tools[:6]]
    # 'herramientas_extra' (o 'herramientas' por compat) = sugeridas sin código.
    extra = _as_list(ai.get('herramientas_extra') or ai.get('herramientas'))
    have = {(t.get('name') or '').lower() for t in chosen_tools}
    for name in extra:
        if name.lower() not in have:
            chosen_tools.append({"name": name, "code": "", "qty": None})

    return {
        "notice_code": ctx.get('code'),
        "equipment": ctx.get('path'),
        "causa_raiz": (ai.get('causa_raiz') or '').strip() or None,
        "acciones": _as_list(ai.get('acciones')),
        "herramientas": chosen_tools,
        "repuestos": chosen_spares,
        "casos_similares": [{"code": c['code'], "type": c['type']} for c in cases],
        "resumen": (ai.get('resumen') or '').strip() or None,
        "confianza": (ai.get('confianza') or 'media').strip().lower(),
        "recommended_action": rec_action,
        "generated_at": None,  # se estampa al guardar
    }


def format_whatsapp_message(payload):
    """Mensaje ordenado para el grupo de mantenimiento (listas, sin texto corrido)."""
    conf = {'alta': '🟢 alta', 'media': '🟡 media', 'baja': '🟠 baja'}.get(
        payload.get('confianza'), '🟡 media')
    lines = [f"🔧 *PRE-DIAGNÓSTICO IA* — {payload.get('notice_code') or ''}"]
    if payload.get('equipment'):
        lines.append(f"📍 {payload['equipment']}")
    lines.append("")

    if payload.get('causa_raiz'):
        lines.append("⚠️ *Causa raíz probable:*")
        lines.append(payload['causa_raiz'])
        lines.append("")

    if payload.get('acciones'):
        lines.append("🛠️ *Acciones recomendadas:*")
        for a in payload['acciones']:
            lines.append(f"• {a}")
        lines.append("")

    if payload.get('repuestos'):
        lines.append("📦 *Repuestos probables:*")
        for r in payload['repuestos']:
            code = f"  (cód. {r['code']})" if r.get('code') else ""
            qty = f" — cant. {r['qty']}" if r.get('qty') else ""
            lines.append(f"• {r['name']}{code}{qty}")
        lines.append("")

    if payload.get('herramientas'):
        lines.append("🔩 *Herramientas:*")
        for t in payload['herramientas']:
            if isinstance(t, dict):
                code = f"  (cód. {t['code']})" if t.get('code') else ""
                qty = f" — cant. {t['qty']}" if t.get('qty') else ""
                lines.append(f"• {t.get('name')}{code}{qty}")
            else:  # compat: payloads antiguos guardaban strings
                lines.append(f"• {t}")
        lines.append("")

    if payload.get('casos_similares'):
        lines.append("📚 *Casos similares:*")
        for c in payload['casos_similares'][:5]:
            lines.append(f"• {c['code']}")
        lines.append("")

    lines.append(f"_Confianza del análisis: {conf}. Generado por IA — validar en campo._")
    return '\n'.join(lines).strip()


def _save_rca(app, ctx, payload, model='deepseek-chat', status='ok', error=None):
    """Guarda/actualiza el RCA en notice_rca (upsert por notice_id)."""
    from sqlalchemy import text
    from database import db as _db
    from utils.tz import now_lima_naive
    payload = dict(payload or {})
    payload['generated_at'] = now_lima_naive().strftime('%Y-%m-%d %H:%M')
    summary = payload.get('resumen') or payload.get('causa_raiz') or ''
    with app.app_context():
        existing = _db.session.execute(text(
            "SELECT id FROM notice_rca WHERE notice_id = :n"), {"n": ctx['id']}).fetchone()
        params = {
            "n": ctx['id'], "code": ctx.get('code'),
            "payload": json.dumps(payload, ensure_ascii=False),
            "summary": summary[:500], "model": model,
            "conf": payload.get('confianza'), "status": status, "err": error,
        }
        if existing:
            _db.session.execute(text(
                "UPDATE notice_rca SET notice_code=:code, payload=:payload, summary=:summary, "
                "model=:model, confidence=:conf, status=:status, error=:err, "
                "updated_at=CURRENT_TIMESTAMP WHERE notice_id=:n"), params)
        else:
            _db.session.execute(text(
                "INSERT INTO notice_rca (notice_id, notice_code, payload, summary, model, "
                "confidence, status, error) VALUES (:n, :code, :payload, :summary, :model, "
                ":conf, :status, :err)"), params)
        _db.session.commit()
    return payload


def generate_rca(app, notice_id, push=True):
    """Genera (o regenera) el pre-diagnóstico de un aviso. Devuelve el payload.

    push=True encola el mensaje al grupo de WhatsApp de mantenimiento
    (WHATSAPP_MAINT_GROUP_JID) si está configurado.
    """
    if not ensure_rca_tables(app):
        return None
    from sqlalchemy import text
    from database import db as _db
    try:
        with app.app_context():
            ctx = _load_notice_context(_db.session, text, notice_id)
            if not ctx:
                logger.warning(f"generate_rca: aviso {notice_id} no encontrado")
                return None
            cases = _collect_similar_cases(_db.session, text, ctx)
            spares = _collect_hard_spares(_db.session, text, ctx)
            tools = _collect_hard_tools(_db.session, text, ctx)
            specs = _collect_specs(_db.session, text, ctx)
            rec_action = _recommended_action(_db.session, text, ctx)
    except Exception as e:
        logger.error(f"generate_rca contexto error: {e}")
        return None

    ai = _call_llm(ctx, cases, spares, tools, rec_action, specs=specs)
    status = 'ok' if ai else 'no_ai'
    payload = _build_payload(ctx, cases, spares, tools, rec_action, ai)

    try:
        saved = _save_rca(app, ctx, payload, status=status)
    except Exception as e:
        logger.error(f"generate_rca guardado error: {e}")
        saved = payload

    # Push a los grupos de mantenimiento (canal cerrado, nunca a producción)
    if push:
        groups = get_maint_group_jids(app)
        if groups:
            msg = format_whatsapp_message(saved)
            for g in groups:
                enqueue_wa_message(app, g, msg, context=f"rca:{ctx.get('code')}")
        else:
            logger.info("Sin grupos de mantenimiento configurados — RCA guardado sin push a WhatsApp")
    return saved


def get_rca(app, notice_id):
    """Devuelve el payload guardado del RCA de un aviso, o None."""
    if not ensure_rca_tables(app):
        return None
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            row = _db.session.execute(text(
                "SELECT payload, model, confidence, status, updated_at "
                "FROM notice_rca WHERE notice_id = :n"), {"n": notice_id}).fetchone()
        if not row:
            return None
        payload = json.loads(row[0]) if row[0] else {}
        payload['_model'] = row[1]
        payload['_status'] = row[3]
        return payload
    except Exception as e:
        logger.warning(f"get_rca error: {e}")
        return None


def trigger_rca_async(app, notice_id):
    """Dispara la generación del RCA en un hilo, sin bloquear el flujo del aviso.

    No corre en tests (TESTING) ni sin DEEPSEEK_API_KEY: el diagnóstico es un
    extra que jamás debe romper la creación del aviso.
    """
    try:
        if app.config.get('TESTING'):
            return
    except Exception:
        pass
    if not os.getenv('DEEPSEEK_API_KEY'):
        return

    def _run():
        try:
            generate_rca(app, notice_id, push=True)
        except Exception as e:
            logger.error(f"trigger_rca_async error (aviso {notice_id}): {e}")

    threading.Thread(target=_run, daemon=True).start()
