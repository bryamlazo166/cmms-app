"""Telegram Bot for CMMS — full data access, actions, alerts via DeepSeek AI."""
import os
import json
import logging
import threading
import time
import collections
import requests
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
# Opcional: para transcribir mensajes de voz (Whisper API). Si no esta seteada,
# el bot responde indicando que la funcion no esta configurada.
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
POLL_INTERVAL = 2


def _parse_int_env(name, default=None):
    raw = (os.getenv(name) or '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name} no es un entero valido: {raw!r}; usando default {default}")
        return default


def _parse_id_list_env(name):
    raw = (os.getenv(name) or '').strip()
    ids = set()
    if not raw:
        return ids
    for chunk in raw.replace(';', ',').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            logger.warning(f"Ignorando ID invalido en {name}: {chunk!r}")
    return ids


# Authorized chat_ids — solo estos pueden usar el bot.
# OWNER_CHAT_ID se lee de TELEGRAM_OWNER_CHAT_ID (variable de entorno).
# La whitelist inicial sale de TELEGRAM_ALLOWED_CHAT_IDS (lista separada por comas).
# El owner SIEMPRE queda autorizado, aunque no aparezca en la lista.
OWNER_CHAT_ID = _parse_int_env('TELEGRAM_OWNER_CHAT_ID')
_allowed_chats = _parse_id_list_env('TELEGRAM_ALLOWED_CHAT_IDS')
if OWNER_CHAT_ID is not None:
    _allowed_chats.add(OWNER_CHAT_ID)

if not _allowed_chats:
    logger.warning(
        "TELEGRAM_ALLOWED_CHAT_IDS y TELEGRAM_OWNER_CHAT_ID estan vacias. "
        "El bot rechazara TODOS los mensajes hasta que se configure al menos un ID."
    )

# Store admin chat_ids for daily alerts
_admin_chats = set()

# Idempotencia: evita procesar el mismo update_id de Telegram dos veces.
# Caso comun: durante un re-deploy en Render, o cuando hay una instancia local
# corriendo en paralelo con la remota, dos procesos polean el mismo token y
# ambos procesan el mismo update (dos transcripciones, dos llamadas a DeepSeek,
# dos respuestas).
#
# Estrategia: dedup persistente en DB (tabla bot_processed_updates) con
# INSERT ... ON CONFLICT DO NOTHING. Solo el primer proceso que inserta gana
# la carrera; el segundo ve rowcount=0 y descarta el update. El deque local
# es un cache LRU para evitar pegarle a la DB en cada poll del MISMO proceso.
_processed_updates = collections.deque(maxlen=500)
_processed_lock = threading.Lock()
_processed_table_ready = False


def _ensure_processed_updates_table(app):
    """Crea la tabla bot_processed_updates si no existe (idempotente)."""
    global _processed_table_ready
    if _processed_table_ready:
        return True
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            _db.session.execute(text(
                "CREATE TABLE IF NOT EXISTS bot_processed_updates ("
                "update_id BIGINT PRIMARY KEY, "
                "processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            _db.session.commit()
        _processed_table_ready = True
        return True
    except Exception as e:
        logger.warning(f"No se pudo crear bot_processed_updates: {e}. "
                       f"Dedup persistente deshabilitado; se usa solo dedup en memoria.")
        return False


def _seen_update(update_id, app=None):
    """Devuelve True si ya procesamos este update_id antes (y lo marca si no).

    Si `app` viene, usa dedup persistente en DB para coordinar entre procesos.
    Si no viene o falla la DB, cae al dedup en memoria (per-process).
    """
    if update_id is None:
        return False
    with _processed_lock:
        if update_id in _processed_updates:
            return True

    if app is not None and _ensure_processed_updates_table(app):
        try:
            from sqlalchemy import text
            from database import db as _db
            with app.app_context():
                # ON CONFLICT DO NOTHING funciona en Postgres >=9.5 y SQLite >=3.24.
                res = _db.session.execute(
                    text("INSERT INTO bot_processed_updates (update_id) "
                         "VALUES (:uid) ON CONFLICT (update_id) DO NOTHING"),
                    {"uid": int(update_id)},
                )
                inserted = (res.rowcount or 0) > 0
                _db.session.commit()
            with _processed_lock:
                _processed_updates.append(update_id)
            if not inserted:
                logger.info(f"update_id {update_id} ya procesado por otra instancia; descartando.")
            return not inserted
        except Exception as e:
            logger.warning(f"Dedup persistente fallo para {update_id}: {e}. Cayendo a memoria.")

    with _processed_lock:
        _processed_updates.append(update_id)
        return False


def _cleanup_processed_updates(app, days=2):
    """Borra entradas de bot_processed_updates mas viejas que `days`."""
    if not _processed_table_ready:
        return
    try:
        from sqlalchemy import text
        from database import db as _db
        with app.app_context():
            _db.session.execute(
                text("DELETE FROM bot_processed_updates "
                     "WHERE processed_at < CURRENT_TIMESTAMP - INTERVAL '%d days'" % days)
                if _db.engine.dialect.name == 'postgresql' else
                text("DELETE FROM bot_processed_updates "
                     "WHERE processed_at < datetime('now', '-%d days')" % days)
            )
            _db.session.commit()
    except Exception as e:
        logger.warning(f"Cleanup bot_processed_updates fallo: {e}")


# ── Contexto del LLM extraido a bot/context.py ───────────────────────────
# El guide loader, chat history, focused equipment y build CMMS context
# viven todos en bot/context.py. Aqui los re-exportamos para compat.
from bot.context import (  # noqa: E402
    _GUIDE_CACHE,
    _load_cmms_guide,
    _chat_history,
    _CHAT_HISTORY_MAX,
    _CHAT_HISTORY_TTL,
    _get_chat_history,
    _append_chat_history,
    _reset_chat_history,
    _get_focused_equipment_context,
    _get_cmms_context,
    _build_cmms_context_real,
    _cached_cmms_context,
    _cached_cmms_context_ts,
    _CACHE_CONTEXT_TTL,
)

def _send_typing(chat_id):
    """Envia el indicador 'typing...' a Telegram. Dura ~5s en el cliente."""
    try:
        _tg_api('sendChatAction', chat_id=chat_id, action='typing')
    except Exception:
        pass


def _tg_api(method, **kwargs):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}'
    r = requests.post(url, json=kwargs, timeout=30)
    return r.json()


def _send(chat_id, text):
    for i in range(0, len(text), 4000):
        _tg_api('sendMessage', chat_id=chat_id, text=text[i:i+4000], parse_mode='Markdown')


# ── Helpers de matching/taxonomia extraidos a bot/resolvers.py ────────
# Las acciones en bot/actions/* importan directo de bot.resolvers.
# Aqui los re-exportamos con prefijo _ por compatibilidad con codigo legacy.
from bot.resolvers import (  # noqa: E402
    COMPONENT_SYNONYMS as _COMPONENT_SYNONYMS,
    FUZZY_STOPWORDS as _FUZZY_STOPWORDS,
    fuzzy_tokens as _fuzzy_tokens,
    build_fuzzy_where as _build_fuzzy_where,
    score_fuzzy_candidates as _score_fuzzy_candidates,
    normalize_token as _normalize_token,
    smart_component_match as _smart_component_match,
    resolve_equipment as _resolve_equipment,
    resolve_taxonomy as _resolve_taxonomy,
)

# ── Acciones de avisos extraidas a bot/actions/notices.py ─────────────
# Re-export con prefijo _ para mantener compatibilidad del dispatcher.
from bot.actions.notices import (  # noqa: E402
    create_notice as _create_notice,
    promote_notice as _promote_notice,
    edit_notice as _edit_notice,
)

# ── Acciones de OT extraidas a bot/actions/work_orders.py ─────────────
# Re-export con prefijo _ para mantener compatibilidad del dispatcher.
from bot.actions.work_orders import (  # noqa: E402
    close_ot as _close_ot,
    add_log_entry as _add_log_entry,
    start_ot as _start_ot,
    reschedule_ot as _reschedule_ot,
    edit_ot as _edit_ot,
)

# Whitelist of editable fields per entity
_NOTICE_EDITABLE = {'description', 'criticality', 'priority', 'maintenance_type',
                    'cancellation_reason', 'status', 'failure_mode', 'failure_category',
                    'closed_date',
                    'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}
_OT_EDITABLE = {'description', 'failure_mode', 'maintenance_type', 'technician_id',
                'scheduled_date', 'estimated_duration', 'tech_count',
                'execution_comments', 'caused_downtime', 'downtime_hours',
                'report_required', 'report_due_date', 'report_url', 'status',
                'real_start_date', 'real_end_date',
                'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}


# ── Acciones y helpers de lubricacion extraidos ──────────────────────
# bot/actions/lubrication.py contiene las 4 acciones y sus 3 helpers.
# Re-export con prefijo _ para mantener compatibilidad del dispatcher.
from bot.actions.lubrication import (  # noqa: E402
    register_lubrication as _register_lubrication,
    register_lubrication_batch as _register_lubrication_batch,
    edit_lubrication as _edit_lubrication,
    delete_lubrication as _delete_lubrication,
    format_point_label as _format_point_label,
    resolve_lub_point_fuzzy as _resolve_lub_point_fuzzy,
    refresh_lub_point_from_executions as _refresh_lub_point_from_executions,
)

# ── Acciones extraidas a bot/actions/ ─────────────────────────────────
# replicate_specs y register_inspection viven en sus propios modulos.
# Se reexponen aca con prefijo _ para no romper el dispatcher.
from bot.actions.specs import replicate_specs as _replicate_specs  # noqa: E402
from bot.actions.inspection import register_inspection as _register_inspection  # noqa: E402

# ── Hammer batches / cambio de martillos FAPMETAL ─────────────────────────
# Las funciones reales viven en bot/actions/hammer_batches.py; las
# re-exponemos aca con los nombres antiguos para no romper imports internos
# del dispatcher.

from bot.actions.hammer_batches import (
    change_hammer_batch as _change_hammer_batch,
    receive_hammer_batch as _receive_hammer_batch,
)


# ── Analisis predictivo y programacion (Mejoras 2 y 3) ────────────────────

_THICKNESS_KEYWORDS = (
    'espesor', 'espesores', 'chaqueta', 'delgado', 'delgada', 'corrosion',
    'inspeccion ut', 'ultrasonido', 'cual toca inspeccionar',
    'que digestor', 'cual digestor', 'mas critico', 'mas delgado',
)

_SCHEDULE_KEYWORDS = (
    'que me toca', 'que toca hoy', 'que toca esta semana', 'que toca manana',
    'que hay programado', 'pendientes de hoy', 'vencidos', 'proximos preventivos',
    'que hay para hacer', 'mis ots de hoy', 'mis ots programadas',
    'agenda de mantenimiento',
)


def _build_thickness_analysis(app, message):
    """Si la pregunta es analitica sobre espesores, inyecta un ranking global."""
    msg_l = (message or '').lower()
    if not any(kw in msg_l for kw in _THICKNESS_KEYWORDS):
        return ''
    try:
        from sqlalchemy import text
        with app.app_context():
            from database import db as _db
            # Top 15 puntos mas criticos (remaining wall ratio)
            rows = _db.session.execute(text("""
                SELECT e.tag, e.name, tp.group_name, tp.section, tp.position,
                       tp.nominal_thickness, tp.alarm_thickness, tp.scrap_thickness,
                       tp.last_value, tp.last_date, tp.status,
                       c.name AS comp_name
                FROM thickness_points tp
                JOIN equipments e ON tp.equipment_id = e.id
                LEFT JOIN components c ON tp.component_id = c.id
                WHERE tp.is_active = TRUE AND tp.last_value IS NOT NULL
                  AND tp.nominal_thickness > 0
                ORDER BY
                  CASE tp.status
                    WHEN 'CRITICO' THEN 0
                    WHEN 'ALERTA' THEN 1
                    ELSE 2
                  END,
                  (tp.last_value / NULLIF(tp.nominal_thickness, 0)) ASC
                LIMIT 15
            """)).fetchall()
            if not rows:
                return ''

            # Agrupar por equipo para ranking
            by_eq = {}
            for r in rows:
                tag = r[0]
                by_eq.setdefault(tag, {'name': r[1], 'points': []})['points'].append(r)

            lines = [
                "=== ANALISIS DE ESPESORES (TOP CRITICOS) ===",
                "INSTRUCCION: el usuario esta pidiendo recomendacion sobre inspecciones.",
                "Ordena por criticidad (CRITICO antes que ALERTA) y recomienda el equipo",
                "con peor remaining wall para inspeccion prioritaria.",
                "",
            ]
            ranked = sorted(by_eq.items(),
                            key=lambda kv: min(
                                (r[8] / r[5]) for r in kv[1]['points'] if r[5] and r[8]
                            ))
            for tag, data in ranked[:8]:
                lines.append(f"EQUIPO [{tag}] {data['name']}:")
                for r in data['points'][:3]:
                    loc = ' - '.join(filter(None, [r[11], r[2], r[3], r[4]]))
                    ratio = (r[8] / r[5] * 100) if r[5] and r[8] else 0
                    lines.append(
                        f"  {r[10]}: {loc} | nominal {r[5]}mm, alarma {r[6]}mm,"
                        f" scrap {r[7]}mm | ultimo {r[8]}mm ({ratio:.0f}%)"
                        f" el {r[9] or '?'}"
                    )
                lines.append("")
            return '\n'.join(lines) + '\n'
    except Exception as e:
        logger.warning(f"_build_thickness_analysis error: {e}")
        return ''


def _build_schedule_context(app, message):
    """Si pregunta por programacion general, lista overdue + proximos 7 dias."""
    msg_l = (message or '').lower()
    if not any(kw in msg_l for kw in _SCHEDULE_KEYWORDS):
        return ''
    try:
        from datetime import date as _date, timedelta as _td
        from sqlalchemy import text
        today = _date.today().isoformat()
        soon = (_date.today() + _td(days=7)).isoformat()

        with app.app_context():
            from database import db as _db
            # OTs programadas/abiertas con scheduled_date en ventana
            ots = _db.session.execute(text("""
                SELECT wo.code, wo.scheduled_date, wo.status, wo.maintenance_type,
                       wo.description, e.tag, e.name
                FROM work_orders wo
                LEFT JOIN equipments e ON wo.equipment_id = e.id
                WHERE wo.status IN ('Abierta','Programada','En Progreso')
                  AND (wo.scheduled_date IS NULL OR wo.scheduled_date <= :soon)
                ORDER BY wo.scheduled_date NULLS LAST, wo.id DESC
                LIMIT 20
            """), {"soon": soon}).fetchall()

            lub = _db.session.execute(text("""
                SELECT lp.code, lp.lubricant_name, lp.next_due_date, e.tag, e.name
                FROM lubrication_points lp
                LEFT JOIN equipments e ON lp.equipment_id = e.id
                WHERE lp.is_active = TRUE AND lp.next_due_date IS NOT NULL
                  AND lp.next_due_date <= :soon
                ORDER BY lp.next_due_date LIMIT 20
            """), {"soon": soon}).fetchall()

            insp = _db.session.execute(text("""
                SELECT ir.code, ir.name, ir.next_due_date, ir.semaphore_status,
                       e.tag, e.name
                FROM inspection_routes ir
                LEFT JOIN equipments e ON ir.equipment_id = e.id
                WHERE ir.is_active = TRUE AND ir.next_due_date IS NOT NULL
                  AND ir.next_due_date <= :soon
                ORDER BY ir.next_due_date LIMIT 20
            """), {"soon": soon}).fetchall()

            mon = _db.session.execute(text("""
                SELECT mp.code, mp.name, mp.next_due_date, e.tag, e.name
                FROM monitoring_points mp
                LEFT JOIN equipments e ON mp.equipment_id = e.id
                WHERE mp.is_active = TRUE AND mp.next_due_date IS NOT NULL
                  AND mp.next_due_date <= :soon
                ORDER BY mp.next_due_date LIMIT 20
            """), {"soon": soon}).fetchall()

            if not (ots or lub or insp or mon):
                return ''

            lines = [
                "=== PROGRAMACION — VENCIDOS Y PROXIMOS 7 DIAS ===",
                "INSTRUCCION: el usuario pregunta por trabajos pendientes. Lista los",
                "items abajo agrupados por tipo, mostrando codigo, fecha, equipo y descripcion.",
                "",
            ]
            if ots:
                lines.append(f"[OTs PENDIENTES ({len(ots)})]")
                for r in ots[:15]:
                    eq = f"[{r[5]}] {r[6]}" if r[5] else "-"
                    lines.append(
                        f"  {r[0]} | {r[2]} | {r[3] or '-'} | {r[1] or 'sin fecha'} | {eq}"
                    )
                    if r[4]:
                        lines.append(f"    desc: {r[4][:140]}")
                lines.append("")
            if lub:
                lines.append(f"[LUBRICACIONES ({len(lub)})]")
                for r in lub[:10]:
                    eq = f"[{r[3]}] {r[4]}" if r[3] else "-"
                    overdue = "VENCIDO" if r[2] and r[2] < today else "proximo"
                    lines.append(f"  {r[0]} | {r[1]} | {r[2]} ({overdue}) | {eq}")
                lines.append("")
            if insp:
                lines.append(f"[INSPECCIONES ({len(insp)})]")
                for r in insp[:10]:
                    eq = f"[{r[4]}] {r[5]}" if r[4] else "-"
                    overdue = "VENCIDO" if r[2] and r[2] < today else "proximo"
                    lines.append(f"  {r[0]} | {r[1]} | {r[2]} ({overdue}) | {eq} | {r[3] or '-'}")
                lines.append("")
            if mon:
                lines.append(f"[MONITOREO ({len(mon)})]")
                for r in mon[:10]:
                    eq = f"[{r[3]}] {r[4]}" if r[3] else "-"
                    overdue = "VENCIDO" if r[2] and r[2] < today else "proximo"
                    lines.append(f"  {r[0]} | {r[1]} | {r[2]} ({overdue}) | {eq}")
                lines.append("")
            return '\n'.join(lines) + '\n'
    except Exception as e:
        logger.warning(f"_build_schedule_context error: {e}")
        return ''


# ── Glosario aprendido (B1) ────────────────────────────────────────────────

def _apply_aliases(app, text_msg, chat_id):
    """Expande aliases conocidos dentro del mensaje del usuario.

    Devuelve (texto_expandido, lista_aliases_aplicados).
    """
    if not text_msg:
        return text_msg, []
    try:
        from utils.aliases import expand_message, increment_usage
        with app.app_context():
            from database import db as _db
            expanded, applied = expand_message(text_msg, chat_id, db_session=_db.session)
            if applied:
                increment_usage(_db.session, applied)
            return expanded, applied
    except Exception as e:
        logger.warning(f"_apply_aliases error: {e}")
        return text_msg, []


def _handle_alias_command(app, chat_id, text_msg):
    """Procesa '/alias <termino> = <expansion> [categoria]'."""
    body = text_msg[len('/alias '):].strip()
    if '=' not in body:
        _send(chat_id, "Formato: `/alias <termino> = <expansion>`\nEjemplo: `/alias FAPMETAL = FAB METAL SAC`")
        return
    parts = body.split('=', 1)
    alias = parts[0].strip()
    rest = parts[1].strip()
    # Categoria opcional al final entre [corchetes]
    category = None
    import re as _re
    m = _re.search(r'\[([^\]]+)\]\s*$', rest)
    if m:
        category = m.group(1).strip()
        rest = rest[:m.start()].strip()
    expansion = rest
    try:
        from utils.aliases import save_alias
        with app.app_context():
            from database import db as _db
            ok, msg = save_alias(_db.session, alias, expansion,
                                 chat_id=None,  # global por defecto
                                 category=category, created_by=str(chat_id))
        emoji = "✅" if ok else "❌"
        _send(chat_id, f"{emoji} {msg}")
    except Exception as e:
        _send(chat_id, f"❌ Error guardando alias: {e}")


def _list_aliases_for_chat(app, chat_id):
    """Responde con la lista de aliases activos."""
    try:
        from utils.aliases import list_aliases
        with app.app_context():
            from database import db as _db
            items = list_aliases(_db.session, chat_id=chat_id, limit=80)
        if not items:
            _send(chat_id, "📚 Sin aliases guardados todavia.\n\nUsa `/alias <termino> = <expansion>` para enseñar al bot.")
            return
        lines = ["📚 *Glosario aprendido:*\n"]
        for it in items:
            cat = f" _[{it['category']}]_" if it.get('category') else ""
            uc = f" (usado {it['usage_count']}x)" if it.get('usage_count') else ""
            lines.append(f"• `{it['alias']}` → {it['expansion']}{cat}{uc}")
        # Telegram limit 4096 chars
        msg = '\n'.join(lines)
        if len(msg) > 3500:
            msg = msg[:3500] + "\n_... (lista truncada)_"
        _send(chat_id, msg)
    except Exception as e:
        _send(chat_id, f"❌ Error listando aliases: {e}")


def _delete_alias_for_chat(app, chat_id, text_msg):
    """Procesa '/borra_alias <termino>'."""
    alias = text_msg[len('/borra_alias '):].strip()
    if not alias:
        _send(chat_id, "Formato: `/borra_alias <termino>`")
        return
    try:
        from utils.aliases import delete_alias
        with app.app_context():
            from database import db as _db
            ok, msg = delete_alias(_db.session, alias)
        emoji = "✅" if ok else "❌"
        _send(chat_id, f"{emoji} {msg}")
    except Exception as e:
        _send(chat_id, f"❌ Error: {e}")


def _build_rag_context(app, query_text):
    """Busca casos historicos similares (OTs cerradas + avisos) y devuelve un
    bloque de contexto para inyectar al prompt del bot.

    Si no hay OPENAI_API_KEY o la tabla esta vacia, devuelve string vacio.
    """
    if not OPENAI_API_KEY or not query_text:
        return ''
    try:
        from utils.embeddings import semantic_search
        with app.app_context():
            from database import db as _db
            # top_k=6 para dar espacio a documentos + casos historicos
            results = semantic_search(_db.session, query_text, top_k=6)
        if not results:
            return ''
        # Filtrar resultados con baja similitud (ruido)
        results = [r for r in results if r.get('similarity', 0) >= 0.35]
        if not results:
            return ''
        # Separar documentos (manuales/planos/informes) de casos historicos (OTs/avisos)
        doc_results = [r for r in results if r['entity_type'] == 'document_link']
        case_results = [r for r in results if r['entity_type'] != 'document_link']
        lines = []
        if doc_results:
            lines.append("=== DOCUMENTOS / MANUALES / PLANOS / INFORMES RELACIONADOS ===")
            lines.append("INSTRUCCION: si el usuario pide un manual, plano, ficha o informe, devuelve")
            lines.append("el(los) link(s) de abajo en formato Markdown [titulo](url) para que sean")
            lines.append("clickeables en Telegram. Usa exactamente la URL tal como aparece.")
            lines.append("")
            for r in doc_results:
                md = r.get('metadata') or {}
                title = md.get('title') or '(sin titulo)'
                doc_type = (md.get('doc_type') or 'doc').upper()
                url = md.get('url') or ''
                parent = md.get('parent_tag') or md.get('parent_name') or '-'
                sim_pct = int(r['similarity'] * 100)
                lines.append(f"- [{doc_type}] {title} (de {parent}, similitud {sim_pct}%)")
                if url:
                    lines.append(f"  URL: {url}")
            lines.append("")
        if case_results:
            lines.append("=== CASOS HISTORICOS SIMILARES (encontrados por busqueda semantica) ===")
            lines.append("INSTRUCCION: si el usuario pregunta '¿como se arreglo la ultima vez?' o pide")
            lines.append("comparar con casos pasados, USA estos como referencia y citalos por codigo.")
            lines.append("Si el texto del caso incluye 'Documentos reportados:' con URLs, preservalas")
            lines.append("en la respuesta como enlaces clickeables [informe](url).")
            lines.append("")
            for i, r in enumerate(case_results, 1):
                sim_pct = int(r['similarity'] * 100)
                lines.append(f"#{i} [{r['entity_type']}] similitud {sim_pct}%:")
                lines.append(r['text_chunk'])
                lines.append("")
        return '\n'.join(lines) + '\n\n'
    except Exception as e:
        logger.warning(f"_build_rag_context error: {e}")
        return ''


def _index_entity_async(app, entity_type, entity_id):
    """Indexa una OT cerrada o un aviso en bot_embeddings. No bloquea."""
    if not OPENAI_API_KEY:
        return
    def _do():
        try:
            from utils.embeddings import upsert_embedding, build_ot_text, build_notice_text
            with app.app_context():
                from database import db as _db
                from models import (
                    WorkOrder, MaintenanceNotice, Area, Line, Equipment, System, Component
                )
                if entity_type == 'work_order':
                    wo = WorkOrder.query.get(entity_id)
                    if not wo:
                        return
                    eq = Equipment.query.get(wo.equipment_id) if wo.equipment_id else None
                    ar = Area.query.get(wo.area_id) if wo.area_id else None
                    ln = Line.query.get(wo.line_id) if wo.line_id else None
                    sy = System.query.get(wo.system_id) if wo.system_id else None
                    co = Component.query.get(wo.component_id) if wo.component_id else None
                    notice = MaintenanceNotice.query.get(wo.notice_id) if wo.notice_id else None
                    text = build_ot_text(wo.to_dict(), equipment=eq, area=ar, line=ln,
                                         system=sy, component=co, notice=notice)
                    metadata = {
                        'code': wo.code,
                        'equipment_tag': eq.tag if eq else None,
                        'failure_mode': wo.failure_mode,
                    }
                    upsert_embedding(_db.session, 'work_order', wo.id, text, metadata)
                    _db.session.commit()
                elif entity_type == 'notice':
                    n = MaintenanceNotice.query.get(entity_id)
                    if not n:
                        return
                    eq = Equipment.query.get(n.equipment_id) if n.equipment_id else None
                    ar = Area.query.get(n.area_id) if n.area_id else None
                    ln = Line.query.get(n.line_id) if n.line_id else None
                    co = Component.query.get(n.component_id) if n.component_id else None
                    text = build_notice_text(n, equipment=eq, area=ar, line=ln, component=co)
                    metadata = {
                        'code': n.code,
                        'equipment_tag': eq.tag if eq else None,
                        'failure_mode': n.failure_mode,
                        'criticality': n.criticality,
                    }
                    upsert_embedding(_db.session, 'notice', n.id, text, metadata)
                    _db.session.commit()
                elif entity_type == 'document_link':
                    from utils.embeddings import build_document_link_text
                    from models import DocumentLink, RotativeAsset
                    doc = DocumentLink.query.get(entity_id)
                    if not doc:
                        return
                    parent_name = None; parent_tag = None
                    category = None; brand = None; model = None
                    area_name = None; line_name = None
                    if doc.entity_type == 'rotative_asset':
                        ra = RotativeAsset.query.get(doc.entity_id)
                        if ra:
                            parent_name = ra.name
                            parent_tag = ra.code
                            category = ra.category
                            brand = ra.brand
                            model = ra.model
                            area_name = ra.area.name if ra.area else None
                            line_name = ra.line.name if ra.line else None
                    elif doc.entity_type == 'equipment':
                        eq = Equipment.query.get(doc.entity_id)
                        if eq:
                            parent_name = eq.name
                            parent_tag = eq.tag
                            area_name = eq.area.name if getattr(eq, 'area', None) else None
                            line_name = eq.line.name if getattr(eq, 'line', None) else None
                    elif doc.entity_type == 'component':
                        co = Component.query.get(doc.entity_id)
                        if co:
                            parent_name = co.name
                    text = build_document_link_text(
                        doc.to_dict(),
                        parent_name=parent_name, parent_tag=parent_tag,
                        parent_type=doc.entity_type,
                        category=category, brand=brand, model=model,
                        area=area_name, line=line_name,
                    )
                    metadata = {
                        'url': doc.url,
                        'title': doc.title,
                        'doc_type': doc.doc_type,
                        'parent_type': doc.entity_type,
                        'parent_id': doc.entity_id,
                        'parent_tag': parent_tag,
                        'parent_name': parent_name,
                    }
                    upsert_embedding(_db.session, 'document_link', doc.id, text, metadata)
                    _db.session.commit()
        except Exception as e:
            logger.warning(f"_index_entity_async error ({entity_type}/{entity_id}): {e}")

    threading.Thread(target=_do, daemon=True).start()


def _download_telegram_file(file_id):
    """Descarga el contenido binario de un archivo de Telegram. Devuelve (bytes, file_path) o (None, None)."""
    try:
        fi = _tg_api('getFile', file_id=file_id)
        if not fi.get('ok'):
            return None, None
        fp = fi['result']['file_path']
        data = requests.get(
            f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{fp}', timeout=30
        ).content
        return data, fp
    except Exception as e:
        logger.warning(f"_download_telegram_file error: {e}")
        return None, None


def _transcribe_voice(file_id, app=None, chat_id=None):
    """Transcribe un mensaje de voz de Telegram usando Whisper API.

    Devuelve el texto transcrito o None si falla. Requiere OPENAI_API_KEY.
    Telegram envia voz en formato OGG/Opus que Whisper acepta nativamente.
    """
    from bot.metrics import track_whisper, Stopwatch
    if not OPENAI_API_KEY:
        return None
    audio_bytes, fp = _download_telegram_file(file_id)
    if not audio_bytes:
        return None
    audio_len = len(audio_bytes)
    try:
        ext = (fp or 'voice.ogg').rsplit('.', 1)[-1] if fp and '.' in fp else 'ogg'
        filename = f"voice.{ext}"
        files = {
            'file': (filename, audio_bytes, 'audio/ogg'),
            'model': (None, 'whisper-1'),
            'language': (None, 'es'),
            'response_format': (None, 'text'),
        }
        headers = {'Authorization': f'Bearer {OPENAI_API_KEY}'}
        with Stopwatch() as sw:
            r = requests.post(
                'https://api.openai.com/v1/audio/transcriptions',
                headers=headers, files=files, timeout=60,
            )
        if r.status_code != 200:
            logger.warning(f"Whisper API error {r.status_code}: {r.text[:200]}")
            track_whisper(app, chat_id, audio_len, sw.elapsed_ms,
                          status='error', error_msg=f"HTTP {r.status_code}")
            return None
        text = r.text.strip()
        track_whisper(app, chat_id, audio_len, sw.elapsed_ms, status='success')
        return text or None
    except Exception as e:
        logger.warning(f"_transcribe_voice error: {e}")
        track_whisper(app, chat_id, audio_len, 0, status='error', error_msg=str(e)[:200])
        return None


def _upload_telegram_photo(app, file_id, entity_type, entity_id):
    try:
        fi = _tg_api('getFile', file_id=file_id)
        if not fi.get('ok'):
            return None
        fp = fi['result']['file_path']
        photo_data = requests.get(f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{fp}', timeout=30).content
        from utils.photo_helpers import compress_photo, upload_to_supabase_storage
        compressed, _ = compress_photo(photo_data)
        url = upload_to_supabase_storage(compressed, f"telegram_{file_id}.jpg")
        with app.app_context():
            from database import db as _db
            from sqlalchemy import text
            _db.session.execute(text("""
                INSERT INTO photo_attachments (entity_type, entity_id, url, caption, original_size_kb, compressed_size_kb, created_at)
                VALUES (:et, :eid, :url, 'Foto desde Telegram', :orig, :comp, NOW())
            """), {"et": entity_type, "eid": entity_id, "url": url, "orig": len(photo_data)//1024, "comp": len(compressed)//1024})
            # Si es inspección UT y aún no tiene pdf_url, asignar esta foto como evidencia
            if entity_type == 'thickness_inspection':
                try:
                    existing = _db.session.execute(text(
                        "SELECT pdf_url FROM thickness_inspections WHERE id = :id"
                    ), {"id": entity_id}).fetchone()
                    if existing and not existing[0]:
                        _db.session.execute(text(
                            "UPDATE thickness_inspections SET pdf_url = :url WHERE id = :id"
                        ), {"url": url, "id": entity_id})
                except Exception as ue:
                    logger.warning(f"thickness_inspection pdf_url update skipped: {ue}")
            _db.session.commit()
            _db.session.remove()
        return url
    except Exception as e:
        logger.error(f"Photo upload error: {e}")
        return None


# ── DeepSeek AI ──────────────────────────────────────────────────────────────

def _ask_deepseek(question, cmms_context, is_action=False, history=None, app=None, chat_id=None):
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}

    action_instructions = """

FORMATO DE RESPUESTA OBLIGATORIO — SIEMPRE respondes con un UNICO objeto JSON valido, NUNCA texto plano.

Hay dos formas posibles:

A) CONSULTA / RESPUESTA DE TEXTO (cuando NO hay accion que ejecutar):
{"action": "none", "reply": "aqui va el texto que quieres mostrar al usuario"}

B) ACCION (cuando el usuario quiere crear/modificar algo — ver lista abajo):
{"action": "<nombre_accion>", "data": {...}}

REGLA CRITICA #1 — DISTINGUIR CONSULTA DE REPORTE DE FALLA:
- Si el usuario PREGUNTA informacion (palabras como "cual", "que", "cuanto", "cuando", "dame", "muestrame", "lista", "ver", "consultar", "donde", "como esta", "que tiene", "tiene...?", "es...?"), SIEMPRE usa action:"none" y responde en reply. NUNCA crees un aviso.
- Si el usuario REPORTA una falla activa (palabras como "esta fallando", "se rompio", "no arranca", "vibra", "hace ruido", "gotea", "se sobrecaliento", "se trabo", "salta el termico", "boto aceite"), entonces crea action:"create_notice".
- Si el usuario solo describe el equipo o pide datos tecnicos (marca, codigo, modelo, especificaciones, ubicacion, ficha tecnica), es CONSULTA → action:"none".
- Ante la duda, prefiere action:"none" con reply explicando lo que entendiste. NUNCA generes un aviso "por si acaso".

REGLA — MODULO DE SEGUIMIENTO (Activities + Milestones):
- Cuando el usuario pregunte por "seguimiento", "actividad", "actividades", "mis seguimientos", "compras", "fabricaciones", "fabricacion", "proyecto", "reunion", "limpieza programada", "trabajo programado", "que se va a hacer", "cuando se hara X", "estado de X" donde X NO es una OT/aviso (es algo mas amplio), SIEMPRE revisa la seccion === SEGUIMIENTO — ACTIVIDADES ACTIVAS === y === SEGUIMIENTO — HITOS === del contexto.
- Las actividades del modulo seguimiento son distintas a las OTs y avisos: son fabricaciones, compras, proyectos, paradas, reuniones u otros trabajos de gestion mas amplios. Tienen tipo (FABRICACION/COMPRA/REUNION/PROYECTO/PARADA/OTRO), prioridad (ALTA/MEDIA/BAJA), responsable, fechas (inicio, meta, completion) y una lista de hitos (milestones).
- Cuando respondas sobre una actividad, MENCIONA: titulo, tipo, responsable, fecha meta y proximo hito pendiente (si existe). Si la actividad esta vinculada a un equipo, indica el tag.
- Si el usuario pregunta "cuando se va a hacer X" / "cuando esta programado Y" — primero busca en SEGUIMIENTO, luego en avisos/OTs/preventivos.
- Ejemplos:
  * "Cuando se va a hacer la limpieza del lavador de vahos?" → busca actividades cuyo titulo o descripcion contenga "lavador" o "vahos" en SEGUIMIENTO. Si existe, responde con titulo, fecha meta y proximo hito.
  * "Que actividades de compra tengo abiertas?" → filtra activity_type=COMPRA con status ABIERTA o EN_PROGRESO.
  * "Que tiene asignado Marcos esta semana en seguimiento?" → filtra responsible=Marcos.

REGLA CRITICA #2: Si el usuario reporta una falla, pide crear/editar/cerrar algo, NO uses action:"none" con reply describiendo la accion. Devuelve la accion real. El campo "reply" NUNCA debe contener frases como "aviso creado", "AV-XXXX generado", "OT cerrada", "accion registrada" — eso solo lo hace el sistema despues de ejecutar la accion real.

ACCIONES DISPONIBLES:

1. CREAR AVISO (reportar falla o registrar actividad):
{"action": "create_notice", "data": {"description": "...", "scope": "PLAN|FUERA_PLAN|GENERAL", "failure_mode": "Rotura|Desgaste|Fuga|Desalineacion|Sobrecalentamiento|Ruido anormal|Vibracion excesiva|Aflojamiento|Corrosion|Atascamiento|Descarrilamiento|Cortocircuito|Sobrecarga|Fatiga", "failure_category": "Mecanica|Electrica|Hidraulica|Neumatica|Instrumentacion|Lubricacion|Estructural", "blockage_object": "Metal|Piedra|Cadena|Madera|Alambre|Perno|Acero Inoxidable|Bronce|Otro", "equipment_tag": "D8", "component_name": "motor electrico", "free_location": "texto libre si no hay equipo", "criticality": "Alta|Media|Baja", "priority": "Alta|Normal|Baja", "maintenance_type": "Correctivo|Preventivo|Mejora", "event_date": "YYYY-MM-DD opcional"}}

REGLA CRITICA #3 — FECHA DEL EVENTO (event_date):
- Si el usuario menciona CUANDO ocurrio la falla (ej: "ayer", "anteayer", "hace 2 dias", "el lunes pasado", "el 23 de abril", "anoche", "en la madrugada del 22"), SIEMPRE incluye event_date con la fecha en formato ISO YYYY-MM-DD.
- Si NO menciona fecha (reporta algo que esta ocurriendo ahora o no aclara), OMITE event_date — el sistema usara la fecha de hoy.
- Calcula relativos respecto a HOY que es """ + date.today().isoformat() + """.
- Ejemplos:
  * "ayer se rompio la chumacera del D3" → event_date: """ + (date.today() - timedelta(days=1)).isoformat() + """
  * "anoche el motor del D5 boto chispas" → event_date: """ + (date.today() - timedelta(days=1)).isoformat() + """
  * "hace 3 dias se trabo el D9" → event_date: """ + (date.today() - timedelta(days=3)).isoformat() + """
  * "el viernes pasado vibro mucho el TH2" → event_date: viernes anterior a hoy en ISO
  * "el 22 de abril fallo la bomba" → event_date: 2026-04-22 (asume año actual si no especifica)
  * "se sobrecaliento el motor del D8" (sin fecha) → OMITE event_date

REGLAS PARA EL CAMPO scope (CRITICO):
- "PLAN" = falla/trabajo sobre un equipo que SI esta en el arbol (lista EQUIPOS del contexto). REQUIERE equipment_tag valido. Es el caso por defecto y mas comun.
- "FUERA_PLAN" = trabajo sobre un equipo REAL pero todavia NO inventariado en el arbol. Usalo cuando el usuario diga "no esta en el sistema", "todavia no lo tengo", "sin inventariar", "no esta en el arbol", o cuando mencione un equipo que NO existe en la lista EQUIPOS. Incluye SIEMPRE free_location describiendo donde esta fisicamente.
- "GENERAL" = actividad generica de mantenimiento que NO es sobre un equipo del arbol y nunca lo sera. Ejemplos: pintar barandas, limpiar canaletas, fabricar soporte, instalar luminarias en oficina, traslado de chatarra, capacitacion, soporte a otra area, obra civil, jardineria. NO pongas equipment_tag ni component_name. Pon free_location si tiene sentido (ej: "area coccion - barandas perimetrales").
- Si el usuario dice "no es de equipos", "es trabajo general", "no es falla", usa GENERAL.
- Cuando es scope GENERAL o FUERA_PLAN, los campos failure_mode y failure_category son opcionales (puedes omitirlos si no aplica).
- Si dudas entre PLAN y FUERA_PLAN: si encuentras el equipo en la lista EQUIPOS por tag o nombre, usa PLAN. Si NO lo encuentras, usa FUERA_PLAN automaticamente.

Ejemplos de scope:
- "el digestor 8 vibra" → scope:"PLAN", equipment_tag:"D8"
- "hay una bomba en el sotano de calderas que esta goteando, todavia no la tenemos en el arbol" → scope:"FUERA_PLAN", free_location:"sotano calderas - bomba sin inventariar"
- "FAPMETAL pinto las barandas del area de coccion hoy" → scope:"GENERAL", free_location:"area coccion - barandas", maintenance_type:"Mejora"
- "se hizo limpieza profunda del piso de la sala electrica" → scope:"GENERAL", free_location:"sala electrica - piso"
- "fabricamos un soporte para la nueva tuberia" → scope:"GENERAL"

REGLAS CRITICAS PARA IDENTIFICAR equipo Y componente:
1. SIEMPRE incluye `equipment_tag` (D1..D9, TH1..TH3, etc.) tomado de la lista EQUIPOS. NUNCA dejes el aviso sin equipo si el usuario menciona uno.
2. SIEMPRE intenta incluir `component_name` con el nombre del componente especifico. NO te quedes solo en el equipo. El sistema tiene un matcher inteligente con sinonimos que resolvera el componente real.
   - "motor del D8", "motor electrico del digestor 8" → component_name: "motor electrico"
   - "reductor del D5", "caja reductora del digestor 5" → component_name: "reductor"
   - "motorreductor del TH2", "motor-reductor del transportador 2" → component_name: "motorreductor"
   - "chumacera lado conducido del D3" → component_name: "chumacera conducida"
   - "chumacera motriz del D1" → component_name: "chumacera motriz"
   - "faja del D3", "banda del digestor 3" → component_name: "faja"
   - "rodamiento del motor del TH2" → component_name: "motor electrico" (porque el rodamiento vive dentro del motor)
   - "valvula de la reductora" → component_name: "reductor" (la valvula vive dentro)
   - "rodillo de salida del transportador 2" → component_name: "rodillo"
3. Si el usuario menciona un activo rotativo especifico por codigo (ej: "MTR-D8", "RED-TH2-01") busca ese codigo en la lista ACTIVOS ROTATIVOS y usa rotative_asset_id con el asset_id correspondiente. El sistema deducira solo el equipo y componente desde ese asset.
4. Si NO mencionas un asset por codigo, NO pongas rotative_asset_id — el codigo lo deducira automaticamente del componente si hay un asset instalado.
5. Si no hay equipo claro, omite equipment_tag y usa free_location.

Ejemplos:
- "el motor del digestor 8 esta sobrecalentando" → {"action":"create_notice","data":{"description":"Sobrecalentamiento en motor electrico del Digestor #8 - revisar bobinado y rodamientos","failure_mode":"Sobrecalentamiento","failure_category":"Electrica","equipment_tag":"D8","component_name":"motor electrico","criticality":"Alta"}}
- "rodamiento de la caja reductora del TH2 hace ruido" → {"action":"create_notice","data":{"description":"Ruido anormal en rodamiento de caja reductora del TH2","failure_mode":"Ruido anormal","failure_category":"Mecanica","equipment_tag":"TH2","component_name":"reductor","criticality":"Media"}}
- "se rompio la chumacera conducida del D3" → {"action":"create_notice","data":{"description":"Rotura de chumacera lado conducido del Digestor #3","failure_mode":"Rotura","failure_category":"Mecanica","equipment_tag":"D3","component_name":"chumacera conducida","criticality":"Alta"}}
- "fuga de aceite en el motorreductor del TH1" → component_name:"motorreductor"
- "el D9 se bloqueo por una cadena que ingreso con la materia prima" → {"action":"create_notice","data":{"description":"Bloqueo del Digestor #9 por cadena ingresada con materia prima - revisar tripode interno","failure_mode":"Atascamiento","failure_category":"Mecanica","blockage_object":"Cadena","equipment_tag":"D9","component_name":"tripode interno","criticality":"Alta"}}
- "D5 se trabo por piedra" → failure_mode:"Atascamiento", blockage_object:"Piedra"
- "encontramos un fierro dentro del D3" → failure_mode:"Atascamiento", blockage_object:"Metal"
- "el D7 se paro porque ingreso madera" → failure_mode:"Atascamiento", blockage_object:"Madera"

REGLA PARA BLOQUEOS: Cuando el usuario reporta que un digestor se "bloqueo", "trabo", "atasco", "paro por objeto", SIEMPRE usa failure_mode:"Atascamiento" e incluye blockage_object con el tipo de objeto (Metal, Piedra, Cadena, Madera, Alambre, Perno, Acero Inoxidable, Bronce, Otro). Si no dice que objeto fue, pregunta.

2. CERRAR OT:
{"action": "close_ot", "data": {"ot_code": "OT-0034", "comments": "Trabajo completado - se reemplazo faja y se verifico alineacion", "event_date": "YYYY-MM-DD opcional"}}
- event_date: si el usuario regulariza un cierre que ocurrio en el pasado ("ayer cerre la OT-0034", "el viernes terminamos el cambio de faja"), aplica la regla #3 y manda la fecha real en ISO. Si no menciona fecha, OMITE event_date.

3. INICIAR OT:
{"action": "start_ot", "data": {"ot_code": "OT-0034"}}

4. AGREGAR NOTA A BITACORA:
{"action": "add_log", "data": {"ot_code": "OT-0034", "comment": "Se cambio faja y se alineo poleas", "entry_type": "NOTA|AVANCE|MATERIAL|PROVEEDOR|INFORME"}}

REGLA CRITICA — CONSULTAR vs ESCRIBIR EN BITACORA:
- Si el usuario dice "revisa la bitacora", "muestrame la bitacora", "que dice la bitacora", "muestrame el informe", "necesito el informe", "hay link del informe", "donde esta el informe", es una CONSULTA (action:"none") — NO uses add_log.
- Para responder, busca en la seccion "BITACORA DE OTs" del contexto entradas de la OT solicitada.
- Si la OT tiene un "Informe: <url>" en la lista de OTs, devuelve ese URL al usuario.
- Si alguna entrada de bitacora contiene una URL (http://... o https://...), preserva esa URL en tu respuesta como link clickeable [Informe](url).
- Si no hay ni report_url ni URLs en la bitacora, di "no hay informe registrado para la OT-XXXX" — y sugiere que se cargue desde la pantalla de OTs (campo "Link del informe").
- Solo usa add_log cuando el usuario pida REGISTRAR/AGREGAR/ANOTAR algo nuevo ("agrega a la bitacora", "anota que...", "registra en la OT que...").

REGISTRAR LINK DE INFORME — Si el usuario dice "el informe de la OT-XXXX esta en https://...",
"agrega el link del informe a la OT-XXXX: <url>", "guarda el informe de la OT-XXXX en <url>", usa:
{"action": "edit_ot", "data": {"ot_code": "OT-XXXX", "fields": {"report_url": "https://..."}}}

REGISTRAR RECORDATORIO / PENDIENTE FUTURO — Cuando el usuario dice "recordame", "agendame",
"avisame", "no me olvides", "en X dias/semanas/meses", "para el dia DD/MM" y refiere una OT,
crea una entrada de bitacora con tipo PENDIENTE y log_date en el futuro:
{"action": "add_log", "data": {"ot_code": "OT-XXXX", "log_date": "YYYY-MM-DD",
                                "comment": "lo que hay que hacer", "entry_type": "PENDIENTE"}}

REGLAS PARA INTERPRETAR DURACIONES (calcula tu mismo la fecha futura usando la fecha de hoy):
- "en 1 mes" / "en un mes" → +30 dias
- "en mes y medio" / "en 1.5 meses" → +45 dias
- "en 2 meses" → +60 dias
- "en 15 dias" / "en dos semanas" → +14/15 dias
- "el viernes proximo" → calcula la fecha del proximo viernes
- "para el 15 de junio" → 2026-06-15 (interpreta el año actual si no se aclara)

EJEMPLOS:
- "recordame en 1 mes fabricar el tripode para D3 (OT-0034)"
  → {"action":"add_log","data":{"ot_code":"OT-0034","log_date":"2026-06-08","comment":"Fabricar tripode para D3","entry_type":"PENDIENTE"}}
- "agenda en la OT-0028 que en 45 dias hay que reingresar a inspeccionar el D7"
  → {"action":"add_log","data":{"ot_code":"OT-0028","log_date":"2026-06-22","comment":"Reingresar a inspeccionar el D7","entry_type":"PENDIENTE"}}
- "no me olvides que el 2026-07-01 vence la garantia del motor de la OT-0050"
  → {"action":"add_log","data":{"ot_code":"OT-0050","log_date":"2026-07-01","comment":"Vence garantia del motor","entry_type":"PENDIENTE"}}

5. REPROGRAMAR OT (cambiar fecha):
{"action": "reschedule_ot", "data": {"ot_code": "OT-0034", "new_date": "2026-04-10"}}
Convierte fechas relativas: "lunes" = proximo lunes, "mañana" = fecha de mañana. Hoy es """ + date.today().isoformat() + """.

6. EDITAR AVISO (modificar campos de un aviso existente):
{"action": "edit_notice", "data": {"notice_code": "AV-0003", "fields": {"description": "nueva descripcion", "criticality": "Alta", "priority": "Alta", "maintenance_type": "Correctivo", "status": "Pendiente|Anulado", "cancellation_reason": "texto si status=Anulado", "equipment_tag": "H2", "system_name": "SISTEMA DE ACCIONAMIENTO", "component_name": "MOTOR ELECTRICO"}}}
Campos editables permitidos: description, criticality, priority, maintenance_type, status, cancellation_reason, failure_mode, failure_category, closed_date.
Campos de TAXONOMIA (para cambiar equipo/sistema/componente): equipment_tag, equipment_name, system_name, component_name.
  - equipment_tag: tag del equipo destino (ej: "D8", "H2", "SEC2-TH3"). El sistema resuelve automaticamente line_id y area_id.
  - system_name: nombre del sistema dentro del equipo (ej: "SISTEMA DE ACCIONAMIENTO", "SISTEMA ELECTRICO").
  - component_name: nombre del componente dentro del sistema (ej: "MOTOR ELECTRICO", "REDUCTOR").
  - Si cambias equipo en un aviso, las OTs vinculadas se actualizan automaticamente.
Solo incluye en "fields" los campos que el usuario pide cambiar. No inventes valores.
Ejemplos:
- "cambia la criticidad del AV-0003 a alta" → {"action":"edit_notice","data":{"notice_code":"AV-0003","fields":{"criticality":"Alta"}}}
- "corrige la descripcion del AV-0005: ahora es fuga de aceite en reductor" → {"action":"edit_notice","data":{"notice_code":"AV-0005","fields":{"description":"Fuga de aceite en reductor - revisar retenes"}}}
- "anula el AV-0002, era duplicado" → {"action":"edit_notice","data":{"notice_code":"AV-0002","fields":{"status":"Anulado","cancellation_reason":"Duplicado"}}}
- "el AV-0019 es de la hidrolavadora 2, no la 3" → {"action":"edit_notice","data":{"notice_code":"AV-0019","fields":{"equipment_tag":"H2"}}}
- "cambia el AV-0010 al motor del digestor 8" → {"action":"edit_notice","data":{"notice_code":"AV-0010","fields":{"equipment_tag":"D8","system_name":"SISTEMA DE ACCIONAMIENTO","component_name":"MOTOR ELECTRICO"}}}

7b. REGISTRAR LUBRICACION (cuando el usuario reporta que se lubrico un punto POR PRIMERA VEZ):
{"action": "register_lubrication", "data": {"point_query": "chumacera motriz percolador 2", "execution_date": "2026-03-30", "executed_by": "Marcos Campos", "quantity_used": 0.5, "comments": "opcional", "leak_detected": false, "anomaly_detected": false}}
- DETECTOR: frases tipo "se lubrico X", "lubrico X", "engrasamos X", "le pusimos grasa al X", "se le hizo lubricacion al X" SIEMPRE son register_lubrication. NO son create_notice ni consulta.
- Para identificar el punto usa SIEMPRE `point_query` con texto descriptivo libre que incluya el componente y el equipo. El sistema parte el texto en tokens, aplica sinonimos y rankea por mejor coincidencia — asi tolera orden libre, palabras intermedias y tokens extras.
- IMPORTANTE — VOCABULARIO de los puntos de lubricacion: en este CMMS los puntos se llaman SIEMPRE "CHUMACERA" (no "rodamiento" ni "cojinete"). Cuando el usuario diga "rodamiento motriz X" → emite point_query "chumacera motriz X". Cuando diga "cojinete X" → "chumacera X". El rodamiento vive DENTRO de la chumacera; el punto de lubricacion se nombra por la chumacera.
- IMPORTANTE — NOMBRES DE EQUIPOS: revisa la seccion PUNTOS DE LUBRICACION del contexto antes de armar point_query. Los equipos a veces tienen nombres especiales (ej: "TH2 ALIMENTADOR ENFRIADOR" se llama TH2A-SECA en tag, NO "secador 2"). Si el usuario dice "th2 alimentador secador 2" o "alimentador al secador 2", busca en la lista cual equipo encaja realmente y usa esos terminos en point_query (ej: "chumacera motriz th2a seca" o solo "chumacera motriz th2a"). Si no encuentras un equipo claro, usa el codigo TAG textualmente.
- Mantra: NO inventes palabras que no esten en la lista de puntos. Si dudas entre dos formas, elige la mas corta y especifica (codigo o tag del equipo).
- Solo usa `point_id` si en el contexto ves explicitamente el punto correcto con `id:NN` y estas 100% seguro. Si dudas, usa point_query — es mas robusto.
- Solo usa `point_code` si el usuario menciona un codigo exacto tipo "LUB-D8-CHM-MOT".
- execution_date: convierte fechas relativas ("ayer", "hoy", "el viernes pasado") o textuales ("24-abril", "30 de marzo") a formato ISO YYYY-MM-DD. Si dicen hora, ignorala. Hoy es """ + date.today().isoformat() + """. "24-abril" → 2026-04-24. "el viernes" → viernes pasado en ISO.
- executed_by: por defecto "MANTENIMIENTO". Si el usuario menciona "FAPMETAL" o "fap metal" usa "FAPMETAL". Si menciona un nombre y apellido, usalo TAL CUAL (ej: "Marcos Campos").
- leak_detected/anomaly_detected: solo true si el usuario lo menciona explicitamente. Si los marca true, se creara automaticamente un aviso de mantenimiento.
- IMPORTANTE: NO uses esta accion si el usuario dice "corrige", "cambia", "actualiza", "estaba mal", "era ayer", "era el ...", "no era ese tecnico" sobre una ejecucion ya registrada. En esos casos usa edit_lubrication.
- IMPORTANTE: NO uses esta accion si el usuario dice "elimina", "borra", "anula" una ejecucion. Usa delete_lubrication.
- Ejemplos COMPLETOS:
  * "Se lubrico chumacera motriz del percolador #2 el 24-abril, Marcos Campos" → {"action":"register_lubrication","data":{"point_query":"chumacera motriz percolador 2","execution_date":"2026-04-24","executed_by":"Marcos Campos"}}
  * "el viernes lubrico la cadena del percolador #2, Marcos Campos" → {"action":"register_lubrication","data":{"point_query":"cadena percolador 2","execution_date":"<viernes pasado en ISO>","executed_by":"Marcos Campos"}}
  * "ayer FAPMETAL engraso el reductor del D8" → {"action":"register_lubrication","data":{"point_query":"reductor digestor 8","execution_date":"<ayer ISO>","executed_by":"FAPMETAL"}}

7b-bis. REGISTRAR LUBRICACIONES MULTIPLES (LOTE) — cuando el usuario enumera VARIOS componentes lubricados en un solo mensaje, con la misma fecha y ejecutor:
{"action": "register_lubrication_batch", "data": {"points": ["chumacera conducida THAL-SECA", "chumacera motriz THAL-SECA", "cadena THAL-SECA"], "execution_date": "2026-04-15", "executed_by": "FAPMETAL"}}
- DETECTOR: frases con LISTAS de componentes separados por coma o "y", todos del MISMO equipo, con UNA SOLA fecha y un solo ejecutor. Ej: "se lubrico la chumacera conducida, chumacera motriz y cadena del TH alimentador al secador 1", "ayer engrasamos cadena y dos chumaceras del molino 1", "FAPMETAL hizo lubricacion de chumacera motriz, conducida y cadena del D8".
- CADA item de `points` es un point_query INDEPENDIENTE: incluye el componente + el equipo (mismo equipo en todos). Aplica TODAS las reglas de point_query de la seccion 7b (vocabulario CHUMACERA, sinonimos, tag textual del equipo).
- Campos comunes (execution_date, executed_by, action_type) van fuera de `points` y se aplican a todos. Si un componente tiene una particularidad (ej: cantidad distinta), usa item dict: {"point_query":"cadena TH...", "quantity_used":0.2}.
- USA esta accion en LUGAR de register_lubrication cuando hay 2+ componentes. NO emitas multiples actions sueltas.
- Ejemplos:
  * "el 15-abril se lubrico la chumacera conducida, chumacera motriz y cadena del TH alimentador al secador 1" → {"action":"register_lubrication_batch","data":{"points":["chumacera conducida thal seca","chumacera motriz thal seca","cadena thal seca"],"execution_date":"2026-04-15","executed_by":"MANTENIMIENTO"}}
  * "ayer FAPMETAL engraso chumacera motriz, conducida y cadena del D8" → {"action":"register_lubrication_batch","data":{"points":["chumacera motriz d8","chumacera conducida d8","cadena d8"],"execution_date":"<ayer ISO>","executed_by":"FAPMETAL"}}
  * "Marcos Campos lubrico hoy las dos chumaceras del percolador 2" → {"action":"register_lubrication_batch","data":{"points":["chumacera motriz percolador 2","chumacera conducida percolador 2"],"executed_by":"Marcos Campos"}}

7c. EDITAR LUBRICACION (corregir una ejecucion ya registrada):
{"action": "edit_lubrication", "data": {"exec_id": 123, "fields": {"execution_date": "2026-04-06", "executed_by": "FAPMETAL", "quantity_used": 0.3, "comments": "...", "leak_detected": true}}}
- Busca el exec_id en ULTIMAS EJECUCIONES DE LUBRICACION del contexto. Identifica cual ejecucion es por el punto + fecha + ejecutor que mencione el usuario.
- Si hay mas de una ejecucion candidata, responde con action:none y un reply listando las opciones para que el usuario aclare cual.
- Solo incluye en "fields" los campos que el usuario quiere cambiar. Campos editables: execution_date, executed_by, quantity_used, quantity_unit, comments, leak_detected, anomaly_detected, action_type.
- Ejemplo: usuario dice "corrige la lubricacion de la chumacera conducida del D9, fue ayer no hoy". Buscas en EJECUCIONES la mas reciente del LUB-D9-CHM-CON, tomas su exec_id, y devuelves: {"action":"edit_lubrication","data":{"exec_id":<el id>,"fields":{"execution_date":"<ayer en ISO>"}}}
- Ejemplo: "la del D5 chumacera motriz no fue mantenimiento, fue FAPMETAL" → {"action":"edit_lubrication","data":{"exec_id":<id>,"fields":{"executed_by":"FAPMETAL"}}}

7d. ELIMINAR LUBRICACION (borrar una ejecucion mal registrada):
{"action": "delete_lubrication", "data": {"exec_id": 123}}
- Usalo cuando el usuario diga "elimina", "borra", "anula", "ese registro estaba mal", "fue duplicado".
- Igual que edit, busca el exec_id en EJECUCIONES por contexto. Si hay ambiguedad, pregunta primero con action:none.

7d-bis. REPLICAR ESPECIFICACIONES (cuando el usuario quiere copiar las specs tecnicas de un componente o equipo a otro):
{"action": "replicate_specs", "data": {"entity_type": "component|equipment", "source_equipment_tag": "MOLI1-LINE", "source_component_name": "chumacera conducida", "target_equipment_tag": "MOLI1-LINE", "target_component_name": "chumacera motriz", "mode": "merge|replace", "overwrite": false}}
- Usalo cuando el usuario diga frases como "replica las specs de X a Y", "copia las especificaciones de la chumacera conducida del molino 1 a la chumacera motriz del mismo molino", "los datos tecnicos del motor del D8 son los mismos que los del D9, copialos", "duplica las specs de A en B".
- entity_type: 'component' (default, mas comun) si copia entre componentes; 'equipment' si copia entre equipos completos.
- mode: 'merge' (default) NO toca las keys que el destino ya tiene. 'replace' borra TODAS las specs del destino antes de copiar — solo usalo si el usuario lo pide explicitamente con palabras como "reemplaza todas", "borra y copia", "sobreescribe completamente".
- overwrite: solo aplica con merge. true si el usuario dice "actualiza los valores aunque ya existan", "sobreescribe los valores que coincidan".
- Para componentes incluye SIEMPRE source_equipment_tag y source_component_name (ambos), y lo mismo para target_*. El sistema usa el matcher inteligente con sinonimos (chumacera motriz/conducida, motor electrico/mtr, etc).
- Si el origen y destino son del mismo equipo, repite el mismo equipment_tag en source_* y target_*.

REGLA CRITICA #X PARA replicate_specs (NO IGNORAR — caso real de bug):
- Usa LITERALMENTE los tags que el usuario menciona. Si el usuario dice "TH6", source_equipment_tag DEBE ser "TH6" — NO "TH5", NO "TH3", NO ningun otro tag aunque el TH6 no aparezca en el contexto.
- NUNCA substituyas, aproximes o "redondees" el tag a otro equipo similar. La accion es DESTRUCTIVA y copiar al equipo equivocado es peor que fallar.
- Si el tag que pidio el usuario NO esta en la lista EQUIPOS del contexto, NO inventes otro tag. Devuelve action:"none" con reply pidiendo confirmacion: ej. "No encuentro 'TH6' en el arbol. Tags disponibles que se parecen: TH1, TH2, TH3, TH5. ¿Cual es el correcto?".
- Una sola accion replicate_specs por mensaje. Si el usuario menciona varias copias en un solo mensaje, ejecuta SOLO la primera y deja un reply mencionando las pendientes. NUNCA inventes restricciones tipo "no puedo procesar multiples solicitudes" — eso no existe en el sistema.

- Ejemplos:
  * "replica las specs de la chumacera conducida del molino 1 a la chumacera motriz del molino 1" → {"action":"replicate_specs","data":{"entity_type":"component","source_equipment_tag":"MOLI1-LINE","source_component_name":"chumacera conducida","target_equipment_tag":"MOLI1-LINE","target_component_name":"chumacera motriz"}}
  * "copia las especificaciones del motor del D8 al motor del D9" → {"action":"replicate_specs","data":{"entity_type":"component","source_equipment_tag":"D8","source_component_name":"motor electrico","target_equipment_tag":"D9","target_component_name":"motor electrico"}}
  * "duplica las specs del reductor del TH2 al reductor del TH3, y sobreescribe lo que ya tenga" → mode:"merge", overwrite:true.
  * "borra las specs del motor del D5 y copia las del D8" → mode:"replace".

7e. REGISTRAR INSPECCION (cuando el usuario reporta que ejecuto una ruta de inspeccion):
{"action": "register_inspection", "data": {"route_id": 5, "execution_date": "2026-04-24", "executed_by": "INSPECTOR|nombre tecnico", "overall_result": "OK|CON_HALLAZGOS", "findings_count": 0, "comments": "opcional"}}
- Busca la ruta en la lista RUTAS DE INSPECCION del contexto. Usa el `id` que aparece como `id:NN`. Tambien puedes usar `route_code`.
- Si no encuentras id exacto, usa `route_query` con texto fuzzy: {"route_query": "inspeccion semanal D8"}
- execution_date: aplica la REGLA #3 (event_date). Si dicen "ayer se hizo la inspeccion semanal del D8" → fecha de ayer en ISO. Si dicen "hoy" o no aclaran, omitelo (default hoy).
- overall_result: "OK" si no hay hallazgos. "CON_HALLAZGOS" si el usuario reporta problemas. Si no aclara y findings_count>0, el sistema lo deduce.
- findings_count: numero de hallazgos. Si dice "encontre 2 fugas y 1 perno suelto" → findings_count:3. Si dice "todo bien" → 0.
- IMPORTANTE: si findings_count>0, el sistema crea automaticamente un aviso vinculado. Tu solo registras la inspeccion.
- Ejemplos:
  * "hoy hice la inspeccion semanal del D8, todo OK" → {"action":"register_inspection","data":{"route_query":"semanal D8","overall_result":"OK","findings_count":0}}
  * "ayer revise la ruta INS-TH3 y encontre dos fugas" → {"action":"register_inspection","data":{"route_code":"INS-TH3","execution_date":"<ayer ISO>","overall_result":"CON_HALLAZGOS","findings_count":2,"comments":"dos fugas detectadas"}}
  * "anteayer FAPMETAL hizo la inspeccion mensual del molino, sin hallazgos" → executed_by:"FAPMETAL", findings_count:0, execution_date:<anteayer ISO>

7f. CAMBIO DE MARTILLOS EN MOLINO (cuando el usuario reporta un cambio nocturno de lote de martillos):
{"action": "change_hammer_batch", "data": {"mill": "M1|M2", "start_time": "YYYY-MM-DDTHH:MM", "end_time": "YYYY-MM-DDTHH:MM", "lubrication_done": true, "hammers_changed_count": 72, "notes": "opcional", "batch_out_code": "opcional override", "batch_in_code": "opcional override"}}
- DETECTOR: frases tipo "cambiaron martillos del molino X", "FAPMETAL cambio los martillos del molino X", "rotamos el lote de martillos del molino X", "cambio de martillos en M1/M2", "el lote LOTE-A se retiro del molino 1", "se hizo el cambio nocturno de martillos".
- mill: "M1" para Molino #1, "M2" para Molino #2. Acepta variantes como "molino 1", "molino #1", "molino uno", "M1", "el primer molino".
- start_time / end_time: formato ISO con hora "YYYY-MM-DDTHH:MM" (ej: "2026-05-13T04:30"). Aplica REGLA #3 para la fecha (event_date).
  * "anoche de 4:30 a 5:30" → start_time del dia anterior 04:30, end_time del dia anterior 05:30
  * "hoy de 04:00 a 05:10" → start_time hoy 04:00, end_time hoy 05:10
  * Si el usuario da solo duracion ("duro una hora desde las 4:30") deduce end_time = start_time + duracion.
- lubrication_done: por DEFAULT true (FAPMETAL siempre lubrica chumaceras motriz y conducida en el mismo servicio). Marcalo false SOLO si el usuario explicita "sin lubricacion" o "no lubricaron".
- hammers_changed_count: por defecto 72 (lote completo). Solo override si el usuario aclara "cambiaron solo X martillos" o "fueron Y martillos".
- batch_out_code / batch_in_code: SOLO incluir si el usuario menciona explicitamente codigo de lote (ej. "salio el LOTE-A, entro el LOTE-C"). Si no, el sistema infiere automaticamente (hay 1 lote en cada slot).
- notes: capturar cualquier observacion adicional ("solo cambiaron por la noche porque no habia produccion en dia", "encontraron 3 martillos doblados", etc.).
- Ejemplos:
  * "anoche FAPMETAL cambio los martillos del molino 1 de 4:30 a 5:30" → {"action":"change_hammer_batch","data":{"mill":"M1","start_time":"<ayer ISO>T04:30","end_time":"<ayer ISO>T05:30","lubrication_done":true}}
  * "se cambiaron los martillos del molino 2 hoy de 04:15 a 05:20, ademas lubricaron chumaceras" → {"action":"change_hammer_batch","data":{"mill":"M2","start_time":"<hoy ISO>T04:15","end_time":"<hoy ISO>T05:20","lubrication_done":true}}
  * "cambio nocturno de martillos M1 ayer, salio LOTE-B y entro LOTE-C, 4:00 a 5:00" → {"action":"change_hammer_batch","data":{"mill":"M1","start_time":"<ayer ISO>T04:00","end_time":"<ayer ISO>T05:00","batch_out_code":"LOTE-B","batch_in_code":"LOTE-C"}}

7g. RECIBIR LOTE RELLENADO DE FAPMETAL (cuando el usuario reporta que FAPMETAL devolvio un lote rellenado):
{"action": "receive_hammer_batch", "data": {"batch_code": "LOTE-A", "event_date": "YYYY-MM-DD", "notes": "opcional"}}
- DETECTOR: frases tipo "FAPMETAL entrego el lote rellenado", "llego el LOTE-X rellenado", "recibimos los martillos rellenados", "ya devolvieron el lote de martillos".
- batch_code: codigo del lote (ej. "LOTE-A"). Si el usuario no especifica y hay un solo lote en EN_FAPMETAL, el sistema lo infiere — omite batch_code.
- event_date: fecha de recepcion. Aplica REGLA #3 (default hoy).
- Ejemplos:
  * "FAPMETAL trajo hoy el LOTE-A rellenado" → {"action":"receive_hammer_batch","data":{"batch_code":"LOTE-A"}}
  * "ayer recibimos los martillos rellenados" → {"action":"receive_hammer_batch","data":{"event_date":"<ayer ISO>"}}
  * "llego el lote rellenado de fapmetal" → {"action":"receive_hammer_batch","data":{}}

8. PROMOVER / DEGRADAR AVISO (cambiar scope y vincular o desvincular equipo):
{"action": "promote_notice", "data": {"notice_code": "AV-0010", "target_scope": "PLAN|FUERA_PLAN|GENERAL", "equipment_tag": "D8", "component_name": "motor electrico", "free_location": "opcional"}}
- Usalo cuando el usuario diga frases como "vincula el AV-0010 al equipo D8", "promueve el AV-0010 al digestor 9", "el AV-0010 ya tiene equipo, es la bomba BMB-01", "ese aviso era general, marca como tal", "el AV-0007 ya no es del D5, era servicio general".
- target_scope:"PLAN" REQUIERE equipment_tag (y opcionalmente component_name). El sistema resuelve el componente con sinonimos como en create_notice.
- target_scope:"FUERA_PLAN" o "GENERAL" desvinculan el aviso de cualquier equipo del arbol. Para FUERA_PLAN incluye free_location si la conoces.
- IMPORTANTE: cuando promueves a PLAN, las OTs vinculadas al aviso TAMBIEN se actualizan automaticamente al nuevo equipo. No tienes que hacer nada extra para eso.
- Ejemplos:
  * "vincula el AV-0012 al motor del digestor 8" → {"action":"promote_notice","data":{"notice_code":"AV-0012","target_scope":"PLAN","equipment_tag":"D8","component_name":"motor electrico"}}
  * "el AV-0007 era trabajo general, no es de equipos" → {"action":"promote_notice","data":{"notice_code":"AV-0007","target_scope":"GENERAL"}}
  * "marca el AV-0009 como fuera de plan, es una bomba que aun no inventariamos" → {"action":"promote_notice","data":{"notice_code":"AV-0009","target_scope":"FUERA_PLAN","free_location":"bomba sin inventariar"}}

7. EDITAR OT (modificar campos de una OT existente):
{"action": "edit_ot", "data": {"ot_code": "OT-0034", "fields": {"description": "...", "technician_id": "CARLOS LUQUE", "estimated_duration": 4, "tech_count": 2, "scheduled_date": "2026-04-10", "execution_comments": "...", "caused_downtime": true, "downtime_hours": 1.5, "equipment_tag": "H2", "system_name": "SISTEMA DE ACCIONAMIENTO", "component_name": "MOTOR ELECTRICO"}}}
Campos editables permitidos: description, failure_mode, maintenance_type, technician_id, scheduled_date, estimated_duration, tech_count, execution_comments, caused_downtime, downtime_hours, report_required, report_due_date, status.
Campos de TAXONOMIA (para cambiar equipo/sistema/componente): equipment_tag, equipment_name, system_name, component_name.
  - equipment_tag: tag del equipo destino (ej: "D8", "H2", "SEC2-TH3"). Resuelve automaticamente line_id y area_id.
  - system_name: nombre del sistema dentro del equipo (ej: "SISTEMA DE ACCIONAMIENTO", "SISTEMA ELECTRICO").
  - component_name: nombre del componente dentro del sistema (ej: "MOTOR ELECTRICO", "REDUCTOR").
  - Si cambias equipo en una OT, el aviso vinculado se actualiza automaticamente.
  - IMPORTANTE: cuando el usuario diga "deberia ser la hidrolavadora 2" o "cambialo al digestor 8" o "el equipo correcto es TH5", usa equipment_tag para cambiar el equipo. NO cambies solo la descripcion.
Ejemplos:
- "asigna la OT-0034 a Carlos Luque" → {"action":"edit_ot","data":{"ot_code":"OT-0034","fields":{"technician_id":"CARLOS LUQUE CCOLQUE"}}}
- "la OT-0034 duro 3 horas y paro la linea 1 hora" → {"action":"edit_ot","data":{"ot_code":"OT-0034","fields":{"caused_downtime":true,"downtime_hours":1}}}
- "cambia la duracion estimada de la OT-0034 a 6 horas y asigna 2 tecnicos" → {"action":"edit_ot","data":{"ot_code":"OT-0034","fields":{"estimated_duration":6,"tech_count":2}}}
- "la OT-0014 deberia ser la hidrolavadora 2, no la 3" → {"action":"edit_ot","data":{"ot_code":"OT-0014","fields":{"equipment_tag":"H2"}}}
- "cambia la OT-0014 al motor del D8" → {"action":"edit_ot","data":{"ot_code":"OT-0014","fields":{"equipment_tag":"D8","system_name":"SISTEMA DE ACCIONAMIENTO","component_name":"MOTOR ELECTRICO"}}}
Nota: para cambiar SOLO la fecha programada, prefiere reschedule_ot. Para cerrar/iniciar OT usa close_ot/start_ot.

REGLAS para interpretar avisos:
- description: Redacta profesionalmente orientado al modo de falla, NO copies textual al usuario.
  Ej: usuario dice "la faja se rompio" → "Rotura de faja de transmision - requiere inspeccion y reemplazo"
  Ej: "el motor suena raro" → "Ruido anormal en motor electrico - posible falla en rodamientos"
  Ej: "el reductor bota aceite" → "Fuga de aceite en caja reductora - revisar retenes y nivel"
- Busca el equipo en los DATOS del sistema por tag o nombre
- Si el usuario menciona un equipo que NO existe en el arbol, PREGUNTA si quiere crearlo sin equipo vinculado
- Si el usuario EXPLICITAMENTE pide crear el aviso sin equipo, o dice "sin equipo", "sin vincular", "asi nomas", genera el JSON SIN los campos equipment_tag, equipment_name, component_name
- SIEMPRE puedes crear un aviso sin equipo vinculado. El campo "free_location" permite texto libre para ubicacion
  Ej: {"action": "create_notice", "data": {"description": "Fuga de vapor en tuberia zona calderas", "failure_mode": "Fuga", "failure_category": "Mecanica", "criticality": "Alta", "free_location": "Tuberia zona calderas - no mapeado en arbol"}}
- Si es consulta normal (ej: "cuantas OTs abiertas hay?"), usa {"action":"none","reply":"..."} con la respuesta en reply.

EJEMPLOS DE CONSULTAS (TODAS deben usar action:"none"):
- "cual es la chumacera motriz del TH10" → CONSULTA, no aviso
- "que marca de rodamiento usa el D5" → CONSULTA
- "dame las specs del motor del digestor 3" → CONSULTA
- "cuantas OTs hay abiertas" → CONSULTA
- "muestrame los avisos de hoy" → CONSULTA
- "que componentes tiene el sistema de accionamiento del TH7" → CONSULTA
- "cual es el codigo del rodamiento del D9" → CONSULTA

EJEMPLOS DE REPORTES DE FALLA (deben usar action:"create_notice"):
- "el motor del D8 esta sobrecalentando" → FALLA → create_notice
- "vibra mucho la chumacera del TH3" → FALLA → create_notice
- "se rompio la cadena del TH5" → FALLA → create_notice"""

    cmms_guide = _load_cmms_guide()
    guide_block = f"\n=== CONOCIMIENTO MAESTRO DEL CMMS (politicas, vocabulario y procesos) ===\n{cmms_guide}\n" if cmms_guide else ""

    system_prompt = f"""Eres el asistente de mantenimiento del CMMS Pro, sistema de gestion de mantenimiento industrial.
SIEMPRE respondes con un objeto JSON valido (ver FORMATO DE RESPUESTA OBLIGATORIO abajo). NUNCA texto plano fuera de JSON.
Dentro del campo "reply" responde en español, conciso y profesional. Usa SOLO datos reales del sistema.
NUNCA inventes datos ni confirmes acciones no realizadas.
Si no tienes info, responde {{"action":"none","reply":"No tengo esa informacion."}}.
{guide_block}

CONSULTAS DE ESPECIFICACIONES TECNICAS (modelo, marca, codigo, parte, dimensiones, ficha tecnica):
- Busca PRIMERO en la seccion '=== FOCO DE CONSULTA ===' las lineas '* CLAVE: VALOR' debajo del COMPONENTE pedido. Esas SON las specs.
- Si no hay foco, busca en '=== SPECS DE COMPONENTES ===' por '[TAG] NOMBRE_COMPONENTE: ...'.
- Si encuentras specs, responde listandolas: "El componente X tiene: marca=NTN, modelo=UCF315, ...".
- Solo responde "no hay especificaciones" si efectivamente no aparece ninguna linea de spec para ese componente o si aparece 'SPEC_FALTANTE'.
- IMPORTANTE: notas tipograficas como CHUAMCERA = CHUMACERA. Usa el dato aunque haya errores de tipeo.

Cuando el usuario pida ANALISIS o RECOMENDACIONES, puedes:
- Calcular % correctivo vs preventivo
- Identificar equipos problematicos (mas OTs correctivas)
- Sugerir preventivos basados en recurrencia de fallas
- Comparar rendimiento entre equipos similares
- Priorizar backlog de OTs por criticidad y recurrencia
- Generar resumen ejecutivo para gerencia
- Estimar consumo de repuestos basado en frecuencia de cambio
- Sugerir plan semanal basado en OTs pendientes y puntos vencidos
{action_instructions}

DATOS ACTUALES:
{cmms_context}
"""

    # Construir mensajes: system + historial previo (opcional) + pregunta actual
    messages = [{'role': 'system', 'content': system_prompt}]
    if history:
        # Solo incluir entradas con role valido (user/assistant) y content no vacio.
        # El historial NO incluye otro 'system' (ya esta arriba).
        for h in history:
            r = (h or {}).get('role')
            c = (h or {}).get('content')
            if r in ('user', 'assistant') and c:
                messages.append({'role': r, 'content': c})
    messages.append({'role': 'user', 'content': question})

    payload = {
        'model': 'deepseek-chat',
        'messages': messages,
        'max_tokens': 2000, 'temperature': 0.2,
        'response_format': {'type': 'json_object'},
    }

    from bot.metrics import track_deepseek, Stopwatch
    try:
        with Stopwatch() as sw:
            r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            track_deepseek(app, chat_id, 'deepseek-chat', None, sw.elapsed_ms,
                           status='error', error_msg=f"HTTP {r.status_code}")
            return f"Error DeepSeek: {r.status_code} {r.text[:200]}"
        body = r.json()
        track_deepseek(app, chat_id, 'deepseek-chat',
                       body.get('usage') or {}, sw.elapsed_ms, status='success')
        return body['choices'][0]['message']['content']
    except Exception as e:
        track_deepseek(app, chat_id, 'deepseek-chat', None, 0,
                       status='error', error_msg=str(e)[:200])
        return f"Error consultando IA: {e}"


# ── Daily Alerts ─────────────────────────────────────────────────────────────

def _generate_daily_summary(app):
    """Generate and send daily summary to all known admin chats."""
    if not _admin_chats:
        return

    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            wo_open = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status != 'Cerrada'")).scalar()
            wo_progress = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'En Progreso'")).scalar()
            n_pending = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE status = 'Pendiente'")).scalar()

            lub = _db.session.execute(text("SELECT count(*) FROM lubrication_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
            insp = _db.session.execute(text("SELECT count(*) FROM inspection_routes WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
            mon = _db.session.execute(text("SELECT count(*) FROM monitoring_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0

            # OTs overdue (scheduled but not started, past date)
            overdue = _db.session.execute(text("""
                SELECT code, description, scheduled_date FROM work_orders
                WHERE status IN ('Abierta', 'Programada') AND scheduled_date IS NOT NULL AND scheduled_date < :today
                ORDER BY scheduled_date LIMIT 10
            """), {"today": date.today().isoformat()}).fetchall()

            # Reports pending
            reports_due = _db.session.execute(text("""
                SELECT code, report_due_date FROM work_orders
                WHERE report_required = true AND report_status = 'PENDIENTE'
                AND report_due_date IS NOT NULL AND report_due_date < :today
            """), {"today": date.today().isoformat()}).fetchall()

            # Low stock — detalle de items
            low_stock_items = _db.session.execute(text("""
                SELECT code, name, current_stock, min_stock, unit
                FROM warehouse_items
                WHERE is_active = true AND current_stock <= min_stock
                ORDER BY (current_stock - min_stock) ASC LIMIT 15
            """)).fetchall()
            low_stock = len(low_stock_items)

            # Espesores UT vencidos
            ut_vencidos = 0
            try:
                ut_vencidos = _db.session.execute(text("""
                    SELECT count(DISTINCT equipment_id) FROM thickness_inspections
                    WHERE next_due_date IS NOT NULL AND next_due_date < :today
                """), {"today": date.today().isoformat()}).scalar() or 0
            except Exception:
                pass

            # Recordatorios PENDIENTES — entradas de bitacora con tipo
            # PENDIENTE cuya fecha es hoy o pasada (vencida).
            try:
                today_iso = date.today().isoformat()
                pendientes_due = _db.session.execute(text("""
                    SELECT le.id, le.log_date, le.comment, le.author, w.code,
                           e.tag, e.name
                    FROM ot_log_entries le
                    JOIN work_orders w ON le.work_order_id = w.id
                    LEFT JOIN equipments e ON w.equipment_id = e.id
                    WHERE le.log_type = 'PENDIENTE'
                      AND le.log_date <= :today
                    ORDER BY le.log_date ASC LIMIT 20
                """), {"today": today_iso}).fetchall()
            except Exception as e:
                logger.warning(f"pendientes_due fetch error: {e}")
                pendientes_due = []

            _db.session.remove()

            # Build message
            msg = f"""📊 *Resumen Diario CMMS* — {date.today().isoformat()}

📋 OTs abiertas: *{wo_open}* | En progreso: *{wo_progress}*
🔔 Avisos pendientes: *{n_pending}*"""

            if lub + insp + mon > 0:
                msg += f"\n\n🔴 *Puntos vencidos:*\n  Lubricacion: {lub} | Inspeccion: {insp} | Monitoreo: {mon}"

            if ut_vencidos > 0:
                msg += f"\n  Espesores UT: {ut_vencidos} equipo(s)"

            if overdue:
                msg += f"\n\n⏰ *OTs vencidas ({len(overdue)}):*"
                for o in overdue:
                    msg += f"\n  {o[0]} — prog: {o[2]} — {(o[1] or '-')[:50]}"

            if reports_due:
                msg += f"\n\n📄 *Informes vencidos ({len(reports_due)}):*"
                for r in reports_due:
                    msg += f"\n  {r[0]} — vencio: {r[1]}"

            if low_stock > 0:
                msg += f"\n\n📦 *Stock bajo ({low_stock} items):*"
                for item in low_stock_items:
                    stock_val = int(item[2]) if item[2] else 0
                    min_val = int(item[3]) if item[3] else 0
                    status_icon = '🔴' if stock_val == 0 else '🟡'
                    msg += f"\n  {status_icon} {item[0]} {item[1][:35]} → *{stock_val}* / min: {min_val} {item[4] or 'und'}"
                if low_stock > 15:
                    msg += f"\n  _...y {low_stock - 15} items más_"

            if pendientes_due:
                msg += f"\n\n⏰ *Recordatorios / Pendientes ({len(pendientes_due)}):*"
                today_iso = date.today().isoformat()
                for p in pendientes_due:
                    icon = '⚠️' if p[1] < today_iso else '📅'
                    eq = f" · {p[5] or ''}".strip(' ·') if p[5] else ''
                    when = 'HOY' if p[1] == today_iso else f"vencio {p[1]}"
                    cmt = (p[2] or '')[:90]
                    msg += f"\n  {icon} {p[4]}{eq} ({when}): {cmt}"

            msg += "\n\n_Escribe cualquier pregunta para mas detalles._"

            for cid in _admin_chats:
                try:
                    _send(cid, msg)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Daily summary error: {e}")
            try:
                _db.session.remove()
            except Exception:
                pass


def _check_recurring_alerts(app):
    """Alert on components with high failure frequency."""
    if not _admin_chats:
        return

    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            cutoff = (date.today() - timedelta(days=60)).isoformat()
            rec = _db.session.execute(text("""
                SELECT c.name, e.name, e.tag, l.name, count(w.id) as cnt
                FROM work_orders w
                JOIN components c ON w.component_id = c.id
                JOIN systems s ON c.system_id = s.id
                JOIN equipments e ON w.equipment_id = e.id
                JOIN lines l ON e.line_id = l.id
                WHERE w.maintenance_type = 'Correctivo' AND w.real_start_date >= :cutoff
                GROUP BY c.name, e.name, e.tag, l.name
                HAVING count(w.id) >= 3
                ORDER BY cnt DESC LIMIT 5
            """), {"cutoff": cutoff}).fetchall()

            _db.session.remove()

            if rec:
                msg = "🚨 *Alerta: Fallas Recurrentes (ultimos 60 dias)*\n"
                for r in rec:
                    msg += f"\n⚠️ *{r[0]}* en {r[1]} [{r[2]}] ({r[3]}) — *{r[4]} correctivos*"
                msg += "\n\n_Considera revision de causa raiz o cambio preventivo._"

                for cid in _admin_chats:
                    try:
                        _send(cid, msg)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Recurring alerts error: {e}")
            try:
                _db.session.remove()
            except Exception:
                pass


def _generate_weekly_report(app):
    """Generate weekly report every Monday."""
    if not _admin_chats:
        return

    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            week_ago = (date.today() - timedelta(days=7)).isoformat()

            closed = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'Cerrada' AND real_end_date >= :d"), {"d": week_ago}).scalar() or 0
            created = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE code > '' AND id >= (SELECT COALESCE(MAX(id),0) FROM work_orders) - 50")).scalar() or 0
            open_now = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status != 'Cerrada'")).scalar() or 0
            notices_w = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE request_date >= :d"), {"d": week_ago}).scalar() or 0

            corr = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Correctivo' AND real_end_date >= :d"), {"d": week_ago}).scalar() or 0
            prev = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Preventivo' AND real_end_date >= :d"), {"d": week_ago}).scalar() or 0

            # Top equipment with most OTs this week
            top_eq = _db.session.execute(text("""
                SELECT e.name, e.tag, count(w.id) FROM work_orders w
                JOIN equipments e ON w.equipment_id = e.id
                WHERE w.real_end_date >= :d OR (w.status != 'Cerrada' AND w.scheduled_date >= :d)
                GROUP BY e.name, e.tag ORDER BY count(w.id) DESC LIMIT 5
            """), {"d": week_ago}).fetchall()

            _db.session.remove()

            total_w = corr + prev
            corr_pct = round(corr / total_w * 100) if total_w > 0 else 0
            prev_pct = round(prev / total_w * 100) if total_w > 0 else 0

            msg = f"""📊 *Reporte Semanal CMMS*
_{week_ago} al {date.today().isoformat()}_

✅ OTs cerradas: *{closed}*
📋 Avisos nuevos: *{notices_w}*
📂 OTs abiertas ahora: *{open_now}*

⚙️ Correctivo: {corr} ({corr_pct}%) | Preventivo: {prev} ({prev_pct}%)"""

            if top_eq:
                msg += "\n\n🏭 *Equipos con mas actividad:*"
                for e in top_eq:
                    msg += f"\n  {e[0]} [{e[1]}] — {e[2]} OTs"

            msg += "\n\n_Escribe 'resumen ejecutivo' para mas detalle._"

            for cid in _admin_chats:
                try:
                    _send(cid, msg)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Weekly report error: {e}")
            try:
                _db.session.remove()
            except Exception:
                pass


# ── Message Processing ───────────────────────────────────────────────────────

_pending_photos = {}

ACTION_KEYWORDS = ['reportar', 'crear aviso', 'falla', 'fallo', 'se rompio', 'roto', 'rota',
                   'daño', 'dañ', 'parada', 'parado', 'generar aviso', 'registrar falla',
                   'no funciona', 'no sirve', 'se salio', 'se solto', 'fuera de servicio',
                   'cerrar ot', 'cierra ot', 'cerrar la ot', 'cierra la ot',
                   'iniciar ot', 'inicia ot', 'iniciar la ot', 'empezar ot',
                   'agregar nota', 'agregar bitacora', 'anotar en', 'registrar en ot',
                   'nota a la ot', 'bitacora ot',
                   'reprogramar', 'mover ot', 'cambiar fecha', 'postergar', 'adelantar']


def _extract_json(text):
    """Extract JSON from AI response. Robusto: tolera markdown, prosa antes/despues
    del JSON, y JSON con llaves desbalanceadas (intenta extraer el primer objeto valido)."""
    if not text:
        return None
    s = text.strip()
    # 1) Bloques markdown ```json ... ```
    if '```' in s:
        import re as _re
        for m in _re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", s, _re.DOTALL):
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    # 2) Si el texto entero es JSON
    if s.startswith('{'):
        try:
            return json.loads(s)
        except Exception:
            pass
    # 3) Buscar el primer objeto JSON balanceado (greedy desde primera '{')
    start = s.find('{')
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except Exception:
                            break
        start = s.find('{', start + 1)
    return None


def _process_message(app, chat_id, text, photos=None):
    text = (text or '').strip()

    # Authorization check
    if chat_id not in _allowed_chats:
        _send(chat_id, "🔒 No autorizado. Contacta al administrador del CMMS.")
        logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")
        return

    # Owner commands
    if chat_id == OWNER_CHAT_ID and text.lower().startswith('/autorizar'):
        parts = text.split()
        if len(parts) == 2 and parts[1].lstrip('-').isdigit():
            new_id = int(parts[1])
            _allowed_chats.add(new_id)
            _send(chat_id, f"✅ Chat ID *{new_id}* autorizado.")
        else:
            _send(chat_id, "Uso: `/autorizar <chat_id>`")
        return

    if chat_id == OWNER_CHAT_ID and text.lower().startswith('/revocar'):
        parts = text.split()
        if len(parts) == 2 and parts[1].lstrip('-').isdigit():
            rev_id = int(parts[1])
            if rev_id == OWNER_CHAT_ID:
                _send(chat_id, "❌ No puedes revocarte a ti mismo.")
            else:
                _allowed_chats.discard(rev_id)
                _send(chat_id, f"🚫 Chat ID *{rev_id}* revocado.")
        else:
            _send(chat_id, "Uso: `/revocar <chat_id>`")
        return

    if chat_id == OWNER_CHAT_ID and text.lower() == '/usuarios':
        users = '\n'.join(f"  `{cid}`" + (' (tu)' if cid == OWNER_CHAT_ID else '') for cid in _allowed_chats)
        _send(chat_id, f"👥 *Usuarios autorizados:*\n{users}")
        return

    # Track for daily alerts
    _admin_chats.add(chat_id)

    # Handle photos
    if photos:
        pending = _pending_photos.get(chat_id)
        if pending:
            uploaded = 0
            for p in photos:
                fid = p[-1]['file_id']
                if _upload_telegram_photo(app, fid, pending['entity_type'], pending['entity_id']):
                    uploaded += 1
            _send(chat_id, f"📷 {uploaded} foto(s) subida(s) al {pending['entity_type']} {pending.get('code', '')}." if uploaded else "❌ Error subiendo foto.")
        else:
            _send(chat_id, "📷 Foto recibida pero no hay aviso activo.\nPrimero reporta una falla y luego envia la foto.")
        return

    if not text:
        return

    # Comando: vincular PDF a última inspección UT del equipo
    # Uso: /ut_pdf D7 https://drive.google.com/...
    if text.lower().startswith('/ut_pdf'):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            _send(chat_id, "Uso: `/ut_pdf <TAG_EQUIPO> <URL_PDF>`\nEj: `/ut_pdf D7 https://drive.google.com/...`")
            return
        eq_tag = parts[1].strip().upper()
        pdf_url = parts[2].strip()
        try:
            with app.app_context():
                from database import db as _db
                from sqlalchemy import text as _t
                # Buscar equipo
                eq = _db.session.execute(_t(
                    "SELECT id, name FROM equipments WHERE UPPER(tag) = :tag"
                ), {"tag": eq_tag}).fetchone()
                if not eq:
                    _send(chat_id, f"❌ No encontré el equipo con tag *{eq_tag}*.")
                    return
                # Buscar última inspección UT
                insp = _db.session.execute(_t(
                    "SELECT id, inspection_date FROM thickness_inspections "
                    "WHERE equipment_id = :eid ORDER BY inspection_date DESC, id DESC LIMIT 1"
                ), {"eid": eq[0]}).fetchone()
                if not insp:
                    _send(chat_id, f"❌ No hay inspecciones UT registradas para *{eq_tag}* ({eq[1]}).")
                    return
                # Actualizar
                _db.session.execute(_t(
                    "UPDATE thickness_inspections SET pdf_url = :url WHERE id = :id"
                ), {"url": pdf_url, "id": insp[0]})
                _db.session.commit()
                _send(chat_id, f"✅ PDF vinculado a la inspección UT del *{eq_tag}* del *{insp[1]}*.\n📎 {pdf_url}")
        except Exception as e:
            logger.error(f"/ut_pdf error: {e}")
            _send(chat_id, f"❌ Error: {e}")
        return

    # Comando: reporte de contratista
    if text.lower().startswith('/reporte_contratista'):
        parts = text.split(maxsplit=1)
        provider_filter = parts[1].strip().upper() if len(parts) > 1 else None
        try:
            with app.app_context():
                from database import db as _db
                from sqlalchemy import text as _t
                # Mes actual
                today = date.today()
                month_start = today.replace(day=1).isoformat()
                month_end = today.isoformat()
                month_name = today.strftime('%B %Y')

                q = """
                    SELECT p.name AS provider,
                           count(*) AS total_ots,
                           sum(CASE WHEN w.status = 'Cerrada' THEN 1 ELSE 0 END) AS cerradas,
                           COALESCE(sum(w.real_duration), 0) AS total_hours,
                           COALESCE(sum(w.downtime_hours), 0) AS downtime_hrs
                    FROM work_orders w
                    JOIN providers p ON w.provider_id = p.id
                    WHERE w.scheduled_date >= :s AND w.scheduled_date <= :e
                """
                params = {"s": month_start, "e": month_end}
                if provider_filter:
                    q += " AND UPPER(p.name) LIKE :pf"
                    params["pf"] = f"%{provider_filter}%"
                q += " GROUP BY p.name ORDER BY total_ots DESC"

                rows = _db.session.execute(_t(q), params).fetchall()

                # Avisos creados por contratistas vía telegram
                aviso_q = """
                    SELECT reporter_name, count(*) AS cnt
                    FROM maintenance_notices
                    WHERE request_date >= :s AND request_date <= :e
                    AND reporter_type = 'telegram'
                """
                if provider_filter:
                    aviso_q += " AND UPPER(reporter_name) LIKE :pf"
                aviso_q += " GROUP BY reporter_name ORDER BY cnt DESC"
                avisos = _db.session.execute(_t(aviso_q), params).fetchall()

                # Lubricaciones ejecutadas
                lub_q = """
                    SELECT executed_by, count(*) AS cnt
                    FROM lubrication_executions
                    WHERE execution_date >= :s AND execution_date <= :e
                """
                if provider_filter:
                    lub_q += " AND UPPER(executed_by) LIKE :pf"
                lub_q += " GROUP BY executed_by ORDER BY cnt DESC"
                lubs = _db.session.execute(_t(lub_q), params).fetchall()

                _db.session.remove()

                msg = f"📋 *Reporte de Contratistas — {month_name}*\n"
                if provider_filter:
                    msg += f"Filtro: {provider_filter}\n"

                if rows:
                    msg += f"\n*OTs asignadas:*"
                    for r in rows:
                        pct = round(r[2] / r[1] * 100) if r[1] else 0
                        msg += f"\n  🔧 *{r[0]}*: {r[1]} OTs ({r[2]} cerradas, {pct}%) | {r[3]:.1f}h trabajo | {r[4]:.1f}h downtime"
                else:
                    msg += "\nSin OTs de contratistas este mes."

                if avisos:
                    msg += f"\n\n*Avisos reportados (Telegram):*"
                    for a in avisos:
                        msg += f"\n  📱 {a[0]}: {a[1]} avisos"

                if lubs:
                    msg += f"\n\n*Lubricaciones ejecutadas:*"
                    for l in lubs:
                        msg += f"\n  🛢 {l[0]}: {l[1]} puntos"

                _send(chat_id, msg)
        except Exception as e:
            logger.error(f"/reporte_contratista error: {e}")
            _send(chat_id, f"❌ Error: {e}")
        return

    # Comando: crear recordatorio en la bitacora de una OT.
    # Sintaxis: /recordar OT-XXXX <duracion|fecha> <mensaje>
    # Ejemplos:
    #   /recordar OT-0034 30d fabricar tripode para D3
    #   /recordar OT-0034 1m revisar progreso del proveedor
    #   /recordar OT-0034 1.5m reingresar a inspeccion D7
    #   /recordar OT-0034 2026-06-15 recibir entrega del eje
    if text.lower().startswith('/recordar'):
        import re as _re_rem
        parts = text.split(maxsplit=3)
        if len(parts) < 4:
            _send(chat_id,
                "Formato: `/recordar OT-XXXX <duracion> <mensaje>`\n"
                "Duracion: `30d` (dias), `2w` (semanas), `1m` (meses), `1.5m` (1 mes y medio), o fecha `YYYY-MM-DD`.\n\n"
                "Ejemplos:\n"
                "• `/recordar OT-0034 1m fabricar tripode para D3`\n"
                "• `/recordar OT-0028 45d reingresar a inspeccionar D7`\n"
                "• `/recordar OT-0050 2026-06-15 recibir entrega del proveedor`")
            return
        ot_code = parts[1].upper().strip()
        if not ot_code.startswith('OT-'):
            _send(chat_id, "El primer argumento debe ser una OT, ej: OT-0034")
            return
        duration_raw = parts[2].strip().lower()
        message_text = parts[3].strip()

        # Parsear duracion → fecha futura
        target_date = None
        try:
            if _re_rem.match(r'^\d{4}-\d{2}-\d{2}$', duration_raw):
                target_date = date.fromisoformat(duration_raw)
            else:
                m = _re_rem.match(r'^(\d+(?:[.,]\d+)?)\s*([dwm])$', duration_raw)
                if not m:
                    _send(chat_id, f"Duracion '{duration_raw}' no reconocida. Usa Nd / Nw / Nm o YYYY-MM-DD.")
                    return
                val = float(m.group(1).replace(',', '.'))
                unit = m.group(2)
                days = {'d': 1, 'w': 7, 'm': 30}[unit] * val
                target_date = date.today() + timedelta(days=int(round(days)))
        except Exception as e:
            _send(chat_id, f"No pude interpretar la fecha: {e}")
            return

        # Persistir en ot_log_entries con tipo PENDIENTE
        try:
            with app.app_context():
                from database import db as _db
                from sqlalchemy import text as _t
                row = _db.session.execute(_t("SELECT id FROM work_orders WHERE code = :c"),
                                          {"c": ot_code}).fetchone()
                if not row:
                    _db.session.remove()
                    _send(chat_id, f"❌ {ot_code} no encontrada.")
                    return
                ot_id = row[0]
                author = f"Telegram:{chat_id}"
                _db.session.execute(_t("""
                    INSERT INTO ot_log_entries (work_order_id, log_date, log_type,
                                                 author, comment, created_at)
                    VALUES (:wid, :d, 'PENDIENTE', :a, :c, NOW())
                """), {"wid": ot_id, "d": target_date.isoformat(),
                       "a": author, "c": message_text})
                _db.session.commit()
                _db.session.remove()
            days_left = (target_date - date.today()).days
            _send(chat_id,
                f"⏰ *Recordatorio agendado*\n"
                f"OT: `{ot_code}`\n"
                f"Fecha: *{target_date.isoformat()}* (en {days_left} dia{'s' if days_left != 1 else ''})\n"
                f"Tarea: _{message_text}_\n\n"
                f"Aparecera en el resumen diario cuando llegue la fecha.")
        except Exception as e:
            logger.error(f"/recordar error: {e}")
            _send(chat_id, f"❌ Error guardando recordatorio: {e}")
        return

    # Comando: listar recordatorios pendientes (vencidos + proximos 7 dias)
    if text.lower().startswith('/recordatorios') or text.lower().startswith('/pendientes'):
        try:
            with app.app_context():
                from database import db as _db
                from sqlalchemy import text as _t
                today_iso = date.today().isoformat()
                week_iso = (date.today() + timedelta(days=7)).isoformat()
                rows = _db.session.execute(_t("""
                    SELECT le.log_date, le.comment, le.author, w.code, e.tag
                    FROM ot_log_entries le
                    JOIN work_orders w ON le.work_order_id = w.id
                    LEFT JOIN equipments e ON w.equipment_id = e.id
                    WHERE le.log_type = 'PENDIENTE'
                      AND le.log_date <= :w
                    ORDER BY le.log_date ASC LIMIT 30
                """), {"w": week_iso}).fetchall()
                _db.session.remove()
            if not rows:
                _send(chat_id, "✅ Sin recordatorios vencidos ni proximos 7 dias.")
                return
            msg = "⏰ *Recordatorios — vencidos + proximos 7 dias*\n"
            for r in rows:
                d = r[0]
                if d < today_iso:
                    icon = '⚠️'; when = f"VENCIO {d}"
                elif d == today_iso:
                    icon = '🔴'; when = "HOY"
                else:
                    delta = (date.fromisoformat(d) - date.today()).days
                    icon = '📅'; when = f"en {delta}d ({d})"
                eq = f" [{r[4]}]" if r[4] else ''
                msg += f"\n{icon} *{r[3]}*{eq} ({when})\n   _{(r[1] or '')[:120]}_"
            _send(chat_id, msg)
        except Exception as e:
            logger.error(f"/recordatorios error: {e}")
            _send(chat_id, f"❌ Error: {e}")
        return

    # Comando: subir foto del formato UT a la última inspección
    # Uso: /ut_foto D7  → luego enviar la foto
    if text.lower().startswith('/ut_foto'):
        parts = text.split()
        if len(parts) < 2:
            _send(chat_id, "Uso: `/ut_foto <TAG_EQUIPO>` y luego envía la foto del formato.")
            return
        eq_tag = parts[1].strip().upper()
        try:
            with app.app_context():
                from database import db as _db
                from sqlalchemy import text as _t
                eq = _db.session.execute(_t(
                    "SELECT id, name FROM equipments WHERE UPPER(tag) = :tag"
                ), {"tag": eq_tag}).fetchone()
                if not eq:
                    _send(chat_id, f"❌ No encontré el equipo con tag *{eq_tag}*.")
                    return
                insp = _db.session.execute(_t(
                    "SELECT id, inspection_date FROM thickness_inspections "
                    "WHERE equipment_id = :eid ORDER BY inspection_date DESC, id DESC LIMIT 1"
                ), {"eid": eq[0]}).fetchone()
                if not insp:
                    _send(chat_id, f"❌ No hay inspecciones UT para *{eq_tag}*. Crea primero la inspección desde el CMMS.")
                    return
                _pending_photos[chat_id] = {
                    "entity_type": "thickness_inspection",
                    "entity_id": insp[0],
                    "code": f"UT-{eq_tag}-{insp[1]}",
                }
                _send(chat_id, f"📷 Listo. Envía ahora la(s) foto(s) del formato UT del *{eq_tag}* del *{insp[1]}*.")
        except Exception as e:
            logger.error(f"/ut_foto error: {e}")
            _send(chat_id, f"❌ Error: {e}")
        return

    # Commands
    if text.lower() in ('/start', '/help', 'hola', 'ayuda'):
        _send(chat_id, """*CMMS Pro Bot* 🏭

*Consultas:*
• _Cuantas OTs abiertas hay?_
• _Estado del digestor #1_
• _Que componentes fallan mas?_
• _Puntos de lubricacion vencidos?_
• _Resumen de planta / resumen ejecutivo_
• _Activos rotativos instalados_
• _Items con stock bajo_
• _Que tecnicos tienen mas carga?_
• _Comparar digestor 1 vs 5_
• _Plan de trabajo para esta semana_

*Acciones:*
• _Reportar falla en faja del digestor #2_
• _Cerrar OT-0034, trabajo completado_
• _Iniciar OT-0034_
• _Agregar nota a OT-0034: se cambio faja_
• _Cambiar criticidad del AV-0003 a alta_
• _Corrige la descripcion del AV-0005: ..._
• _Anula el AV-0002, era duplicado_
• _Asigna la OT-0034 a Carlos Luque, 6 horas, 2 tecnicos_
• _La OT-0034 paro la linea 1 hora_
• _Se lubrico chumacera motriz del D8 el 30-marzo, FAPMETAL_
• _Lubrique hoy el punto LUB-D5-CHM-MOT_
• Despues de crear aviso, envia foto

*Inspeccion de Espesores (UT):*
• `/ut_pdf D7 https://drive.google.com/...` — vincular PDF a la ultima inspeccion del equipo
• `/ut_foto D7` — luego envia la(s) foto(s) del formato fisico

*Contratistas y Stock:*
• `/reporte_contratista` — resumen mensual de todos los contratistas
• `/reporte_contratista FAPMETAL` — solo un contratista
• _Items con stock bajo?_ — lista de repuestos bajo minimo

*Recordatorios / Pendientes:*
• `/recordar OT-0034 1m fabricar tripode` — agenda un recordatorio
• `/recordar OT-0050 2026-06-15 recibir entrega` — fecha absoluta
• `/recordatorios` — lista pendientes (vencidos + proximos 7 dias)
• Tambien lenguaje natural: _"recordame en 30 dias inspeccionar D7 (OT-0028)"_

*Analisis:*
• _% correctivo vs preventivo_
• _Que repuestos necesito stockear?_
• _Resumen ejecutivo para gerencia_

*Mensajes de voz:* envia un audio y el bot lo transcribe automaticamente.
*Memoria:* el bot recuerda los ultimos mensajes (10 min). Usa `/reset` para olvidar la conversacion.

*Glosario aprendido (aliases):*
• `/alias FAPMETAL = FAB METAL SAC` — guardar abreviatura/apodo
• `/alias el negro = chumacera oxidada del D8 [apodo]` — con categoria
• `/aliases` — listar todos los aliases
• `/borra_alias FAPMETAL` — eliminar un alias

*RAG (memoria historica):* el bot busca casos similares en OTs y avisos
pasados automaticamente y los usa como referencia. Pregunta cosas como
"¿como se arreglo la ultima vez que paso esto?" o "compara con el TH4".""")
        return

    # Comandos rapidos para limpiar el historial de conversacion
    if (text or '').strip().lower() in ('/reset', '/nuevo', '/olvida'):
        _reset_chat_history(chat_id)
        _send(chat_id, "🧹 Conversacion reiniciada. Empezamos de cero.")
        return

    # ── Comandos del glosario aprendido (B1) ──────────────────────────────
    txt_strip = (text or '').strip()
    if txt_strip.lower().startswith('/alias '):
        _handle_alias_command(app, chat_id, txt_strip)
        return
    if txt_strip.lower() in ('/aliases', '/glosario'):
        _list_aliases_for_chat(app, chat_id)
        return
    if txt_strip.lower().startswith('/borra_alias '):
        _delete_alias_for_chat(app, chat_id, txt_strip)
        return

    # ── Glosario: expandir aliases en el mensaje antes de procesar ────────
    expanded_text, applied = _apply_aliases(app, text, chat_id)
    if applied:
        # Notificar discretamente al usuario que se expandio
        terms_str = ', '.join(f"'{a}' → '{e}'" for a, e in applied)
        _send(chat_id, f"💡 _Aliases aplicados: {terms_str}_")
        text = expanded_text  # usar el texto expandido para el resto del flujo

    # Process
    _send(chat_id, "⏳ Consultando datos...")
    _send_typing(chat_id)  # indicador 'typing...' adicional (Telegram ~5s)
    focus = _get_focused_equipment_context(app, text)
    context = _get_cmms_context(app)
    if focus:
        # Si hay foco, quitar la seccion gigante 'SPECS DE COMPONENTES' del contexto
        # general (la info relevante ya esta en el foco). Asi evitamos timeout/saturacion.
        try:
            import re as _re
            context = _re.sub(
                r'\n=== SPECS DE COMPONENTES ===.*?(?=\n===|\Z)',
                '\n=== SPECS DE COMPONENTES === (ver FOCO arriba)\n',
                context, flags=_re.DOTALL,
            )
        except Exception:
            pass
        context = focus + context

    # ── RAG: casos historicos similares ──────────────────────────────
    # Busqueda semantica sobre OTs cerradas y avisos para que el bot
    # pueda responder con casos reales pasados ("¿como se arreglo la
    # ultima vez que paso esto?")
    rag_context = _build_rag_context(app, text)
    if rag_context:
        context = rag_context + context

    # ── ANALISIS DE ESPESORES (Mejora 2) ─────────────────────────────
    thickness_ctx = _build_thickness_analysis(app, text)
    if thickness_ctx:
        context = thickness_ctx + context

    # ── PROGRAMACION / SCHEDULE (Mejora 3) ───────────────────────────
    schedule_ctx = _build_schedule_context(app, text)
    if schedule_ctx:
        context = schedule_ctx + context

    # Memoria de conversacion: trae los ultimos turnos del chat (TTL 10 min)
    history = _get_chat_history(chat_id)
    answer = _ask_deepseek(text, context, is_action=True, history=history, app=app, chat_id=chat_id)

    # Guardar el turno actual en el historial para futuros mensajes
    _append_chat_history(chat_id, 'user', text)
    # El answer es JSON; guardamos el campo 'reply' si existe, o el JSON crudo si no.
    try:
        _ad = _extract_json(answer)
        if _ad and isinstance(_ad, dict):
            _summary = _ad.get('reply') or f"[accion: {_ad.get('action', 'none')}]"
            _append_chat_history(chat_id, 'assistant', _summary)
    except Exception:
        pass

    # DeepSeek is forced to return JSON via response_format. Parse it.
    action_data = _extract_json(answer)
    if not (action_data and isinstance(action_data, dict)):
        logger.warning(f"Bot: failed to parse JSON from DeepSeek. Raw: {answer[:300]}")
        # Reintento: pide al modelo SOLO un JSON con reply en texto plano
        try:
            retry_prompt = (
                "Tu respuesta anterior no fue JSON valido. Devuelve SOLO un objeto JSON "
                "con la forma {\"action\":\"none\",\"reply\":\"<respuesta natural breve "
                "al mensaje del usuario>\"}. Sin markdown, sin texto adicional."
            )
            retry_history = (history or []) + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": answer[:1000]},
                {"role": "user", "content": retry_prompt},
            ]
            retry_answer = _ask_deepseek(retry_prompt, context, is_action=True, history=retry_history, app=app, chat_id=chat_id)
            action_data = _extract_json(retry_answer)
        except Exception as _re_err:
            logger.warning(f"Bot retry failed: {_re_err}")
            action_data = None

        if not (action_data and isinstance(action_data, dict)):
            # Ultimo recurso: si el texto crudo parece prosa coherente, mostrarlo.
            raw = (answer or '').strip()
            # Quita backticks/markdown
            for token in ('```json', '```'):
                raw = raw.replace(token, '')
            raw = raw.strip()
            if raw and not raw.startswith('{') and len(raw) <= 1500:
                _send(chat_id, raw)
            else:
                _send(chat_id,
                      "⚠️ No logre interpretar tu mensaje. Intenta reformularlo o se mas especifico "
                      "(ej: 'lubricacion de la chumacera motriz del percolador 2 hoy, Marcos Campos').")
            return

    action = action_data.get('action')
    data = action_data.get('data', {})

    # Plain query/response — just show the reply text
    if action == 'none' or not action:
        reply = action_data.get('reply') or "No tengo esa informacion."
        _send(chat_id, reply)
        return

    if action == 'create_notice':
        code, nid, err = _create_notice(app, data)
        if code and nid:
            _pending_photos[chat_id] = {"entity_type": "notice", "entity_id": nid, "code": code}
            # Indexar el aviso para busqueda semantica futura (RAG)
            _index_entity_async(app, 'notice', nid)
            scope = data.get('_resolved_scope', 'PLAN')
            scope_emoji = {'PLAN': '🏭', 'FUERA_PLAN': '🚧', 'GENERAL': '🛠️'}.get(scope, '🏭')
            scope_label = {'PLAN': 'PLAN', 'FUERA_PLAN': 'Fuera de Plan', 'GENERAL': 'General'}.get(scope, scope)

            fm = data.get('failure_mode', '-')
            fc = data.get('failure_category', '-')
            eq = data.get('equipment_tag') or data.get('equipment_name') or ''
            comp = data.get('component_name') or ''
            loc = data.get('free_location') or ''

            if scope == 'PLAN':
                equip_line = f"⚙️ Equipo: {eq}"
                comp_line = f"\n🔧 Componente: {comp}" if comp else ""
            else:
                equip_line = f"📍 Ubicacion: {loc or '(no especificada)'}"
                comp_line = ""

            failure_block = ""
            if scope == 'PLAN' or fm != '-' or fc != '-':
                failure_block = f"\n⚠️ Modo de falla: {fm}\n🏷️ Tipo: {fc}"

            # Fecha del evento: si el extractor envio event_date, mostrar
            # transparentemente "(segun tu mensaje)" para que el usuario detecte
            # cualquier interpretacion erronea.
            resolved_date = data.get('_resolved_event_date') or date.today().isoformat()
            today_str = date.today().isoformat()
            if resolved_date != today_str:
                date_line = f"📅 {resolved_date} _(segun tu mensaje)_"
            else:
                date_line = f"📅 {resolved_date}"

            _send(chat_id, f"""✅ *Aviso creado: {code}*
{scope_emoji} _{scope_label}_

📋 {data.get('description', '-')}
{equip_line}{comp_line}{failure_block}
🔴 Criticidad: {data.get('criticality', 'Media')}
{date_line}

📷 _Envia una foto para adjuntarla._""")
        else:
            _send(chat_id, f"❌ Error creando aviso: {err}")
        return

    elif action == 'close_ot':
        code, err = _close_ot(app, data)
        if code:
            resolved_date = data.get('_resolved_event_date') or date.today().isoformat()
            today_str = date.today().isoformat()
            date_line = f"\n📅 Cerrada: {resolved_date}"
            if resolved_date != today_str:
                date_line += " _(segun tu mensaje)_"
            _send(chat_id, f"✅ *{code} cerrada*{date_line}\n📝 {data.get('comments', '-')}")
            # Indexar la OT cerrada para busqueda semantica futura (RAG)
            try:
                with app.app_context():
                    from database import db as _db
                    from sqlalchemy import text as _sqltext
                    row = _db.session.execute(
                        _sqltext("SELECT id FROM work_orders WHERE code = :c"),
                        {"c": code}
                    ).fetchone()
                    if row:
                        _index_entity_async(app, 'work_order', row[0])
            except Exception:
                pass
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'start_ot':
        code, err = _start_ot(app, data)
        if code:
            _send(chat_id, f"▶️ *{code} iniciada* — En Progreso")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'add_log':
        code, err = _add_log_entry(app, data)
        if code:
            _send(chat_id, f"📝 Nota agregada a *{code}*\n_{data.get('comment', '')}_")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'reschedule_ot':
        code, err = _reschedule_ot(app, data)
        if code:
            _send(chat_id, f"📅 *{code}* reprogramada para *{data.get('new_date', '-')}*")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'edit_notice':
        code, changed, err = _edit_notice(app, data)
        if code:
            fields = data.get('fields') or {}
            lines = '\n'.join(f"• *{k}:* {fields.get(k)}" for k in (changed or []))
            _send(chat_id, f"✏️ *Aviso {code} actualizado*\n{lines}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'promote_notice':
        code, info, err = _promote_notice(app, data)
        if code:
            from_scope, to_scope, n_ots = info
            scope_label = {'PLAN': 'PLAN 🏭', 'FUERA_PLAN': 'Fuera de Plan 🚧', 'GENERAL': 'General 🛠️'}
            arrow = f"{scope_label.get(from_scope, from_scope)} → {scope_label.get(to_scope, to_scope)}"
            extra = ""
            if to_scope == 'PLAN':
                eq = data.get('equipment_tag') or data.get('equipment_name') or '-'
                comp = data.get('component_name')
                extra = f"\n⚙️ Vinculado a: {eq}" + (f" / {comp}" if comp else "")
            if n_ots:
                extra += f"\n📋 OTs propagadas: {n_ots}"
            _send(chat_id, f"🔄 *Aviso {code}*\n{arrow}{extra}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'edit_ot':
        code, changed, err = _edit_ot(app, data)
        if code:
            fields = data.get('fields') or {}
            lines = '\n'.join(f"• *{k}:* {fields.get(k)}" for k in (changed or []))
            _send(chat_id, f"✏️ *OT {code} actualizada*\n{lines}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'register_lubrication_batch':
        result, err = _register_lubrication_batch(app, data)
        if err:
            _send(chat_id, f"❌ {err}")
            return
        ok = result.get('ok', [])
        fail = result.get('fail', [])
        ed = data.get('execution_date') or date.today().isoformat()
        eb = data.get('executed_by') or 'MANTENIMIENTO'
        lines = [f"📦 *Lubricaciones registradas — lote*",
                 f"📅 Fecha: {ed}", f"👤 Por: {eb}", ""]
        if ok:
            lines.append(f"✅ *Exitosas ({len(ok)}):*")
            for code, pname in ok:
                # pname ya es el label jerarquico (ver _format_point_label)
                lines.append(f"  • {pname}")
                lines.append(f"    _cod: {code}_")
        if fail:
            lines.append("")
            lines.append(f"❌ *Fallidas ({len(fail)}):*")
            for label, ferr in fail:
                lines.append(f"  • _{label}_")
                # Si el err ya viene formateado con multilineas (sugerencias),
                # lo indentamos; si no, lo recortamos.
                ferr_clean = (ferr or '').strip()
                if '\n' in ferr_clean:
                    indented = '\n'.join('    ' + l for l in ferr_clean.split('\n'))
                    lines.append(indented)
                else:
                    lines.append(f"    _{ferr_clean[:200]}_")
        _send(chat_id, '\n'.join(lines))
        return

    elif action == 'register_lubrication':
        code, pname, err = _register_lubrication(app, data)
        if code:
            ed = data.get('execution_date') or date.today().isoformat()
            eb = data.get('executed_by') or 'MANTENIMIENTO'
            qty = data.get('quantity_used')
            qty_line = f"\n💧 Cantidad: {qty}" if qty else ""
            extra = ""
            if data.get('leak_detected') or data.get('anomaly_detected'):
                extra = "\n⚠️ Anomalia/fuga reportada — se creo aviso vinculado"
            _send(chat_id, f"✅ *Lubricacion registrada*\n🔧 {pname}\n_cod: {code}_\n📅 Fecha: {ed}\n👤 Por: {eb}{qty_line}{extra}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'edit_lubrication':
        code, pname, err = _edit_lubrication(app, data)
        if code:
            fields = data.get('fields') or {}
            lines = '\n'.join(f"• *{k}:* {v}" for k, v in fields.items())
            _send(chat_id, f"✏️ *Lubricacion corregida*\n🔧 {code} — {pname}\n{lines}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'delete_lubrication':
        code, pname, err = _delete_lubrication(app, data)
        if code:
            _send(chat_id, f"🗑️ *Ejecucion eliminada*\n🔧 {code} — {pname}\n_(semaforo del punto recalculado)_")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'replicate_specs':
        summary, err = _replicate_specs(app, data)
        if summary:
            mode = (data.get('mode') or 'merge').lower()
            mode_label = '🔄 Reemplazo' if mode == 'replace' else '➕ Merge'
            _send(chat_id, f"✅ *Specs replicadas* ({mode_label})\n{summary}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'register_inspection':
        rcode, rname, notice_code, err = _register_inspection(app, data)
        if rcode:
            ed = data.get('execution_date') or date.today().isoformat()
            today_str = date.today().isoformat()
            date_line = f"📅 Fecha: {ed}"
            if ed != today_str:
                date_line += " _(segun tu mensaje)_"
            eb = data.get('executed_by') or 'INSPECTOR'
            findings = int(data.get('findings_count') or 0)
            ovr = (data.get('overall_result') or '').upper() or ('CON_HALLAZGOS' if findings > 0 else 'OK')
            result_emoji = '✅' if ovr == 'OK' else '⚠️'
            extra = ""
            if findings > 0:
                extra = f"\n🔎 Hallazgos: {findings}"
                if notice_code:
                    extra += f"\n🔔 Aviso vinculado: *{notice_code}*"
            _send(chat_id, f"{result_emoji} *Inspeccion registrada*\n📋 Ruta: {rcode} — {rname}\n{date_line}\n👤 Por: {eb}\n📊 Resultado: {ovr}{extra}")
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'change_hammer_batch':
        info, err = _change_hammer_batch(app, data)
        if info:
            mill_num = info['mill'][-1]
            lub_line = "\n🛢️ Lubricacion chumaceras: realizada" if info.get('lubrication_done') else ""
            dur_line = f"\n⏱️ Duracion: {info['duration_h']}h" if info.get('duration_h') is not None else ""
            _send(chat_id,
                f"✅ *Cambio de martillos registrado*\n"
                f"🏭 Molino #{mill_num} · 📅 {info['event_date']}\n"
                f"📤 Saliente: *{info['batch_out_code']}* → FAPMETAL\n"
                f"📥 Entrante: *{info['batch_in_code']}* (rellenado #{info['batch_in_refill_count']})\n"
                f"🔨 Martillos: {info['hammers_changed']}"
                f"{lub_line}{dur_line}\n"
                f"📋 OT generada: *{info['ot_code']}*"
            )
        else:
            _send(chat_id, f"❌ {err}")
        return

    elif action == 'receive_hammer_batch':
        info, err = _receive_hammer_batch(app, data)
        if info:
            _send(chat_id,
                f"✅ *Lote rellenado recibido de FAPMETAL*\n"
                f"📦 Lote: *{info['code']}*\n"
                f"📅 Fecha: {info['event_date']}\n"
                f"🔁 Rellenados acumulados: {info['refill_count']}\n"
                f"Estado: RELLENADO_EN_STOCK (listo para proximo cambio)"
            )
        else:
            _send(chat_id, f"❌ {err}")
        return

    # Unknown action — fall back to reply field if present
    reply = action_data.get('reply') or f"⚠️ Accion desconocida: {action}"
    _send(chat_id, reply)


# ── Bot Startup ──────────────────────────────────────────────────────────────

def start_telegram_bot(app):
    if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
        logger.info("Telegram bot not started: TELEGRAM_TOKEN or DEEPSEEK_API_KEY not set.")
        return

    def poll():
        logger.info("Telegram bot started. Polling for messages...")
        offset = 0
        while True:
            try:
                result = _tg_api('getUpdates', offset=offset, timeout=20)
                if result.get('ok') and result.get('result'):
                    for update in result['result']:
                        update_id = update['update_id']
                        offset = update_id + 1
                        # Idempotencia: si ya procesamos este update, saltarlo
                        # (evita duplicados cuando hay 2 instancias del bot).
                        # Pasamos `app` para que coordine via DB entre procesos.
                        if _seen_update(update_id, app=app):
                            logger.info(f"Skipping duplicate update_id {update_id}")
                            continue
                        msg = update.get('message', {})
                        chat_id = msg.get('chat', {}).get('id')
                        txt = msg.get('text', '')
                        photos = msg.get('photo')
                        caption = msg.get('caption', '')
                        voice = msg.get('voice') or msg.get('audio')
                        # Mensaje de voz: transcribir y procesar como texto
                        if chat_id and voice and not (txt or photos):
                            try:
                                file_id = voice.get('file_id')
                                if not OPENAI_API_KEY:
                                    _send(chat_id, "🎤 Mensaje de voz recibido pero la transcripcion no esta configurada. "
                                                   "Pide al admin que setee OPENAI_API_KEY.")
                                else:
                                    _send(chat_id, "🎤 Transcribiendo mensaje de voz...")
                                    transcribed = _transcribe_voice(file_id, app=app, chat_id=chat_id)
                                    if not transcribed:
                                        _send(chat_id, "❌ No pude transcribir el audio. Intenta de nuevo o escribelo.")
                                    else:
                                        _send(chat_id, f"📝 _Transcripcion:_ {transcribed}")
                                        _process_message(app, chat_id, transcribed, photos=None)
                            except Exception as e:
                                logger.error(f"Bot voice error: {e}")
                                _send(chat_id, f"Error procesando voz: {e}")
                        elif chat_id and (txt or photos):
                            try:
                                _process_message(app, chat_id, txt or caption, photos=[photos] if photos else None)
                            except Exception as e:
                                logger.error(f"Bot message error: {e}")
                                _send(chat_id, f"Error: {e}")
            except Exception as e:
                logger.error(f"Bot poll error: {e}")
                time.sleep(5)
            time.sleep(POLL_INTERVAL)

    def daily_alerts():
        """Run daily summary at 7:00 AM, weekly report on Mondays."""
        logger.info("Daily alerts thread started.")
        last_sent = None
        last_weekly = None
        while True:
            now = datetime.now()
            today_key = now.strftime('%Y-%m-%d')
            if now.hour == 7 and now.minute < 5 and last_sent != today_key:
                try:
                    _generate_daily_summary(app)
                    _check_recurring_alerts(app)
                    # Weekly report on Mondays
                    if now.weekday() == 0 and last_weekly != today_key:
                        _generate_weekly_report(app)
                        last_weekly = today_key
                    # Purga de update_ids viejos para que la tabla no crezca.
                    _cleanup_processed_updates(app, days=2)
                    last_sent = today_key
                    logger.info("Daily summary sent.")
                except Exception as e:
                    logger.error(f"Daily alert error: {e}")
            time.sleep(60)

    def refresh_context_loop():
        """Pre-calcula el contexto general cada 60s (Opt #3)."""
        global _cached_cmms_context, _cached_cmms_context_ts
        logger.info("Context pre-cache thread started (TTL 60s).")
        while True:
            try:
                ctx = _build_cmms_context_real(app)
                _cached_cmms_context = ctx
                _cached_cmms_context_ts = time.time()
            except Exception as e:
                logger.warning(f"Context refresh fallo: {e}")
            time.sleep(_CACHE_CONTEXT_TTL)

    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=daily_alerts, daemon=True).start()
    threading.Thread(target=refresh_context_loop, daemon=True).start()
    logger.info("Telegram bot + daily alerts + context cache started.")
