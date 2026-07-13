"""Handler de mensajes entrantes de WhatsApp (via gateway Baileys en Node).

El gateway (whatsapp-gateway/) reenvia cada mensaje privado como JSON a
/api/public/whatsapp/webhook y este modulo decide que responder. Reutiliza el
cerebro del bot de Telegram: _ask_deepseek (bot/llm.py), resolve_taxonomy
(bot/resolvers.py), create_notice (bot/actions/notices.py), semantic_search
(utils/embeddings.py).

Contrato de respuesta al gateway:
    {
      "replies":  ["texto para el usuario", ...],
      "forwards": [{"to": "<jid grupo>", "text": "...",
                    "attach_incoming_media": true|false}, ...]
    }

Modo DRY_RUN (WHATSAPP_DRY_RUN=1, default): ejecuta todo el flujo pero NO
escribe avisos en la BD ni reenvia a grupos — responde lo que HABRIA hecho.
Asi se prueba end-to-end sin ensuciar el CMMS de produccion.
"""
import os
import time
import logging
import threading

logger = logging.getLogger(__name__)


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
                        # normalizar a solo digitos por si guardaron con +51 o espacios
                        ''.join(ch for ch in (r[0] or '') if ch.isdigit()): {
                            "phone": r[0], "nombre": r[1], "rol": r[2],
                            "areas_visibles": r[3], "grupo_destino": r[4],
                            "grupo_nombre": r[5],
                            "puede_ver_todo": bool(r[6]),
                        } for r in rows
                    }
                    _wa_users_cache["ts"] = now
            except Exception as e:
                logger.warning(f"get_wa_user cache refresh fallo: {e}")
    return _wa_users_cache["map"].get(''.join(ch for ch in (phone or '') if ch.isdigit()))


def invalidate_wa_users_cache():
    _wa_users_cache["ts"] = 0.0


# ── Sesiones de conversacion (estado multi-paso por numero) ───────────────
# Flujo: reporte -> confirmar equipo -> (duplicado?) -> foto -> crear aviso.
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


# ── Entrada principal ─────────────────────────────────────────────────────

def handle_incoming(app, payload):
    """Procesa un mensaje del gateway y devuelve replies/forwards.

    payload: {message_id, from, phone, push_name, text, media, timestamp}
    """
    phone = (payload.get('phone') or '').strip()
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

    # ── v1: eco de verificacion end-to-end ────────────────────────────
    # Confirma que el pipeline WhatsApp -> gateway -> Flask -> respuesta
    # funciona. El flujo IA (inferir equipo, duplicados, aviso) se conecta
    # en la siguiente iteracion sobre esta misma estructura.
    parts = [f"👋 Hola {nombre}, te leo."]
    if text:
        parts.append(f"Recibi tu mensaje: \"{text[:200]}\"")
    if media:
        parts.append(f"Recibi tambien un archivo ({media.get('type')}, {media.get('mimetype')}).")
    parts.append(
        "🤖 Estoy en modo prueba (v1). Pronto voy a registrar avisos de "
        "falla directamente en el CMMS."
    )
    if _dry_run():
        parts.append("_[DRY-RUN activo: no se escribe nada en la BD]_")

    return {"replies": ["\n\n".join(parts)]}
