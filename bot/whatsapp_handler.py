"""Handler de mensajes entrantes de WhatsApp (via gateway Baileys en Node).

El gateway (whatsapp-gateway/) reenvia cada mensaje privado como JSON a
/api/public/whatsapp/webhook y este modulo maneja la conversacion completa:

  1. Extraccion IA (DeepSeek) del reporte: equipo/componente/falla, acotada
     al arbol visible del usuario (areas_visibles de bot_whatsapp_users).
  2. Resolucion contra el arbol real (bot.resolvers.resolve_equipment).
  3. Anti-duplicados: avisos ABIERTOS del mismo equipo en los ultimos 30 dias
     -> ofrece agregar observacion en vez de crear otro aviso.
  4. Confirmacion del usuario (lista numerada 1/2/3 o texto libre).
  5. Creacion del aviso via bot.actions.notices.create_notice (Supabase).
  6. Evidencia foto/video -> photo_attachments (Supabase Storage).
  7. Reenvio del aviso ordenado al grupo del reportero (grupo_destino).

Contrato de respuesta al gateway:
    {
      "replies":  ["texto para el usuario", ...],
      "forwards": [{"to": "<jid grupo>", "text": "...",
                    "attach_incoming_media": bool,      # media del mensaje actual
                    "media_base64": "...", "media_type": "image|video",
                    "mimetype": "..."}, ...]
    }

Modo DRY_RUN (WHATSAPP_DRY_RUN=1, default): ejecuta todo el flujo pero NO
escribe avisos en la BD, NO sube fotos y NO reenvia a grupos — muestra lo que
HABRIA hecho. Asi se prueba end-to-end sin ensuciar el CMMS de produccion.
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


def _dry_run():
    # Default '1': seguro por defecto — solo crea avisos reales si se
    # configura WHATSAPP_DRY_RUN=0 explicitamente en el entorno.
    return (os.getenv('WHATSAPP_DRY_RUN', '1').strip() or '1') != '0'


# ── Tabla de usuarios autorizados ─────────────────────────────────────────
# Cada numero (celular de area o personal) define rol, areas visibles y el
# grupo de WhatsApp al que se reenvia su aviso ordenado.

_wa_table_ready = False
_wa_table_lock = threading.Lock()


def _ensure_wa_users_table(app):
    """Crea bot_whatsapp_users si no existe (idempotente, dialect-aware)."""
    global _wa_table_ready
    if _wa_table_ready:
        return True
    with _wa_table_lock:
        if _wa_table_ready:
            return True
        try:
            from sqlalchemy import text
            from database import db as _db
            with app.app_context():
                if _db.engine.dialect.name == 'postgresql':
                    id_col = "id SERIAL PRIMARY KEY"
                else:  # sqlite (tests / local)
                    id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"
                _db.session.execute(text(
                    "CREATE TABLE IF NOT EXISTS bot_whatsapp_users ("
                    f"{id_col}, "
                    "phone_number VARCHAR(30) UNIQUE NOT NULL, "
                    "nombre VARCHAR(120), "
                    "rol VARCHAR(40) DEFAULT 'supervisor_area', "
                    "areas_visibles TEXT, "
                    "grupo_destino VARCHAR(80), "
                    "grupo_nombre VARCHAR(80), "
                    "puede_ver_todo BOOLEAN DEFAULT FALSE, "
                    "activo BOOLEAN DEFAULT TRUE, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                ))
                _db.session.commit()
            _wa_table_ready = True
            return True
        except Exception as e:
            logger.warning(f"No se pudo crear bot_whatsapp_users: {e}")
            return False


# Cache phone -> fila de usuario (dict) con TTL, igual que el bot de Telegram
_wa_users_cache = {"ts": 0.0, "map": {}}
_WA_CACHE_TTL = 60


def _digits(s):
    return ''.join(ch for ch in (s or '') if ch.isdigit())


def get_wa_user(app, phone):
    """Devuelve el usuario registrado para el numero, o None.

    `phone` llega como digitos ('51987654321'). Refresca cache cada 60 s para
    reflejar altas/bajas sin reiniciar.
    """
    now = time.time()
    if now - _wa_users_cache["ts"] > _WA_CACHE_TTL:
        if _ensure_wa_users_table(app):
            try:
                from sqlalchemy import text
                from database import db as _db
                with app.app_context():
                    rows = _db.session.execute(text(
                        "SELECT phone_number, nombre, rol, areas_visibles, "
                        "grupo_destino, grupo_nombre, puede_ver_todo "
                        "FROM bot_whatsapp_users WHERE activo = TRUE"
                    )).fetchall()
                    _wa_users_cache["map"] = {
                        _digits(r[0]): {
                            "phone": r[0], "nombre": r[1], "rol": r[2],
                            "areas_visibles": r[3], "grupo_destino": r[4],
                            "grupo_nombre": r[5],
                            "puede_ver_todo": bool(r[6]),
                        } for r in rows
                    }
                    _wa_users_cache["ts"] = now
            except Exception as e:
                logger.warning(f"get_wa_user cache refresh fallo: {e}")
    return _wa_users_cache["map"].get(_digits(phone))


def invalidate_wa_users_cache():
    _wa_users_cache["ts"] = 0.0


# ── Sesiones de conversacion (estado multi-paso por numero) ───────────────
# Estados: 'confirm' (esperando si/corregir/cancelar), 'dup' (duplicado
# detectado, 1/2/3), 'media' (aviso creado, esperando foto/video o 'listo').
# TTL 15 min: si el usuario no responde, la sesion se descarta.

_sessions = {}
_SESSION_TTL = 900


def _get_session(phone):
    s = _sessions.get(phone)
    if s and time.time() - s.get('ts', 0) > _SESSION_TTL:
        _sessions.pop(phone, None)
        return None
    return s


def _set_session(phone, data):
    data['ts'] = time.time()
    _sessions[phone] = data


def _clear_session(phone):
    _sessions.pop(phone, None)


# ── Arbol visible del usuario ─────────────────────────────────────────────

def _visible_area_ids(user):
    raw = (user.get('areas_visibles') or '').strip()
    if user.get('puede_ver_todo') or not raw:
        return None  # None = todas las areas
    ids = []
    for chunk in raw.replace(';', ',').split(','):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids or None


def _build_scope_tree(app, user):
    """Lista compacta de equipos visibles: 'TAG | equipo | linea | area'."""
    area_ids = _visible_area_ids(user)
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            sql = ("SELECT e.tag, e.name, l.name, a.name FROM equipments e "
                   "LEFT JOIN lines l ON e.line_id = l.id "
                   "LEFT JOIN areas a ON l.area_id = a.id ")
            params = {}
            if area_ids:
                sql += "WHERE l.area_id = ANY(:ids) " if _db.engine.dialect.name == 'postgresql' \
                    else f"WHERE l.area_id IN ({','.join(str(i) for i in area_ids)}) "
                if _db.engine.dialect.name == 'postgresql':
                    params["ids"] = area_ids
            sql += "ORDER BY a.name, l.name, e.name"
            rows = _db.session.execute(text(sql), params).fetchall()
        return '\n'.join(f"{r[0]} | {r[1]} | {r[2] or '-'} | {r[3] or '-'}" for r in rows)
    except Exception as e:
        logger.warning(f"_build_scope_tree error: {e}")
        return ''


# ── Extraccion IA (DeepSeek) ──────────────────────────────────────────────

_EXTRACTION_PROMPT = """Eres el asistente de reportes de falla del CMMS de una planta industrial.
Un trabajador te escribe por WhatsApp reportando una falla u observacion de un equipo.
Tu tarea: extraer los datos del reporte en JSON ESTRICTO (sin texto fuera del JSON).

EQUIPOS VISIBLES PARA ESTE USUARIO (tag | equipo | linea | area):
{tree}

FORMATO DE SALIDA (JSON unico):
{{
  "es_reporte": true/false,
  "reply": "si es_reporte=false: respuesta breve y cordial explicando que solo registras reportes de falla",
  "description": "redaccion profesional orientada al modo de falla (NO copies textual)",
  "equipment_tag": "tag EXACTO de la lista o null si no matchea ninguno",
  "component_name": "componente especifico mencionado (motor electrico, reductor, chumacera motriz, faja, etc) o null",
  "system_name": "solo si menciona un subconjunto (exhaustor, ventilador, bomba) o null",
  "failure_mode": "Rotura|Desgaste|Fuga|Desalineacion|Sobrecalentamiento|Ruido anormal|Vibracion excesiva|Aflojamiento|Corrosion|Atascamiento|Descarrilamiento|Cortocircuito|Sobrecarga|Fatiga",
  "failure_category": "Mecanica|Electrica|Hidraulica|Neumatica|Instrumentacion|Lubricacion|Estructural",
  "blockage_object": "Metal|Piedra|Cadena|Madera|Alambre|Perno|Acero Inoxidable|Bronce|Otro|null",
  "criticality": "Alta|Media|Baja",
  "maintenance_type": "Correctivo|Preventivo|Mejora",
  "scope": "PLAN si el equipo esta en la lista; FUERA_PLAN si menciona un equipo real que NO esta; GENERAL si es trabajo generico sin equipo",
  "free_location": "ubicacion en texto libre si scope != PLAN, sino null",
  "event_date": "YYYY-MM-DD solo si menciona cuando ocurrio (ayer, el lunes, etc), sino null"
}}

REGLAS:
- es_reporte=true SOLO si describe una falla, dano, ruido, fuga, parada u observacion de mantenimiento.
  Preguntas, saludos o consultas -> es_reporte=false con reply cordial.
- equipment_tag: usa LITERALMENTE un tag de la lista. Si el usuario dice "molino 2" busca el tag cuyo
  nombre coincida. NUNCA inventes tags. Si no hay match claro -> null y scope FUERA_PLAN o GENERAL.
- Si reporta bloqueo/atasco ("se trabo", "se bloqueo", "entro una piedra"), failure_mode=Atascamiento
  y blockage_object con el objeto (si no lo dice, null).
- criticality: Alta si hay parada de produccion, riesgo de incendio/seguridad o dano mayor;
  Media para degradacion funcional; Baja para detalles menores.
- HOY es {today}. Calcula fechas relativas ("ayer" -> {yesterday}).
- Responde SOLO el JSON."""


def _call_deepseek_extraction(app, user, message):
    """Llama a DeepSeek con el prompt de extraccion. Devuelve dict o None."""
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        logger.error("DEEPSEEK_API_KEY no configurada")
        return None
    tree = _build_scope_tree(app, user)
    prompt = _EXTRACTION_PROMPT.format(
        tree=tree or '(sin equipos cargados)',
        today=date.today().isoformat(),
        yesterday=(date.today() - timedelta(days=1)).isoformat(),
    )
    try:
        r = requests.post(DEEPSEEK_URL, headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }, json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': message},
            ],
            'max_tokens': 900, 'temperature': 0.2,
            'response_format': {'type': 'json_object'},
        }, timeout=60)
        if r.status_code != 200:
            logger.error(f"DeepSeek extraccion HTTP {r.status_code}: {r.text[:200]}")
            return None
        content = r.json()['choices'][0]['message']['content']
        from bot.llm import _extract_json
        return _extract_json(content)
    except Exception as e:
        logger.error(f"DeepSeek extraccion error: {e}")
        return None


# ── Resolucion contra el arbol real ───────────────────────────────────────

def _resolve_display(app, extraction):
    """Resuelve la extraccion contra el arbol y devuelve nombres legibles.

    Retorna dict {equipment_id, component_id, ..., path: 'Area > Linea > Equipo > Componente'}
    """
    from bot.resolvers import resolve_equipment
    out = {"equipment_id": None, "component_id": None, "path": None}
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = resolve_equipment(_db, text, dict(extraction))
            out.update({"equipment_id": eq_id, "line_id": ln_id, "area_id": ar_id,
                        "system_id": sys_id, "component_id": comp_id})
            if eq_id:
                row = _db.session.execute(text(
                    "SELECT e.tag, e.name, l.name, a.name FROM equipments e "
                    "LEFT JOIN lines l ON e.line_id = l.id "
                    "LEFT JOIN areas a ON l.area_id = a.id WHERE e.id = :id"
                ), {"id": eq_id}).fetchone()
                comp_name = None
                if comp_id:
                    c = _db.session.execute(text(
                        "SELECT name FROM components WHERE id = :id"), {"id": comp_id}).fetchone()
                    comp_name = c[0] if c else None
                if row:
                    parts = [row[3] or '?', row[2] or '?', f"[{row[0]}] {row[1]}"]
                    if comp_name:
                        parts.append(comp_name)
                    out["path"] = ' › '.join(parts)
    except Exception as e:
        logger.warning(f"_resolve_display error: {e}")
    return out


# ── Anti-duplicados ───────────────────────────────────────────────────────

def _find_open_duplicates(app, equipment_id, days=30, limit=3):
    """Avisos ABIERTOS del mismo equipo en los ultimos `days` dias."""
    if not equipment_id:
        return []
    try:
        from sqlalchemy import text
        from database import db as _db
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        with app.app_context():
            rows = _db.session.execute(text(
                "SELECT code, description, reporter_name, request_date "
                "FROM maintenance_notices "
                "WHERE equipment_id = :eq AND status = 'Pendiente' "
                "AND request_date >= :cutoff ORDER BY id DESC LIMIT :lim"
            ), {"eq": equipment_id, "cutoff": cutoff, "lim": limit}).fetchall()
        return [{"code": r[0], "description": (r[1] or '')[:160],
                 "reporter": r[2] or '-', "date": str(r[3] or '')} for r in rows]
    except Exception as e:
        logger.warning(f"_find_open_duplicates error: {e}")
        return []


def _append_observation(app, notice_code, user, obs_text):
    """Agrega la observacion de un segundo reportero a un aviso existente."""
    try:
        from sqlalchemy import text
        from database import db as _db
        stamp = f"[+ Obs de {user.get('nombre')} via WhatsApp {date.today().isoformat()}]: {obs_text[:400]}"
        with app.app_context():
            _db.session.execute(text(
                "UPDATE maintenance_notices SET description = description || :obs "
                "WHERE code = :code"
            ), {"obs": f"\n{stamp}", "code": notice_code})
            _db.session.commit()
        return True
    except Exception as e:
        logger.error(f"_append_observation error: {e}")
        return False


# ── Creacion del aviso + evidencia + mensaje al grupo ─────────────────────

def _create_notice_from_extraction(app, user, extraction):
    """Crea el aviso real via bot.actions.notices.create_notice."""
    from bot.actions.notices import create_notice
    data = {
        "description": extraction.get('description') or 'Reporte desde WhatsApp',
        "criticality": extraction.get('criticality') or 'Media',
        "maintenance_type": extraction.get('maintenance_type') or 'Correctivo',
        "failure_mode": extraction.get('failure_mode'),
        "failure_category": extraction.get('failure_category'),
        "blockage_object": extraction.get('blockage_object'),
        "scope": extraction.get('scope'),
        "free_location": extraction.get('free_location'),
        "reporter_name": user.get('nombre') or 'WhatsApp',
        "reporter_type": "whatsapp",
    }
    if extraction.get('event_date'):
        data['event_date'] = extraction['event_date']
    for k in ('equipment_tag', 'component_name', 'system_name'):
        if extraction.get(k):
            data[k] = extraction[k]
    return create_notice(app, data)


def _attach_media_to_notice(app, notice_id, media):
    """Sube foto/video a Supabase Storage y la vincula al aviso. Devuelve url o None."""
    try:
        import base64
        raw = base64.b64decode(media.get('base64') or '')
        if not raw:
            return None
        from utils.photo_helpers import compress_photo, upload_to_supabase_storage
        mtype = media.get('type')
        if mtype == 'image':
            payload, _ = compress_photo(raw)
            ext = 'jpg'
        else:
            payload = raw  # video: sin compresion (el gateway limita a 16 MB)
            ext = (media.get('mimetype') or 'video/mp4').split('/')[-1].split(';')[0]
        fname = f"whatsapp_{notice_id}_{int(time.time())}.{ext}"
        url = upload_to_supabase_storage(payload, fname)
        if not url:
            return None
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            _db.session.execute(text(
                "INSERT INTO photo_attachments (entity_type, entity_id, url, caption, "
                "original_size_kb, compressed_size_kb, created_at) "
                "VALUES ('notice', :eid, :url, 'Evidencia desde WhatsApp', :o, :c, CURRENT_TIMESTAMP)"
            ), {"eid": notice_id, "url": url, "o": len(raw) // 1024, "c": len(payload) // 1024})
            _db.session.commit()
        return url
    except Exception as e:
        logger.error(f"_attach_media_to_notice error: {e}")
        return None


def _group_message(code, user, extraction, resolved, is_update=False):
    header = "🔁 *ACTUALIZACION DE AVISO*" if is_update else "🔧 *NUEVO AVISO DE MANTENIMIENTO*"
    lines = [f"{header} — {code}", ""]
    lines.append(f"👤 Reporto: {user.get('nombre')} ({user.get('rol') or '-'})")
    if resolved.get('path'):
        lines.append(f"📍 {resolved['path']}")
    elif extraction.get('free_location'):
        lines.append(f"📍 {extraction['free_location']}")
    fm = extraction.get('failure_mode')
    crit = (extraction.get('criticality') or 'Media').upper()
    icon = {'ALTA': '🔴', 'MEDIA': '🟡', 'BAJA': '🟢'}.get(crit, '🟡')
    if fm:
        lines.append(f"❌ Falla: {fm} · {icon} {crit}")
    else:
        lines.append(f"{icon} Criticidad: {crit}")
    desc = extraction.get('description') or ''
    if desc:
        lines.append(f"📝 {desc[:300]}")
    return '\n'.join(lines)


def _confirm_message(extraction, resolved, dry):
    lines = ["📋 *Entendi tu reporte asi:*", ""]
    if resolved.get('path'):
        lines.append(f"📍 {resolved['path']}")
    elif extraction.get('free_location'):
        lines.append(f"📍 {extraction['free_location']} (fuera del arbol)")
    else:
        lines.append("📍 (sin equipo identificado)")
    if extraction.get('failure_mode'):
        lines.append(f"❌ Falla: {extraction['failure_mode']} ({extraction.get('failure_category') or '-'})")
    if extraction.get('blockage_object'):
        lines.append(f"🧱 Objeto: {extraction['blockage_object']}")
    lines.append(f"⚠️ Criticidad: {extraction.get('criticality') or 'Media'}")
    lines.append(f"📝 {extraction.get('description') or ''}")
    lines.append("")
    lines.append("¿Es correcto?")
    lines.append("1️⃣ Si, registrar")
    lines.append("2️⃣ Corregir (escribe la correccion)")
    lines.append("3️⃣ Cancelar")
    if dry:
        lines.append("\n_[modo prueba DRY-RUN: no se escribira en la BD]_")
    return '\n'.join(lines)


# ── Normalizacion de respuestas del usuario ───────────────────────────────

_YES = {'1', 'si', 'sí', 'ok', 'dale', 'correcto', 'confirmo', 'yes', 'sip', 'ya'}
_NO = {'3', 'no', 'cancelar', 'cancela', 'anular', 'nada'}
_SKIP_MEDIA = {'listo', 'no', 'omitir', 'sin foto', 'ninguna', 'skip', 'ya'}


def _norm_choice(text):
    return (text or '').strip().lower().rstrip('.!')


# ── Entrada principal ─────────────────────────────────────────────────────

def handle_incoming(app, payload):
    """Procesa un mensaje del gateway y devuelve replies/forwards."""
    phone = _digits(payload.get('phone') or '')
    text = (payload.get('text') or '').strip()
    media = payload.get('media')  # {type, mimetype, base64} | None
    push_name = (payload.get('push_name') or '').strip()

    user = get_wa_user(app, phone)
    if not user:
        logger.warning(f"WhatsApp no autorizado: {phone} ({push_name})")
        return {"replies": [
            "🔒 Este numero no esta registrado en el CMMS.\n"
            f"Pide al administrador que registre el numero {phone}."
        ]}

    nombre = user.get('nombre') or push_name or 'colega'
    lower = _norm_choice(text)
    session = _get_session(phone)

    # Cancelar funciona en cualquier estado
    if lower in ('cancelar', 'cancela') and session:
        _clear_session(phone)
        return {"replies": ["👍 Listo, cancelado. Cuando quieras reportar algo, solo escribeme la falla."]}

    # ── Estado: esperando foto/video del aviso ya creado ──────────────
    if session and session.get('state') == 'media':
        return _handle_media_state(app, phone, user, session, text, lower, media)

    # ── Estado: duplicado detectado, esperando decision 1/2/3 ─────────
    if session and session.get('state') == 'dup':
        return _handle_dup_state(app, phone, user, session, text, lower)

    # ── Estado: esperando confirmacion 1/2/3 ──────────────────────────
    if session and session.get('state') == 'confirm':
        return _handle_confirm_state(app, phone, user, session, text, lower, media)

    # ── Sin sesion: mensaje nuevo ──────────────────────────────────────
    if not text and media:
        if media.get('type') == 'audio':
            return {"replies": ["🎙️ Todavia no proceso audios. Escribeme la falla en texto, porfa."]}
        return {"replies": [
            "📷 Recibi el archivo, pero primero cuentame: ¿que falla quieres reportar y de que equipo?"
        ]}

    if not text:
        return {"replies": []}

    if lower in ('hola', 'menu', 'ayuda', 'help', '/start', 'buenas', 'buenos dias', 'buenas tardes', 'buenas noches'):
        return {"replies": [
            f"👋 Hola {nombre}. Soy el bot de mantenimiento.\n\n"
            "Escribeme la falla que observas y yo la registro en el CMMS.\n"
            "Ejemplo: _\"el motor del molino 2 esta calentando y hace ruido\"_\n\n"
            "Luego te pedire confirmacion y una foto o video (opcional)."
        ]}

    # Reporte nuevo → extraccion IA
    extraction = _call_deepseek_extraction(app, user, text)
    if not extraction:
        return {"replies": ["⚠️ No pude analizar tu mensaje (error de IA). Intenta de nuevo en un momento."]}

    if not extraction.get('es_reporte'):
        reply = extraction.get('reply') or (
            "Solo registro reportes de falla. Escribeme que equipo esta fallando y que observas.")
        return {"replies": [reply]}

    resolved = _resolve_display(app, extraction)

    # Anti-duplicados (solo con equipo identificado)
    dups = _find_open_duplicates(app, resolved.get('equipment_id'))
    if dups:
        _set_session(phone, {"state": "dup", "extraction": extraction,
                             "resolved": resolved, "dups": dups,
                             "media_pending": media, "original_text": text})
        lines = ["⚠️ *Ojo:* ya hay aviso(s) abierto(s) de este equipo:", ""]
        for d in dups:
            lines.append(f"• *{d['code']}* — {d['description']}")
            lines.append(f"  _reportado por {d['reporter']} el {d['date']}_")
        lines.append("")
        lines.append("¿Que hago?")
        lines.append(f"1️⃣ Agregar tu observacion al {dups[0]['code']} (no duplicar)")
        lines.append("2️⃣ Crear un aviso NUEVO (es otra falla distinta)")
        lines.append("3️⃣ Cancelar")
        return {"replies": ['\n'.join(lines)]}

    # Sin duplicados → pedir confirmacion
    _set_session(phone, {"state": "confirm", "extraction": extraction,
                         "resolved": resolved, "media_pending": media,
                         "original_text": text})
    return {"replies": [_confirm_message(extraction, resolved, _dry_run())]}


# ── Sub-handlers por estado ───────────────────────────────────────────────

def _handle_confirm_state(app, phone, user, session, text, lower, media):
    extraction = session['extraction']
    resolved = session['resolved']

    if lower in _NO:
        _clear_session(phone)
        return {"replies": ["👍 Cancelado. Aqui estoy si necesitas reportar otra cosa."]}

    if lower in _YES:
        return _do_create(app, phone, user, session)

    # "2", "corregir" o texto libre → re-extraccion con la correccion
    correction = text if lower not in ('2', 'corregir', 'correccion') else None
    if correction is None:
        return {"replies": ["✏️ Dime que corrijo (ej: _\"es el molino 1, no el 2\"_ o _\"la criticidad es alta\"_)."]}
    combined = (f"REPORTE ORIGINAL: {session.get('original_text', '')}\n"
                f"CORRECCION DEL USUARIO: {correction}")
    new_extraction = _call_deepseek_extraction(app, user, combined)
    if not new_extraction or not new_extraction.get('es_reporte'):
        return {"replies": ["⚠️ No entendi la correccion. Intenta de nuevo o escribe *cancelar*."]}
    new_resolved = _resolve_display(app, new_extraction)
    _set_session(phone, {**session, "extraction": new_extraction, "resolved": new_resolved,
                         "original_text": f"{session.get('original_text', '')} / {correction}"})
    return {"replies": [_confirm_message(new_extraction, new_resolved, _dry_run())]}


def _handle_dup_state(app, phone, user, session, text, lower):
    extraction = session['extraction']
    resolved = session['resolved']
    dups = session['dups']

    if lower in _NO:
        _clear_session(phone)
        return {"replies": ["👍 Cancelado, no se registro nada."]}

    if lower in ('2', 'nuevo', 'crear nuevo', 'otra', 'es otra'):
        _set_session(phone, {**session, "state": "confirm"})
        return {"replies": [_confirm_message(extraction, resolved, _dry_run())]}

    if lower in ('1', 'agregar', 'si', 'sí', 'es la misma', 'mismo', 'misma'):
        code = dups[0]['code']
        obs = session.get('original_text') or extraction.get('description') or ''
        if _dry_run():
            _clear_session(phone)
            return {"replies": [
                f"🧪 [DRY-RUN] Habria agregado tu observacion al *{code}* y avisado al grupo.\n"
                f"Observacion: _{obs[:200]}_"
            ]}
        ok = _append_observation(app, code, user, obs)
        if not ok:
            _clear_session(phone)
            return {"replies": [f"⚠️ No pude actualizar el {code}. Reportalo al administrador."]}
        # pedir evidencia opcional para el aviso existente
        notice_id = _notice_id_by_code(app, code)
        _set_session(phone, {"state": "media", "notice_code": code, "notice_id": notice_id,
                             "extraction": extraction, "resolved": resolved, "is_update": True})
        forwards = []
        if user.get('grupo_destino'):
            forwards.append({
                "to": user['grupo_destino'],
                "text": _group_message(code, user, extraction, resolved, is_update=True),
            })
        return {"replies": [
            f"✅ Tu observacion quedo agregada al *{code}*.\n"
            "📸 Si tienes foto o video de la falla, mandalo ahora (o escribe *listo*)."
        ], "forwards": forwards}

    return {"replies": ["Responde *1* (agregar al existente), *2* (crear nuevo) o *3* (cancelar)."]}


def _handle_media_state(app, phone, user, session, text, lower, media):
    code = session.get('notice_code')
    notice_id = session.get('notice_id')

    if media and media.get('type') in ('image', 'video'):
        url = None
        if not _dry_run() and notice_id:
            url = _attach_media_to_notice(app, notice_id, media)
        _clear_session(phone)
        forwards = []
        if not _dry_run() and user.get('grupo_destino'):
            forwards.append({
                "to": user['grupo_destino'],
                "text": f"📎 Evidencia del {code} — {user.get('nombre')}",
                "attach_incoming_media": True,
            })
        msg = f"✅ Evidencia recibida y adjuntada al *{code}*."
        if _dry_run():
            msg = f"🧪 [DRY-RUN] Habria adjuntado la evidencia al *{code}* y reenviado al grupo."
        elif not url:
            msg = f"⚠️ Recibi el archivo pero no pude subirlo al {code}. El aviso sigue registrado."
        return {"replies": [msg], "forwards": forwards}

    if lower in _SKIP_MEDIA:
        _clear_session(phone)
        return {"replies": [f"👍 Listo, el *{code}* quedo registrado sin evidencia."]}

    return {"replies": [
        f"📸 Estoy esperando la foto/video del *{code}*.\n"
        "Mandala ahora, o escribe *listo* para terminar sin evidencia."
    ]}


def _do_create(app, phone, user, session):
    extraction = session['extraction']
    resolved = session['resolved']
    media_pending = session.get('media_pending')

    if _dry_run():
        _clear_session(phone)
        preview = _group_message('AV-SIMULADO', user, extraction, resolved)
        return {"replies": [
            "🧪 *[DRY-RUN]* El aviso NO se creo (modo prueba). Esto es lo que habria pasado:\n\n"
            f"1. Aviso creado en el CMMS (estado Pendiente)\n"
            f"2. Mensaje al grupo *{user.get('grupo_nombre') or user.get('grupo_destino') or '(sin grupo)'}*:\n\n"
            f"{preview}"
        ]}

    code, notice_id, err = _create_notice_from_extraction(app, user, extraction)
    if err or not code:
        _clear_session(phone)
        logger.error(f"WhatsApp create_notice fallo: {err}")
        return {"replies": [f"⚠️ No pude crear el aviso: {err or 'error desconocido'}"]}

    forwards = []
    if user.get('grupo_destino'):
        fwd = {"to": user['grupo_destino'],
               "text": _group_message(code, user, extraction, resolved)}
        # si el reporte original traia foto, adjuntarla al grupo tambien
        if media_pending and media_pending.get('base64'):
            fwd["media_base64"] = media_pending['base64']
            fwd["media_type"] = media_pending.get('type')
            fwd["mimetype"] = media_pending.get('mimetype')
        forwards.append(fwd)

    # adjuntar media que vino con el primer mensaje
    if media_pending and media_pending.get('base64'):
        _attach_media_to_notice(app, notice_id, media_pending)
        _clear_session(phone)
        return {"replies": [
            f"✅ Aviso *{code}* creado en el CMMS con tu evidencia.\n"
            f"📢 Avise al grupo {user.get('grupo_nombre') or ''}."
        ], "forwards": forwards}

    _set_session(phone, {"state": "media", "notice_code": code, "notice_id": notice_id,
                         "extraction": extraction, "resolved": resolved})
    return {"replies": [
        f"✅ Aviso *{code}* creado en el CMMS (estado Pendiente).\n"
        f"📢 Avise al grupo {user.get('grupo_nombre') or ''}.\n\n"
        "📸 Si tienes foto o video de la falla, mandalo ahora (o escribe *listo*)."
    ], "forwards": forwards}


def _notice_id_by_code(app, code):
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            row = _db.session.execute(text(
                "SELECT id FROM maintenance_notices WHERE code = :c"), {"c": code}).fetchone()
        return row[0] if row else None
    except Exception:
        return None
