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

# Authorized chat_ids — only these can use the bot
OWNER_CHAT_ID = 1853592586
_allowed_chats = {OWNER_CHAT_ID}

# Store admin chat_ids for daily alerts
_admin_chats = set()

# Idempotencia: evita procesar el mismo update_id de Telegram dos veces.
# Caso comun: durante un re-deploy en Render, dos instancias del bot pueden
# polear Telegram a la vez y procesar el mismo mensaje, generando respuestas
# duplicadas (a veces con redaccion ligeramente distinta porque DeepSeek se
# ejecuta dos veces).
_processed_updates = collections.deque(maxlen=500)
_processed_lock = threading.Lock()


def _seen_update(update_id):
    """Devuelve True si ya procesamos este update_id antes (y lo marca si no)."""
    if update_id is None:
        return False
    with _processed_lock:
        if update_id in _processed_updates:
            return True
        _processed_updates.append(update_id)
        return False


def _send_typing(chat_id):
    """Envia el indicador 'typing...' a Telegram. Dura ~5s en el cliente."""
    try:
        _tg_api('sendChatAction', chat_id=chat_id, action='typing')
    except Exception:
        pass


# Memoria de conversacion: por chat_id guarda los ultimos N mensajes
# (user/assistant) para que el bot tenga contexto entre mensajes.
# Estructura: {chat_id: {'msgs': [...], 'last_ts': float}}
# TTL: si pasaron mas de _CHAT_HISTORY_TTL segundos sin actividad, se descarta.
_chat_history = {}
_CHAT_HISTORY_MAX = 6        # ultimas 6 entradas (3 turnos user+assistant)
_CHAT_HISTORY_TTL = 600      # 10 minutos sin actividad -> reinicia contexto


def _get_chat_history(chat_id):
    """Devuelve la lista de mensajes previos validos para el chat."""
    entry = _chat_history.get(chat_id)
    if not entry:
        return []
    if time.time() - entry.get('last_ts', 0) > _CHAT_HISTORY_TTL:
        _chat_history.pop(chat_id, None)
        return []
    return list(entry.get('msgs', []))


def _append_chat_history(chat_id, role, content):
    """Agrega un mensaje (user/assistant) al historial del chat. Mantiene sliding window."""
    if not chat_id or not content:
        return
    entry = _chat_history.setdefault(chat_id, {'msgs': [], 'last_ts': 0})
    entry['msgs'].append({'role': role, 'content': str(content)[:1500]})
    if len(entry['msgs']) > _CHAT_HISTORY_MAX:
        entry['msgs'] = entry['msgs'][-_CHAT_HISTORY_MAX:]
    entry['last_ts'] = time.time()


def _reset_chat_history(chat_id):
    _chat_history.pop(chat_id, None)


def _tg_api(method, **kwargs):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}'
    r = requests.post(url, json=kwargs, timeout=30)
    return r.json()


def _send(chat_id, text):
    for i in range(0, len(text), 4000):
        _tg_api('sendMessage', chat_id=chat_id, text=text[i:i+4000], parse_mode='Markdown')


# ── Data Context ─────────────────────────────────────────────────────────────

def _get_focused_equipment_context(app, message):
    """Si el mensaje menciona un equipo (tag o nombre), devuelve su info completa.

    Esto se inyecta al inicio del contexto para que el LLM no tenga que buscar.
    """
    import re
    msg_upper = (message or '').upper()
    if not msg_upper:
        return ''

    # Normalizar: quitar '#' y colapsar espacios para hacer match flexible.
    # Asi "Digestor 2", "Digestor #2", "DIGESTOR  #  2" matchean todos contra "DIGESTOR #2".
    def _norm(s):
        return re.sub(r'\s+', ' ', (s or '').upper().replace('#', '').replace('.', '')).strip()
    msg_norm = _norm(msg_upper)

    # Extraer patrones tipo "DIGESTOR 2" -> inferir tag "D2"; "TRANSPORTADOR 5" -> "TH5"
    inferred_tags = set()
    for kw, prefix in (('DIGESTOR', 'D'), ('TRANSPORTADOR', 'TH'), ('SECADOR', 'SEC'),
                       ('MOLINO', 'MOLI'), ('HIDROLAVADORA', 'H'), ('TRITURADOR', 'TRI'),
                       ('PERCOLADOR', 'PER'), ('VAHO', 'VAHO')):
        for m in re.finditer(kw + r'\s*#?\s*(\d+)', msg_norm):
            inferred_tags.add(prefix + m.group(1))

    lines = []
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            # Buscar todos los equipos para hacer match
            equips = _db.session.execute(text(
                "SELECT id, tag, name FROM equipments"
            )).fetchall()
            matched_ids = set()
            for e in equips:
                eq_tag = (e[1] or '').upper()
                eq_name = (e[2] or '').upper()
                eq_tag_norm = _norm(eq_tag)
                eq_name_norm = _norm(eq_name)
                # Match por tag completo (SEC2-TH10, D2, etc) normalizado
                if eq_tag_norm and re.search(r'\b' + re.escape(eq_tag_norm) + r'\b', msg_norm):
                    matched_ids.add(e[0])
                    continue
                # Match por tag inferido ("Digestor 2" -> "D2")
                # Tolera tags compuestos tipo 'MOLI2-LINE1' cuando se infiere 'MOLI2'.
                if eq_tag_norm:
                    inf_match = any(
                        (inf == eq_tag_norm or eq_tag_norm.startswith(inf + '-'))
                        for inf in inferred_tags
                    )
                    if inf_match:
                        matched_ids.add(e[0])
                        continue
                # Match por nombre completo normalizado
                if eq_name_norm and re.search(r'\b' + re.escape(eq_name_norm) + r'\b', msg_norm):
                    matched_ids.add(e[0])

            # Si no encontramos equipo por tag/nombre, el usuario pudo mencionar
            # un COMPONENTE (ej: 'bomba de lodos', 'motor electrico del D5').
            # Buscamos componentes por nombre y tomamos su equipo padre.
            if not matched_ids:
                try:
                    comp_rows = _db.session.execute(text(
                        "SELECT c.name, s.equipment_id FROM components c "
                        "JOIN systems s ON c.system_id = s.id"
                    )).fetchall()
                    # Orden descendente por longitud para priorizar matches largos
                    # (ej: 'BOMBA DE LODOS' antes que 'BOMBA')
                    for c in sorted(comp_rows, key=lambda x: -len(x[0] or '')):
                        cname = _norm(c[0] or '')
                        if cname and len(cname) >= 5 and re.search(
                            r'\b' + re.escape(cname) + r'\b', msg_norm
                        ):
                            matched_ids.add(c[1])
                except Exception:
                    pass

            # Tambien probar por CODIGO de activo rotativo mencionado (ej: MR-0048)
            if not matched_ids:
                try:
                    ra_rows = _db.session.execute(text(
                        "SELECT code, name, component_id FROM rotative_assets "
                        "WHERE status = 'Instalado'"
                    )).fetchall()
                    for ra in ra_rows:
                        rac = _norm(ra[0] or '')
                        ran = _norm(ra[1] or '')
                        if rac and re.search(r'\b' + re.escape(rac) + r'\b', msg_norm):
                            # Buscar equipment_id a partir del component_id
                            if ra[2]:
                                eq_row = _db.session.execute(text(
                                    "SELECT s.equipment_id FROM systems s "
                                    "JOIN components c ON c.system_id = s.id "
                                    "WHERE c.id = :cid"
                                ), {"cid": ra[2]}).fetchone()
                                if eq_row:
                                    matched_ids.add(eq_row[0])
                        elif ran and len(ran) >= 8 and re.search(
                            r'\b' + re.escape(ran) + r'\b', msg_norm
                        ):
                            if ra[2]:
                                eq_row = _db.session.execute(text(
                                    "SELECT s.equipment_id FROM systems s "
                                    "JOIN components c ON c.system_id = s.id "
                                    "WHERE c.id = :cid"
                                ), {"cid": ra[2]}).fetchone()
                                if eq_row:
                                    matched_ids.add(eq_row[0])
                except Exception:
                    pass

            if not matched_ids:
                return ''

            # ── DESAMBIGUACION: si hay multiples equipos del mismo nombre,
            # filtrar por LINEA o AREA mencionada en el mensaje, y priorizar
            # los que TIENEN component_specs (mas utiles para responder).
            if len(matched_ids) > 3:
                lines_db = _db.session.execute(text("SELECT id, name, area_id FROM lines")).fetchall()
                areas_db = _db.session.execute(text("SELECT id, name FROM areas")).fetchall()
                line_hits = set()
                for l in lines_db:
                    ln = _norm(l[1] or '')
                    if ln and re.search(r'\b' + re.escape(ln) + r'\b', msg_norm):
                        line_hits.add(l[0])
                area_hits = set()
                for a in areas_db:
                    an = _norm(a[1] or '')
                    if an and re.search(r'\b' + re.escape(an) + r'\b', msg_norm):
                        area_hits.add(a[0])
                if line_hits or area_hits:
                    eqs_full = _db.session.execute(text(
                        "SELECT e.id, e.line_id, l.area_id FROM equipments e "
                        "LEFT JOIN lines l ON e.line_id = l.id WHERE e.id = ANY(:ids)"
                    ), {"ids": list(matched_ids)}).fetchall()
                    filtered = set()
                    for ef in eqs_full:
                        if line_hits and ef[1] in line_hits:
                            filtered.add(ef[0])
                        elif area_hits and ef[2] in area_hits:
                            filtered.add(ef[0])
                    if filtered:
                        matched_ids = filtered

            # Si todavia hay muchos, priorizar los que tienen specs cargadas
            if len(matched_ids) > 3:
                with_specs = _db.session.execute(text(
                    "SELECT DISTINCT s.equipment_id FROM systems s "
                    "JOIN components c ON c.system_id = s.id "
                    "JOIN component_specs cs ON cs.component_id = c.id "
                    "WHERE s.equipment_id = ANY(:ids)"
                ), {"ids": list(matched_ids)}).fetchall()
                ws_ids = {r[0] for r in with_specs}
                if ws_ids:
                    matched_ids = ws_ids

            matched_list = list(matched_ids)[:3]  # max 3 equipos para no saturar

            # ── BULK QUERIES (evitar N+1 que cuelga el bot) ──────────────────
            # 1) Equipos
            eqs_rows = _db.session.execute(text(
                "SELECT e.id, e.tag, e.name, l.name AS line_name, a.name AS area_name "
                "FROM equipments e LEFT JOIN lines l ON e.line_id = l.id "
                "LEFT JOIN areas a ON l.area_id = a.id WHERE e.id = ANY(:ids)"
            ), {"ids": matched_list}).fetchall()
            # 2) Specs de equipos
            espec_rows = _db.session.execute(text(
                "SELECT equipment_id, key_name, value_text, unit FROM equipment_specs "
                "WHERE equipment_id = ANY(:ids) ORDER BY equipment_id, order_index"
            ), {"ids": matched_list}).fetchall()
            espec_by_eq = {}
            for r in espec_rows:
                espec_by_eq.setdefault(r[0], []).append((r[1], r[2], r[3]))
            # 3) Sistemas y componentes
            syscomp_rows = _db.session.execute(text(
                "SELECT s.equipment_id, s.name AS sys_name, c.id AS comp_id, c.name AS comp_name "
                "FROM systems s LEFT JOIN components c ON c.system_id = s.id "
                "WHERE s.equipment_id = ANY(:ids) ORDER BY s.equipment_id, s.name, c.name"
            ), {"ids": matched_list}).fetchall()
            comp_ids = [r[2] for r in syscomp_rows if r[2]]
            # 4) Specs de componentes en bulk
            cspec_by_comp = {}
            if comp_ids:
                cspec_rows = _db.session.execute(text(
                    "SELECT component_id, key_name, value_text, unit FROM component_specs "
                    "WHERE component_id = ANY(:cids) ORDER BY component_id, order_index"
                ), {"cids": comp_ids}).fetchall()
                for r in cspec_rows:
                    cspec_by_comp.setdefault(r[0], []).append((r[1], r[2], r[3]))

            # 5) Activos rotativos INSTALADOS en cualquiera de esos componentes
            # (motores, bombas, cajas reductoras, etc. con su marca/modelo/BOM)
            ra_by_comp = {}
            ra_specs_by_id = {}
            ra_bom_by_id = {}
            if comp_ids:
                ra_rows = _db.session.execute(text(
                    "SELECT id, code, name, brand, model, category, component_id "
                    "FROM rotative_assets "
                    "WHERE component_id = ANY(:cids) AND status = 'Instalado'"
                ), {"cids": comp_ids}).fetchall()
                asset_ids = []
                for ra in ra_rows:
                    ra_by_comp.setdefault(ra[6], []).append(ra)
                    asset_ids.append(ra[0])
                # 5a) Specs de esos activos rotativos
                if asset_ids:
                    ras_rows = _db.session.execute(text(
                        "SELECT asset_id, key_name, value_text, unit "
                        "FROM rotative_asset_specs "
                        "WHERE asset_id = ANY(:aids) AND is_active = TRUE "
                        "ORDER BY asset_id, order_index"
                    ), {"aids": asset_ids}).fetchall()
                    for r in ras_rows:
                        ra_specs_by_id.setdefault(r[0], []).append((r[1], r[2], r[3]))
                    # 5b) BOM (repuestos: rodamientos, retenes, etc.)
                    bom_rows = _db.session.execute(text(
                        "SELECT rab.asset_id, rab.category, rab.quantity, rab.notes, "
                        "       COALESCE(wi.code, '-') AS item_code, "
                        "       COALESCE(wi.name, rab.free_text, '-') AS item_name, "
                        "       COALESCE(wi.brand, '') AS item_brand, "
                        "       COALESCE(wi.manufacturer_code, '') AS mfr_code "
                        "FROM rotative_asset_bom rab "
                        "LEFT JOIN warehouse_items wi ON rab.warehouse_item_id = wi.id "
                        "WHERE rab.asset_id = ANY(:aids)"
                    ), {"aids": asset_ids}).fetchall()
                    for r in bom_rows:
                        ra_bom_by_id.setdefault(r[0], []).append({
                            'category': r[1], 'qty': r[2], 'notes': r[3],
                            'code': r[4], 'name': r[5], 'brand': r[6],
                            'mfr_code': r[7],
                        })

            # Indexar syscomp por equipo
            syscomp_by_eq = {}
            for r in syscomp_rows:
                syscomp_by_eq.setdefault(r[0], []).append((r[1], r[2], r[3]))

            # ── Render ──
            for eq in eqs_rows:
                lines.append(f"\n>>> EQUIPO ENCONTRADO: [{eq[1]}] {eq[2]}")
                lines.append(f"    Linea: {eq[3]} | Area: {eq[4]}")
                espec_list = espec_by_eq.get(eq[0], [])
                if espec_list:
                    lines.append(f"    SPECS DEL EQUIPO:")
                    for k, v, u in espec_list:
                        lines.append(f"      - {k}: {v} {u or ''}")
                cur_sys = None
                for sys_name, comp_id, comp_name in syscomp_by_eq.get(eq[0], []):
                    if sys_name != cur_sys:
                        lines.append(f"    SISTEMA: {sys_name}")
                        cur_sys = sys_name
                    if comp_id:
                        lines.append(f"      COMPONENTE: {comp_name}")
                        cs_list = cspec_by_comp.get(comp_id, [])
                        if cs_list:
                            for k, v, u in cs_list:
                                lines.append(f"        * {k}: {v} {u or ''}")
                        # Activos rotativos instalados en este componente
                        ras_here = ra_by_comp.get(comp_id, [])
                        for ra in ras_here:
                            ra_id, ra_code, ra_name, ra_brand, ra_model, ra_cat, _ = ra
                            lines.append(f"        >> ACTIVO ROTATIVO INSTALADO: {ra_code} {ra_name}")
                            meta_bits = []
                            if ra_brand: meta_bits.append(f"Marca: {ra_brand}")
                            if ra_model: meta_bits.append(f"Modelo: {ra_model}")
                            if ra_cat:   meta_bits.append(f"Categoria: {ra_cat}")
                            if meta_bits:
                                lines.append(f"           " + ' | '.join(meta_bits))
                            for k, v, u in ra_specs_by_id.get(ra_id, []):
                                lines.append(f"           · SPEC {k}: {v} {u or ''}")
                            boms = ra_bom_by_id.get(ra_id, [])
                            if boms:
                                lines.append(f"           REPUESTOS/BOM del activo (rodamientos, retenes, fajas, etc):")
                                for b in boms:
                                    note = f" [{b['notes']}]" if b.get('notes') else ''
                                    brand = f" {b['brand']}" if b.get('brand') else ''
                                    mfr = f" (parte: {b['mfr_code']})" if b.get('mfr_code') else ''
                                    qty = b.get('qty') or ''
                                    cat = b.get('category') or ''
                                    lines.append(
                                        f"             • {b.get('code', '-')} {b.get('name', '-')}{brand}{mfr}"
                                        f" — x{qty} {cat}{note}"
                                    )
                        if not cs_list and not ras_here:
                            lines.append(f"        * SPEC_FALTANTE: ficha tecnica no cargada")
        except Exception as e:
            logger.warning(f"_get_focused_equipment_context error: {e}")
            return ''
    if not lines:
        return ''
    header = (
        "=== FOCO DE CONSULTA — DATOS DETALLADOS DEL EQUIPO MENCIONADO ===\n"
        "INSTRUCCION CRITICA PARA EL ASISTENTE:\n"
        "  Las lineas '*' bajo cada COMPONENTE son las ESPECIFICACIONES TECNICAS del\n"
        "  componente (modelo, marca, codigo, dimensiones). Si el usuario pregunta por\n"
        "  specs/modelo/marca/codigo/parte/dimensiones, responde EXACTAMENTE con esos\n"
        "  pares clave=valor. NO digas 'no hay especificaciones' si abajo hay lineas '*'.\n"
        "  Ejemplo: '* CHUMACERA: UCF315-300D1' significa chumacera modelo UCF315-300D1.\n"
        "  '* SPEC_FALTANTE' significa que NO se cargo la ficha del componente.\n"
        "\n"
        "  Las lineas '>> ACTIVO ROTATIVO INSTALADO' son el activo rotativo real montado\n"
        "  en ese componente (bomba centrifuga, motor electrico, caja reductora, etc).\n"
        "  Las lineas '· SPEC' bajo el activo son sus especificaciones (HP, RPM, etc).\n"
        "  Las lineas 'REPUESTOS/BOM' listan los repuestos del activo rotativo:\n"
        "  RODAMIENTOS, RETENES, FAJAS, ACOPLES, etc. con su codigo de almacen,\n"
        "  marca y numero de parte del fabricante.\n"
        "  Si el usuario pregunta '¿que rodamiento usa la bomba X?', '¿que repuestos\n"
        "  lleva?', '¿codigo de parte del reten?', responde con los items del BOM del\n"
        "  activo instalado en ese componente.\n"
        "  IMPORTANTE: CHUAMCERA = CHUMACERA (tolera errores de tipeo en los datos).\n"
    )
    return header + "\n".join(lines) + "\n\n"


# ── Pre-calculo del contexto general (Opt #3) ────────────────────────────
# El contexto general (conteos, listado de equipos/tecnicos/fallas, etc)
# cambia lentamente. Lo pre-calculamos cada 60s en un thread de background
# para no repetir ~15 queries a Supabase en cada mensaje al bot.
_cached_cmms_context = ''
_cached_cmms_context_ts = 0.0
_CACHE_CONTEXT_TTL = 60  # segundos entre refrescos


def _get_cmms_context(app):
    """Devuelve el contexto general. Usa cache si esta disponible.

    - Si el cache esta frio (aun sin inicializar), construye una vez on-demand.
    - Si el cache esta caliente, devuelve la version pre-calculada (0ms).
    - El refresh ocurre en un thread separado lanzado por start_bot().
    """
    global _cached_cmms_context
    # Fallback: durante los primeros segundos del bot, cache puede estar vacio
    if not _cached_cmms_context:
        try:
            _cached_cmms_context = _build_cmms_context_real(app)
        except Exception as e:
            logger.warning(f"_get_cmms_context first-build fallo: {e}")
            return ''
    return _cached_cmms_context


def _build_cmms_context_real(app):
    ctx = []
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            # Summary
            wo_total = _db.session.execute(text("SELECT count(*) FROM work_orders")).scalar()
            wo_open = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status != 'Cerrada'")).scalar()
            wo_closed = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'Cerrada'")).scalar()
            wo_progress = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'En Progreso'")).scalar()
            wo_prog = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'Programada'")).scalar()
            # Counts by scope (so the bot can answer accurately)
            n_total = _db.session.execute(text("SELECT count(*) FROM maintenance_notices")).scalar()
            n_pending = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE status = 'Pendiente'")).scalar()
            try:
                n_plan = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE scope = 'PLAN'")).scalar() or 0
                n_fuera = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE scope = 'FUERA_PLAN'")).scalar() or 0
                n_general = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE scope = 'GENERAL'")).scalar() or 0
            except Exception:
                n_plan = n_fuera = n_general = 0

            ctx.append("=== RESUMEN CMMS ===")
            ctx.append(f"OTs totales: {wo_total} | Abiertas: {wo_open} | En Progreso: {wo_progress} | Programadas: {wo_prog} | Cerradas: {wo_closed}")
            ctx.append(f"Avisos totales: {n_total} | Pendientes: {n_pending} | PLAN: {n_plan} | FUERA_PLAN: {n_fuera} | GENERAL: {n_general}")

            # Areas + Lines
            areas = _db.session.execute(text("SELECT id, name FROM areas ORDER BY name")).fetchall()
            lines = _db.session.execute(text("SELECT id, name, area_id FROM lines ORDER BY name")).fetchall()
            ctx.append(f"\n=== AREAS ({len(areas)}) ===")
            for a in areas:
                al = ', '.join(l[1] for l in lines if l[2] == a[0])
                ctx.append(f"  {a[1]} (id:{a[0]}) — Lineas: {al or 'ninguna'}")

            # Equipment
            equips = _db.session.execute(text("""
                SELECT e.id, e.name, e.tag, e.criticality, l.name FROM equipments e
                LEFT JOIN lines l ON e.line_id = l.id ORDER BY l.name, e.name
            """)).fetchall()
            ctx.append(f"\n=== EQUIPOS ({len(equips)}) ===")
            for e in equips:
                ctx.append(f"  {e[1]} [{e[2]}] | Crit: {e[3] or '-'} | Linea: {e[4] or '-'} | id:{e[0]}")

            # Work Orders (last 50)
            ots = _db.session.execute(text("""
                SELECT w.id, w.code, w.maintenance_type, w.status, w.description,
                       w.scheduled_date, w.failure_mode, w.real_start_date, w.real_end_date,
                       e.name, e.tag, c.name, s.name, l.name, w.notice_id,
                       t.name as tech_name, w.technician_id
                FROM work_orders w
                LEFT JOIN equipments e ON w.equipment_id = e.id
                LEFT JOIN components c ON w.component_id = c.id
                LEFT JOIN systems s ON w.system_id = s.id
                LEFT JOIN lines l ON w.line_id = l.id
                LEFT JOIN technicians t ON CAST(w.technician_id AS INTEGER) = t.id
                ORDER BY w.id DESC LIMIT 50
            """)).fetchall()
            ctx.append(f"\n=== ULTIMAS {len(ots)} OTs ===")
            for o in ots:
                eq = f"{o[10] or ''} {o[9] or '-'}".strip()
                tech = o[15] or '-'
                ctx.append(f"  {o[1]} | {o[2] or '-'} | {o[3]} | {eq} | {o[12] or ''}/{o[11] or ''} | {o[4] or '-'} | Falla: {o[6] or '-'} | Tec: {tech} | Prog: {o[5] or '-'} | id:{o[0]}")

            # Notices (last 30) — include scope and free_location for FUERA_PLAN/GENERAL
            try:
                notices = _db.session.execute(text("""
                    SELECT n.id, n.code, n.status, n.description, n.criticality, n.priority,
                           n.request_date, n.maintenance_type, n.reporter_name,
                           e.name, e.tag, l.name, c.name, n.scope, n.free_location
                    FROM maintenance_notices n
                    LEFT JOIN equipments e ON n.equipment_id = e.id
                    LEFT JOIN lines l ON n.line_id = l.id
                    LEFT JOIN components c ON n.component_id = c.id
                    ORDER BY n.id DESC LIMIT 30
                """)).fetchall()
            except Exception:
                notices = _db.session.execute(text("""
                    SELECT n.id, n.code, n.status, n.description, n.criticality, n.priority,
                           n.request_date, n.maintenance_type, n.reporter_name,
                           e.name, e.tag, l.name, c.name
                    FROM maintenance_notices n
                    LEFT JOIN equipments e ON n.equipment_id = e.id
                    LEFT JOIN lines l ON n.line_id = l.id
                    LEFT JOIN components c ON n.component_id = c.id
                    ORDER BY n.id DESC LIMIT 30
                """)).fetchall()
            ctx.append(f"\n=== ULTIMOS {len(notices)} AVISOS ===")
            for n in notices:
                scope = n[13] if len(n) > 13 else 'PLAN'
                if scope == 'PLAN':
                    eq = f"{n[10] or ''} {n[9] or '-'}".strip()
                    where = f"{eq} | {n[12] or '-'}"
                else:
                    floc = (n[14] if len(n) > 14 else None) or '(sin ubicacion)'
                    where = f"{scope}: {floc}"
                ctx.append(f"  {n[1]} | {n[2]} | {where} | {n[3] or '-'} | Crit: {n[4] or '-'} | id:{n[0]}")

            # Rotative Assets — with id, equipment + component link
            assets = _db.session.execute(text("""
                SELECT ra.id, ra.code, ra.name, ra.category, ra.brand, ra.model, ra.status,
                       e.tag, e.name, c.id, c.name
                FROM rotative_assets ra
                LEFT JOIN equipments e ON ra.equipment_id = e.id
                LEFT JOIN components c ON ra.component_id = c.id
                WHERE ra.is_active = true ORDER BY e.tag, ra.code
            """)).fetchall()
            if assets:
                ctx.append(f"\n=== ACTIVOS ROTATIVOS ({len(assets)}) ===")
                for a in assets:
                    eq = f"[{a[7] or '-'}] {a[8] or '-'}"
                    comp = f"comp_id:{a[9]} {a[10]}" if a[9] else "(sin componente)"
                    ctx.append(f"  asset_id:{a[0]} {a[1] or '-'} {a[2]} | {a[3] or '-'} | {a[4] or ''} {a[5] or ''} | {a[6]} | {eq} | {comp}")

            # Overdue points
            try:
                lub = _db.session.execute(text("SELECT count(*) FROM lubrication_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                insp = _db.session.execute(text("SELECT count(*) FROM inspection_routes WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                mon = _db.session.execute(text("SELECT count(*) FROM monitoring_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                ctx.append(f"\n=== PUNTOS VENCIDOS (ROJO) === Lub: {lub} | Insp: {insp} | Mon: {mon}")
            except Exception:
                pass

            # Lubrication points (active) — needed for register_lubrication action
            try:
                lub_points = _db.session.execute(text("""
                    SELECT lp.id, lp.code, lp.name, lp.lubricant_name, lp.quantity_nominal, lp.quantity_unit,
                           lp.frequency_days, lp.last_service_date, lp.next_due_date, lp.semaphore_status,
                           e.tag, e.name, l.name
                    FROM lubrication_points lp
                    LEFT JOIN equipments e ON lp.equipment_id = e.id
                    LEFT JOIN lines l ON lp.line_id = l.id
                    WHERE lp.is_active = true
                    ORDER BY l.name, e.tag, lp.name
                """)).fetchall()
                if lub_points:
                    ctx.append(f"\n=== PUNTOS DE LUBRICACION ({len(lub_points)}) ===")
                    for p in lub_points:
                        eq = f"[{p[10] or '-'}] {p[11] or '-'}"
                        qty = f"{p[4] or '-'} {p[5] or ''}".strip()
                        ctx.append(f"  id:{p[0]} | {p[1] or '-'} | {p[2]} | {eq} | {p[12] or '-'} | Lub:{p[3] or '-'} {qty} | cada {p[6]}d | Ult:{p[7] or '-'} | Prox:{p[8] or '-'} | {p[9]}")
            except Exception as e:
                ctx.append(f"(error puntos lubricacion: {e})")

            # Inspection routes (active)
            try:
                insp_routes = _db.session.execute(text("""
                    SELECT ir.id, ir.code, ir.name, ir.frequency_days, ir.last_execution_date,
                           ir.next_due_date, ir.semaphore_status, e.tag, e.name, l.name
                    FROM inspection_routes ir
                    LEFT JOIN equipments e ON ir.equipment_id = e.id
                    LEFT JOIN lines l ON ir.line_id = l.id
                    WHERE ir.is_active = true
                    ORDER BY l.name, e.tag, ir.name
                """)).fetchall()
                if insp_routes:
                    ctx.append(f"\n=== RUTAS DE INSPECCION ({len(insp_routes)}) ===")
                    for r in insp_routes:
                        eq = f"[{r[7] or '-'}] {r[8] or '-'}"
                        ctx.append(f"  id:{r[0]} | {r[1] or '-'} | {r[2]} | {eq} | {r[9] or '-'} | cada {r[3]}d | Ult:{r[4] or '-'} | Prox:{r[5] or '-'} | {r[6]}")
            except Exception:
                pass

            # Monitoring points (active)
            try:
                mon_points = _db.session.execute(text("""
                    SELECT mp.id, mp.code, mp.name, mp.frequency_days, mp.last_measurement_date,
                           mp.next_due_date, mp.semaphore_status, e.tag, e.name
                    FROM monitoring_points mp
                    LEFT JOIN equipments e ON mp.equipment_id = e.id
                    WHERE mp.is_active = true
                    ORDER BY e.tag, mp.name
                """)).fetchall()
                if mon_points:
                    ctx.append(f"\n=== PUNTOS DE MONITOREO ({len(mon_points)}) ===")
                    for m in mon_points:
                        eq = f"[{m[7] or '-'}] {m[8] or '-'}"
                        ctx.append(f"  id:{m[0]} | {m[1] or '-'} | {m[2]} | {eq} | cada {m[3]}d | Ult:{m[4] or '-'} | Prox:{m[5] or '-'} | {m[6]}")
            except Exception:
                pass

            # Recent lubrication executions (last 30) — needed for edit/delete
            try:
                lub_execs = _db.session.execute(text("""
                    SELECT le.id, le.point_id, lp.code, lp.name, le.execution_date,
                           le.executed_by, le.quantity_used, le.quantity_unit, le.comments,
                           le.leak_detected, le.anomaly_detected
                    FROM lubrication_executions le
                    JOIN lubrication_points lp ON le.point_id = lp.id
                    ORDER BY le.id DESC LIMIT 30
                """)).fetchall()
                if lub_execs:
                    ctx.append(f"\n=== ULTIMAS {len(lub_execs)} EJECUCIONES DE LUBRICACION ===")
                    for x in lub_execs:
                        flags = ''
                        if x[9]: flags += ' [FUGA]'
                        if x[10]: flags += ' [ANOMALIA]'
                        qty = f" {x[6]}{x[7] or ''}" if x[6] else ''
                        com = f" — {x[8]}" if x[8] else ''
                        ctx.append(f"  exec_id:{x[0]} | {x[2] or f'pt:{x[1]}'} {x[3]} | {x[4]} | por:{x[5] or '-'}{qty}{flags}{com}")
            except Exception:
                pass

            # Technicians
            techs = _db.session.execute(text("SELECT id, name, specialty FROM technicians WHERE is_active = true ORDER BY name")).fetchall()
            if techs:
                ctx.append(f"\n=== TECNICOS ({len(techs)}) ===")
                for t in techs:
                    ctx.append(f"  {t[1]} | {t[2] or '-'} | id:{t[0]}")

            # Warehouse low stock
            try:
                low = _db.session.execute(text("""
                    SELECT code, name, current_stock, min_stock, unit FROM warehouse_items
                    WHERE is_active = true AND current_stock <= min_stock ORDER BY name LIMIT 20
                """)).fetchall()
                if low:
                    ctx.append(f"\n=== STOCK BAJO ({len(low)}) ===")
                    for w in low:
                        ctx.append(f"  {w[0]} {w[1]} | Stock: {w[2]} {w[4] or ''} | Min: {w[3]}")
            except Exception:
                pass

            # Failure recurrence
            try:
                rec = _db.session.execute(text("""
                    SELECT c.name, s.name, e.name, e.tag, l.name, count(w.id)
                    FROM work_orders w
                    JOIN components c ON w.component_id = c.id
                    JOIN systems s ON c.system_id = s.id
                    JOIN equipments e ON w.equipment_id = e.id
                    JOIN lines l ON e.line_id = l.id
                    WHERE w.maintenance_type = 'Correctivo'
                    GROUP BY c.name, s.name, e.name, e.tag, l.name
                    ORDER BY count(w.id) DESC LIMIT 10
                """)).fetchall()
                if rec:
                    ctx.append(f"\n=== TOP FALLAS RECURRENTES ===")
                    for r in rec:
                        ctx.append(f"  {r[0]} ({r[1]}) en {r[2]} [{r[3]}] {r[4]} — {r[5]} OTs")
            except Exception:
                pass

            # Equipment specs (key technical data)
            try:
                especs = _db.session.execute(text("""
                    SELECT e.name, e.tag, es.key_name, es.value_text, es.unit
                    FROM equipment_specs es
                    JOIN equipments e ON es.equipment_id = e.id
                    ORDER BY e.name, es.order_index LIMIT 100
                """)).fetchall()
                if especs:
                    ctx.append(f"\n=== SPECS TECNICOS DE EQUIPOS ===")
                    curr_eq = ''
                    for s in especs:
                        eq_label = f"{s[0]} [{s[1]}]"
                        if eq_label != curr_eq:
                            curr_eq = eq_label
                            ctx.append(f"  {eq_label}:")
                        ctx.append(f"    {s[2]}: {s[3]} {s[4] or ''}")
            except Exception:
                pass

            # Componentes por equipo (lista completa para que el LLM sepa qué existe)
            try:
                comps = _db.session.execute(text("""
                    SELECT e.tag, e.name, s.name AS sys_name, c.name AS comp_name, c.id AS comp_id
                    FROM components c
                    JOIN systems s ON c.system_id = s.id
                    JOIN equipments e ON s.equipment_id = e.id
                    ORDER BY e.tag, s.name, c.name
                """)).fetchall()
                if comps:
                    ctx.append(f"\n=== COMPONENTES POR EQUIPO ===")
                    cur_eq = None
                    for c in comps:
                        eq_lbl = f"[{c[0]}] {c[1]}"
                        if eq_lbl != cur_eq:
                            ctx.append(f"  {eq_lbl}:")
                            cur_eq = eq_lbl
                        ctx.append(f"    - {c[2]} > {c[3]} (comp_id={c[4]})")
            except Exception:
                pass

            # Component specs (sin LIMIT — necesario para responder consultas técnicas)
            try:
                cspecs = _db.session.execute(text("""
                    SELECT e.tag, c.name, cs.key_name, cs.value_text, cs.unit
                    FROM component_specs cs
                    JOIN components c ON cs.component_id = c.id
                    JOIN systems s ON c.system_id = s.id
                    JOIN equipments e ON s.equipment_id = e.id
                    ORDER BY e.tag, c.name, cs.order_index
                """)).fetchall()
                if cspecs:
                    ctx.append(f"\n=== SPECS DE COMPONENTES ===")
                    for s in cspecs:
                        ctx.append(f"  [{s[0]}] {s[1]}: {s[2]}={s[3]} {s[4] or ''}")
            except Exception:
                pass

            # Document links
            try:
                docs = _db.session.execute(text("""
                    SELECT entity_type, entity_id, title, url, doc_type FROM document_links ORDER BY id DESC LIMIT 30
                """)).fetchall()
                if docs:
                    ctx.append(f"\n=== DOCUMENTOS/PLANOS ({len(docs)}) ===")
                    for d in docs:
                        ctx.append(f"  [{d[0]} id:{d[1]}] {d[2]} ({d[4] or 'otro'}) — {d[3]}")
            except Exception:
                pass

            # OTs per technician (workload)
            try:
                workload = _db.session.execute(text("""
                    SELECT t.name, count(w.id) as cnt,
                           sum(CASE WHEN w.status = 'En Progreso' THEN 1 ELSE 0 END) as prog,
                           sum(CASE WHEN w.status IN ('Abierta','Programada') THEN 1 ELSE 0 END) as pend
                    FROM work_orders w
                    JOIN technicians t ON CAST(w.technician_id AS INTEGER) = t.id
                    WHERE w.status != 'Cerrada'
                    GROUP BY t.name ORDER BY cnt DESC
                """)).fetchall()
                if workload:
                    ctx.append(f"\n=== CARGA DE TRABAJO POR TECNICO ===")
                    for w in workload:
                        ctx.append(f"  {w[0]}: {w[1]} OTs ({w[2]} en progreso, {w[3]} pendientes)")
            except Exception:
                pass

            # KPI: corrective vs preventive ratio (only PLAN — exclude GENERAL/FUERA_PLAN noise)
            try:
                corr = _db.session.execute(text("""
                    SELECT count(*) FROM work_orders w
                    LEFT JOIN maintenance_notices n ON w.notice_id = n.id
                    WHERE w.maintenance_type = 'Correctivo'
                      AND COALESCE(n.scope, 'PLAN') = 'PLAN'
                """)).scalar() or 0
                prev = _db.session.execute(text("""
                    SELECT count(*) FROM work_orders w
                    LEFT JOIN maintenance_notices n ON w.notice_id = n.id
                    WHERE w.maintenance_type = 'Preventivo'
                      AND COALESCE(n.scope, 'PLAN') = 'PLAN'
                """)).scalar() or 0
                total_mt = corr + prev
                if total_mt > 0:
                    ctx.append(f"\n=== KPI MANTENIMIENTO (solo PLAN) ===")
                    ctx.append(f"  Correctivo: {corr} ({round(corr/total_mt*100)}%) | Preventivo: {prev} ({round(prev/total_mt*100)}%)")
            except Exception:
                pass

            _db.session.remove()
        except Exception as e:
            ctx.append(f"Error cargando datos: {e}")
            try:
                _db.session.remove()
            except Exception:
                pass

    return '\n'.join(ctx)


# ── Actions ──────────────────────────────────────────────────────────────────

# Component name synonyms — when DeepSeek says X, also try Y
_COMPONENT_SYNONYMS = {
    'motor': ['motor electrico', 'motor', 'mtr'],
    'motor electrico': ['motor electrico', 'motor', 'mtr'],
    'motorreductor': ['motorreductor', 'motor reductor', 'mtr-red'],
    'reductor': ['reductor', 'caja reductora', 'red'],
    'caja reductora': ['caja reductora', 'reductor', 'red'],
    'chumacera motriz': ['chumacera motriz', 'chumacera lado motriz', 'chum motriz'],
    'chumacera conducida': ['chumacera conducida', 'chumacera lado conducido', 'chum conducida'],
    'chumacera': ['chumacera'],
    'faja': ['faja', 'banda', 'correa'],
    'cadena': ['cadena'],
    'rodamiento': ['rodamiento', 'cojinete', 'balinera'],
    'valvula': ['valvula', 'vavula'],
    'sello': ['sello', 'reten', 'oring'],
    'acople': ['acople', 'acoplamiento', 'copla'],
    'pinon': ['pinon', 'piñon', 'engranaje'],
    'eje': ['eje', 'flecha'],
    'rodillo': ['rodillo', 'polin'],
    'transportador': ['transportador', 'faja transportadora'],
}


def _normalize_token(t):
    """Strip accents and normalize masc/fem endings so 'conducido' ~ 'conducida'."""
    import unicodedata
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii').lower()
    # Stem common spanish gender/number endings
    for end in ('idas', 'idos', 'ida', 'ido', 'as', 'os', 'a', 'o', 'es', 's'):
        if len(t) > len(end) + 2 and t.endswith(end):
            return t[:-len(end)]
    return t


def _smart_component_match(db, text_module, equipment_id, raw_name):
    """Find the best matching component for an equipment given a free-text component name.
    Uses token overlap with normalization (stems gender/number) + synonym expansion.
    Returns (component_id, system_id) or None.
    """
    if not raw_name:
        return None
    name = raw_name.lower().strip()

    # Build candidate search terms: original + synonyms whose KEY tokens are all in input
    user_tokens_raw = set(name.split())
    user_tokens_norm = {_normalize_token(t) for t in user_tokens_raw if len(t) > 2}

    terms = {name}
    for key, syns in _COMPONENT_SYNONYMS.items():
        # Direction A: input contains all key tokens → expand with synonyms
        key_tokens_norm = {_normalize_token(t) for t in key.split() if len(t) > 2}
        if key_tokens_norm and key_tokens_norm.issubset(user_tokens_norm):
            terms.update(syns)
            terms.add(key)
            continue
        # Direction B: input matches one of the synonym phrases → also include the key + all syns
        for syn in syns:
            syn_tokens_norm = {_normalize_token(t) for t in syn.split() if len(t) > 2}
            if syn_tokens_norm and syn_tokens_norm.issubset(user_tokens_norm):
                terms.add(key)
                terms.update(syns)
                break

    rows = db.session.execute(text_module("""
        SELECT c.id, c.name, c.system_id FROM components c
        JOIN systems s ON c.system_id = s.id
        WHERE s.equipment_id = :eid
    """), {"eid": equipment_id}).fetchall()
    if not rows:
        return None

    best = None
    best_score = 0
    for cid, cname, sid in rows:
        cname_low = (cname or '').lower()
        comp_tokens_norm = {_normalize_token(t) for t in cname_low.split() if len(t) > 2}
        score = 0
        # Substring match per synonym term (weighted by length)
        for term in terms:
            if term and term in cname_low:
                score += 10 + len(term)
        # Normalized token overlap (catches 'conducido' vs 'conducida')
        overlap = user_tokens_norm & comp_tokens_norm
        score += len(overlap) * 5
        # Bonus: every component token matched (component is fully described in input)
        if comp_tokens_norm and comp_tokens_norm.issubset(user_tokens_norm):
            score += 20
        if score > best_score:
            best_score = score
            best = (cid, sid)

    return best if best_score > 0 else None


def _resolve_equipment(db, text_module, data):
    """Resolve equipment/component IDs.
    Priority: explicit IDs from DeepSeek > tag/name fuzzy lookup.
    Also resolves rotative_asset_id and back-fills missing levels from it.
    """
    equipment_id = line_id = area_id = system_id = component_id = None
    rotative_asset_id = None

    # 1) Direct IDs (preferred — DeepSeek picks them from context listings)
    if data.get('equipment_id'):
        equipment_id = int(data['equipment_id'])
    if data.get('component_id'):
        component_id = int(data['component_id'])
    if data.get('system_id'):
        system_id = int(data['system_id'])
    if data.get('rotative_asset_id'):
        rotative_asset_id = int(data['rotative_asset_id'])

    # 2) Fuzzy fallbacks if no direct ids
    if not equipment_id:
        if data.get('equipment_tag'):
            row = db.session.execute(text_module("SELECT id, line_id FROM equipments WHERE tag = :t"), {"t": data['equipment_tag']}).fetchone()
            if row:
                equipment_id, line_id = row[0], row[1]
        elif data.get('equipment_name'):
            row = db.session.execute(text_module("SELECT id, line_id FROM equipments WHERE LOWER(name) LIKE :n LIMIT 1"), {"n": f"%{data['equipment_name'].lower()}%"}).fetchone()
            if row:
                equipment_id, line_id = row[0], row[1]

    # 3) If we have a rotative asset, derive equipment/component from it
    if rotative_asset_id:
        r = db.session.execute(text_module("""
            SELECT equipment_id, component_id FROM rotative_assets WHERE id = :id
        """), {"id": rotative_asset_id}).fetchone()
        if r:
            equipment_id = equipment_id or r[0]
            component_id = component_id or r[1]

    # 4) If we have a component but no equipment, derive equipment from component
    if component_id and not equipment_id:
        r = db.session.execute(text_module("""
            SELECT s.equipment_id, c.system_id FROM components c
            JOIN systems s ON c.system_id = s.id
            WHERE c.id = :cid
        """), {"cid": component_id}).fetchone()
        if r:
            equipment_id = r[0]
            system_id = system_id or r[1]

    # 5) Get line_id from equipment if missing
    if equipment_id and not line_id:
        r = db.session.execute(text_module("SELECT line_id FROM equipments WHERE id = :id"), {"id": equipment_id}).fetchone()
        if r:
            line_id = r[0]

    # 6) Get area_id from line
    if line_id:
        r = db.session.execute(text_module("SELECT area_id FROM lines WHERE id = :id"), {"id": line_id}).fetchone()
        if r:
            area_id = r[0]

    # 7) Component fuzzy fallback (when DeepSeek only sent component_name)
    if equipment_id and not component_id and data.get('component_name'):
        component_id, system_id = _smart_component_match(db, text_module, equipment_id, data['component_name']) or (None, None)
        # Try also resolving an asset attached to that component
        if component_id and not rotative_asset_id:
            r = db.session.execute(text_module("""
                SELECT id FROM rotative_assets
                WHERE component_id = :c AND is_active = true LIMIT 1
            """), {"c": component_id}).fetchone()
            if r:
                rotative_asset_id = r[0]

    # 8) Get system_id from component if missing
    if component_id and not system_id:
        r = db.session.execute(text_module("SELECT system_id FROM components WHERE id = :id"), {"id": component_id}).fetchone()
        if r:
            system_id = r[0]

    return equipment_id, line_id, area_id, system_id, component_id, rotative_asset_id


def _create_notice(app, data):
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            max_id = _db.session.execute(text("SELECT COALESCE(MAX(id), 0) FROM maintenance_notices")).scalar()
            code = f"AV-{str(max_id + 1).zfill(4)}"

            eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = _resolve_equipment(_db, text, data)

            # Determine scope: explicit > inferred. PLAN requires a real equipment.
            scope = (data.get('scope') or '').strip().upper() or None
            if scope not in {'PLAN', 'FUERA_PLAN', 'GENERAL'}:
                scope = None
            if not scope:
                scope = 'PLAN' if eq_id else 'FUERA_PLAN'
            # Safety: PLAN without equipment makes no sense — downgrade
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
                "rdate": date.today().isoformat(), "mtype": data.get('maintenance_type', 'Correctivo'),
                "reporter": data.get('reporter_name', 'Bot Telegram'),
                "ar": ar_id, "ln": ln_id, "eq": eq_id, "sys": sys_id, "comp": comp_id, "ra": ra_id,
                "shift": data.get('shift'),
                "scope": scope, "loc": free_loc,
                "fm": data.get('failure_mode'), "fc": data.get('failure_category'), "bo": blockage,
            })
            _db.session.commit()
            nid = _db.session.execute(text("SELECT id FROM maintenance_notices WHERE code = :c"), {"c": code}).scalar()
            _db.session.remove()
            # Mutate data so dispatcher can show the final scope it ended up with
            data['_resolved_scope'] = scope
            return code, nid, None
        except Exception as e:
            _db.session.rollback()
            _db.session.remove()
            return None, None, str(e)


def _promote_notice(app, data):
    """Change the scope of an existing notice and (optionally) link it to a tree equipment.
    When promoting to PLAN, also propagates equipment hierarchy to all linked work orders.
    Reversible: can degrade PLAN -> FUERA_PLAN/GENERAL by passing target_scope only.
    """
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

            # Resolve equipment from the same data shape used by create_notice
            eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = _resolve_equipment(_db, text, data)

            # PLAN requires an equipment — refuse if user did not provide one
            if target_scope == 'PLAN' and not eq_id:
                return None, None, "Para promover a PLAN debes indicar un equipo (equipment_tag o equipment_id)"

            updates = {"scope": target_scope}
            if target_scope == 'PLAN':
                # Set the resolved hierarchy on the notice
                updates.update({
                    "area_id": ar_id, "line_id": ln_id, "equipment_id": eq_id,
                    "system_id": sys_id, "component_id": comp_id, "rotative_asset_id": ra_id,
                    "free_location": None,
                })
            elif target_scope == 'GENERAL':
                # Detach from any equipment — generic activity
                updates.update({
                    "area_id": None, "line_id": None, "equipment_id": None,
                    "system_id": None, "component_id": None, "rotative_asset_id": None,
                })
                if data.get('free_location'):
                    updates["free_location"] = data['free_location']
            else:  # FUERA_PLAN
                # Keep existing free_location unless overridden; clear FK hierarchy
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

            # Propagate hierarchy to linked work orders
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
            _db.session.remove()
            return None, None, str(e)


def _close_ot(app, data):
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

            now = datetime.utcnow().isoformat()[:19]
            comments = data.get('comments', 'Cerrada desde Telegram')
            _db.session.execute(text("""
                UPDATE work_orders SET status = 'Cerrada', real_end_date = :now, execution_comments = :c WHERE code = :code
            """), {"now": now, "c": comments, "code": ot_code})

            # Close linked notice
            if row[2]:
                _db.session.execute(text(
                    "UPDATE maintenance_notices SET status = 'Cerrado', closed_date = :d WHERE id = :id"
                ), {"id": row[2], "d": date.today().isoformat()})

            _db.session.commit()
            _db.session.remove()
            return ot_code, None
        except Exception as e:
            _db.session.rollback()
            _db.session.remove()
            return None, str(e)


def _add_log_entry(app, data):
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
                INSERT INTO ot_bitacora (work_order_id, entry_date, comment, entry_type, created_at)
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
            _db.session.remove()
            return None, str(e)


def _start_ot(app, data):
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
            _db.session.remove()
            return None, str(e)


def _reschedule_ot(app, data):
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
            _db.session.remove()
            return None, str(e)


# Whitelist of editable fields per entity
_NOTICE_EDITABLE = {'description', 'criticality', 'priority', 'maintenance_type',
                    'cancellation_reason', 'status', 'failure_mode', 'failure_category',
                    'closed_date',
                    'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}
_OT_EDITABLE = {'description', 'failure_mode', 'maintenance_type', 'technician_id',
                'scheduled_date', 'estimated_duration', 'tech_count',
                'execution_comments', 'caused_downtime', 'downtime_hours',
                'report_required', 'report_due_date', 'status',
                'real_start_date', 'real_end_date',
                'equipment_id', 'system_id', 'component_id', 'line_id', 'area_id'}


def _resolve_taxonomy(db_session, fields):
    """Resolve equipment_tag/system_name/component_name to FK ids.

    Accepts virtual keys (equipment_tag, system_name, component_name) and
    replaces them with real FK columns (equipment_id, system_id, component_id,
    line_id, area_id).  Returns (resolved_fields_dict, resolved_names_list, error).
    """
    import re
    from sqlalchemy import text
    resolved = {}
    names = []

    eq_tag = fields.pop('equipment_tag', None)
    eq_name = fields.pop('equipment_name', None)
    sys_name = fields.pop('system_name', None)
    comp_name = fields.pop('component_name', None)

    # ── Resolve equipment ──
    eq_row = None
    if eq_tag:
        # Normalize: strip #, collapse spaces
        tag_norm = re.sub(r'\s+', '', (eq_tag or '').upper().replace('#', ''))
        eq_row = db_session.execute(text(
            "SELECT e.id, e.name, e.tag, l.id, l.area_id "
            "FROM equipments e LEFT JOIN lines l ON e.line_id=l.id "
            "WHERE UPPER(REPLACE(REPLACE(e.tag,'#',''),' ','')) = :t LIMIT 1"
        ), {"t": tag_norm}).fetchone()
        if not eq_row:
            # Fallback: try ILIKE on name
            eq_row = db_session.execute(text(
                "SELECT e.id, e.name, e.tag, l.id, l.area_id "
                "FROM equipments e LEFT JOIN lines l ON e.line_id=l.id "
                "WHERE UPPER(REPLACE(REPLACE(e.name,'#',''),' ','')) = :t LIMIT 1"
            ), {"t": tag_norm}).fetchone()
    elif eq_name:
        name_norm = re.sub(r'\s+', '', (eq_name or '').upper().replace('#', ''))
        eq_row = db_session.execute(text(
            "SELECT e.id, e.name, e.tag, l.id, l.area_id "
            "FROM equipments e LEFT JOIN lines l ON e.line_id=l.id "
            "WHERE UPPER(REPLACE(REPLACE(e.name,'#',''),' ','')) = :n "
            "   OR UPPER(REPLACE(REPLACE(e.tag,'#',''),' ','')) = :n LIMIT 1"
        ), {"n": name_norm}).fetchone()

    if eq_row:
        resolved['equipment_id'] = eq_row[0]
        resolved['line_id'] = eq_row[3]
        resolved['area_id'] = eq_row[4]
        names.append(f"equipo: {eq_row[2]} {eq_row[1]}")

    eq_id = resolved.get('equipment_id') or fields.get('equipment_id')

    # ── Resolve system ──
    if sys_name and eq_id:
        sys_row = db_session.execute(text(
            "SELECT id, name FROM systems "
            "WHERE equipment_id = :eid AND UPPER(name) = UPPER(:n) LIMIT 1"
        ), {"eid": eq_id, "n": sys_name.strip()}).fetchone()
        if sys_row:
            resolved['system_id'] = sys_row[0]
            names.append(f"sistema: {sys_row[1]}")

    sys_id = resolved.get('system_id') or fields.get('system_id')

    # ── Resolve component ──
    if comp_name and sys_id:
        comp_row = db_session.execute(text(
            "SELECT id, name FROM components "
            "WHERE system_id = :sid AND UPPER(name) = UPPER(:n) LIMIT 1"
        ), {"sid": sys_id, "n": comp_name.strip()}).fetchone()
        if comp_row:
            resolved['component_id'] = comp_row[0]
            names.append(f"componente: {comp_row[1]}")
    elif comp_name and eq_id and not sys_id:
        # Search component across all systems of this equipment
        comp_row = db_session.execute(text(
            "SELECT c.id, c.name, s.id AS sid, s.name AS sname FROM components c "
            "JOIN systems s ON c.system_id=s.id "
            "WHERE s.equipment_id = :eid AND UPPER(c.name) = UPPER(:n) LIMIT 1"
        ), {"eid": eq_id, "n": comp_name.strip()}).fetchone()
        if comp_row:
            resolved['component_id'] = comp_row[0]
            resolved['system_id'] = comp_row[2]
            names.append(f"sistema: {comp_row[3]}, componente: {comp_row[1]}")

    return resolved, names, None


def _edit_notice(app, data):
    """Edit whitelisted fields of an existing maintenance notice."""
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

            # Resolve taxonomy virtual fields (equipment_tag → equipment_id, etc.)
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

            # Propagate taxonomy changes to linked OTs
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
            _db.session.remove()
            return None, None, str(e)


def _register_lubrication(app, data):
    """Register a lubrication execution for a point. Replicates POST /api/lubrication/executions."""
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        from utils.schedule_helpers import _calculate_lubrication_schedule
        try:
            point_id = data.get('point_id')
            point_code = (data.get('point_code') or '').strip()
            point_query = (data.get('point_query') or '').strip()  # fuzzy fallback

            # Resolve point
            row = None
            if point_id:
                row = _db.session.execute(text("""
                    SELECT id, code, name, frequency_days, warning_days, quantity_unit
                    FROM lubrication_points WHERE id = :id AND is_active = true
                """), {"id": point_id}).fetchone()
            elif point_code:
                row = _db.session.execute(text("""
                    SELECT id, code, name, frequency_days, warning_days, quantity_unit
                    FROM lubrication_points WHERE code = :c AND is_active = true
                """), {"c": point_code}).fetchone()
            elif point_query:
                # Loose ILIKE match across name + code
                q = f"%{point_query}%"
                rows = _db.session.execute(text("""
                    SELECT lp.id, lp.code, lp.name, lp.frequency_days, lp.warning_days, lp.quantity_unit
                    FROM lubrication_points lp
                    LEFT JOIN equipments e ON lp.equipment_id = e.id
                    WHERE lp.is_active = true AND (
                        lp.name ILIKE :q OR lp.code ILIKE :q OR e.name ILIKE :q OR e.tag ILIKE :q
                    )
                    LIMIT 5
                """), {"q": q}).fetchall()
                if len(rows) == 1:
                    row = rows[0]
                elif len(rows) > 1:
                    options = ', '.join(f"{r[1] or r[0]} ({r[2]})" for r in rows)
                    return None, None, f"Varios puntos coinciden con '{point_query}': {options}. Especifica el codigo."

            if not row:
                return None, None, "Punto de lubricacion no encontrado. Especifica point_id, point_code o point_query mas claro."

            pid, pcode, pname, freq_days, warn_days, qty_unit = row

            execution_date = data.get('execution_date') or date.today().isoformat()
            executed_by = data.get('executed_by') or 'MANTENIMIENTO'
            quantity_used = data.get('quantity_used')
            comments = data.get('comments')
            leak = bool(data.get('leak_detected', False))
            anomaly = bool(data.get('anomaly_detected', False))
            action_type = data.get('action_type') or 'SERVICIO'

            # Insert execution
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

            # Recalculate schedule and update point
            next_due, semaphore = _calculate_lubrication_schedule(execution_date, freq_days, warn_days)
            _db.session.execute(text("""
                UPDATE lubrication_points
                SET last_service_date = :lsd, next_due_date = :nd, semaphore_status = :ss
                WHERE id = :id
            """), {"lsd": execution_date, "nd": next_due, "ss": semaphore, "id": pid})

            _db.session.commit()
            _db.session.remove()
            return pcode or f"id:{pid}", pname, None
        except Exception as e:
            _db.session.rollback()
            _db.session.remove()
            return None, None, str(e)


_LUB_EXEC_EDITABLE = {'execution_date', 'executed_by', 'quantity_used', 'quantity_unit',
                      'comments', 'leak_detected', 'anomaly_detected', 'action_type'}


def _refresh_lub_point_from_executions(_db, text, point_id):
    """Recalculate lubrication_points.last_service_date / next_due_date / semaphore
    based on the latest remaining execution after an edit or delete."""
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


def _edit_lubrication(app, data):
    """Edit fields of an existing lubrication execution."""
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

            _refresh_lub_point_from_executions(_db, text, row[1])
            _db.session.commit()
            _db.session.remove()
            return row[2] or f"id:{row[1]}", row[3], None
        except Exception as e:
            _db.session.rollback()
            _db.session.remove()
            return None, None, str(e)


def _delete_lubrication(app, data):
    """Delete a lubrication execution by id."""
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
            _refresh_lub_point_from_executions(_db, text, row[1])
            _db.session.commit()
            _db.session.remove()
            return row[2] or f"id:{row[1]}", row[3], None
        except Exception as e:
            _db.session.rollback()
            _db.session.remove()
            return None, None, str(e)


def _edit_ot(app, data):
    """Edit whitelisted fields of an existing work order."""
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

            # Resolve taxonomy virtual fields (equipment_tag → equipment_id, etc.)
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

            # Propagate taxonomy changes to linked notice
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
            _db.session.remove()
            return None, None, str(e)


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
            results = semantic_search(_db.session, query_text, top_k=4)
        if not results:
            return ''
        # Filtrar resultados con baja similitud (ruido)
        results = [r for r in results if r.get('similarity', 0) >= 0.35]
        if not results:
            return ''
        lines = ["=== CASOS HISTORICOS SIMILARES (encontrados por busqueda semantica) ==="]
        lines.append("INSTRUCCION: si el usuario pregunta '¿como se arreglo la ultima vez?' o pide")
        lines.append("comparar con casos pasados, USA estos como referencia y citalos por codigo.")
        lines.append("")
        for i, r in enumerate(results, 1):
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


def _transcribe_voice(file_id):
    """Transcribe un mensaje de voz de Telegram usando Whisper API.

    Devuelve el texto transcrito o None si falla. Requiere OPENAI_API_KEY.
    Telegram envia voz en formato OGG/Opus que Whisper acepta nativamente.
    """
    if not OPENAI_API_KEY:
        return None
    audio_bytes, fp = _download_telegram_file(file_id)
    if not audio_bytes:
        return None
    try:
        # Determinar nombre de archivo segun extension original
        ext = (fp or 'voice.ogg').rsplit('.', 1)[-1] if fp and '.' in fp else 'ogg'
        filename = f"voice.{ext}"
        files = {
            'file': (filename, audio_bytes, 'audio/ogg'),
            'model': (None, 'whisper-1'),
            'language': (None, 'es'),
            'response_format': (None, 'text'),
        }
        headers = {'Authorization': f'Bearer {OPENAI_API_KEY}'}
        r = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers=headers, files=files, timeout=60,
        )
        if r.status_code != 200:
            logger.warning(f"Whisper API error {r.status_code}: {r.text[:200]}")
            return None
        text = r.text.strip()
        return text or None
    except Exception as e:
        logger.warning(f"_transcribe_voice error: {e}")
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

def _ask_deepseek(question, cmms_context, is_action=False, history=None):
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

REGLA CRITICA #2: Si el usuario reporta una falla, pide crear/editar/cerrar algo, NO uses action:"none" con reply describiendo la accion. Devuelve la accion real. El campo "reply" NUNCA debe contener frases como "aviso creado", "AV-XXXX generado", "OT cerrada", "accion registrada" — eso solo lo hace el sistema despues de ejecutar la accion real.

ACCIONES DISPONIBLES:

1. CREAR AVISO (reportar falla o registrar actividad):
{"action": "create_notice", "data": {"description": "...", "scope": "PLAN|FUERA_PLAN|GENERAL", "failure_mode": "Rotura|Desgaste|Fuga|Desalineacion|Sobrecalentamiento|Ruido anormal|Vibracion excesiva|Aflojamiento|Corrosion|Atascamiento|Descarrilamiento|Cortocircuito|Sobrecarga|Fatiga", "failure_category": "Mecanica|Electrica|Hidraulica|Neumatica|Instrumentacion|Lubricacion|Estructural", "blockage_object": "Metal|Piedra|Cadena|Madera|Alambre|Perno|Acero Inoxidable|Bronce|Otro", "equipment_tag": "D8", "component_name": "motor electrico", "free_location": "texto libre si no hay equipo", "criticality": "Alta|Media|Baja", "priority": "Alta|Normal|Baja", "maintenance_type": "Correctivo|Preventivo|Mejora"}}

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
{"action": "close_ot", "data": {"ot_code": "OT-0034", "comments": "Trabajo completado - se reemplazo faja y se verifico alineacion"}}

3. INICIAR OT:
{"action": "start_ot", "data": {"ot_code": "OT-0034"}}

4. AGREGAR NOTA A BITACORA:
{"action": "add_log", "data": {"ot_code": "OT-0034", "comment": "Se cambio faja y se alineo poleas", "entry_type": "NOTA|AVANCE|MATERIAL|PROVEEDOR|INFORME"}}

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
{"action": "register_lubrication", "data": {"point_id": 12, "execution_date": "2026-03-30", "executed_by": "MANTENIMIENTO|FAPMETAL|nombre tecnico", "quantity_used": 0.5, "comments": "opcional", "leak_detected": false, "anomaly_detected": false}}
- Busca el punto en la lista PUNTOS DE LUBRICACION del contexto. Usa el `id` que aparece como `id:NN`. Tambien puedes usar `point_code` si lo conoces.
- Si no encuentras un id exacto, usa `point_query` con texto fuzzy: {"point_query": "chumacera motriz digestor 8"}
- execution_date: convierte fechas relativas o textos como "30-marzo", "ayer", "hoy" a formato ISO YYYY-MM-DD. Si dicen una hora, ignorala (solo fecha). Hoy es """ + date.today().isoformat() + """.
- executed_by: por defecto "MANTENIMIENTO". Si el usuario menciona "FAPMETAL" o "fap metal" usa "FAPMETAL". Si menciona un nombre, usalo.
- leak_detected/anomaly_detected: solo true si el usuario lo menciona explicitamente. Si los marca true, se creara automaticamente un aviso de mantenimiento.
- IMPORTANTE: NO uses esta accion si el usuario dice "corrige", "cambia", "actualiza", "estaba mal", "era ayer", "era el ...", "no era ese tecnico" sobre una ejecucion ya registrada. En esos casos usa edit_lubrication.
- IMPORTANTE: NO uses esta accion si el usuario dice "elimina", "borra", "anula" una ejecucion. Usa delete_lubrication.

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

    system_prompt = f"""Eres el asistente de mantenimiento del CMMS Pro, sistema de gestion de mantenimiento industrial.
SIEMPRE respondes con un objeto JSON valido (ver FORMATO DE RESPUESTA OBLIGATORIO abajo). NUNCA texto plano fuera de JSON.
Dentro del campo "reply" responde en español, conciso y profesional. Usa SOLO datos reales del sistema.
NUNCA inventes datos ni confirmes acciones no realizadas.
Si no tienes info, responde {{"action":"none","reply":"No tengo esa informacion."}}.

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

    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            return f"Error DeepSeek: {r.status_code} {r.text[:200]}"
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
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
    """Extract JSON from AI response (handles markdown code blocks)."""
    s = text.strip()
    if '```' in s:
        parts = s.split('```')
        for p in parts:
            p = p.strip()
            if p.startswith('json'):
                p = p[4:].strip()
            if p.startswith('{'):
                try:
                    return json.loads(p)
                except Exception:
                    pass
    if s.startswith('{'):
        try:
            return json.loads(s)
        except Exception:
            pass
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

    # Memoria de conversacion: trae los ultimos turnos del chat (TTL 10 min)
    history = _get_chat_history(chat_id)
    answer = _ask_deepseek(text, context, is_action=True, history=history)

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
        # Safety net: if parsing failed, don't dump raw JSON/garbage to user
        logger.warning(f"Bot: failed to parse JSON from DeepSeek. Raw: {answer[:200]}")
        _send(chat_id, "⚠️ No pude procesar la respuesta. Intenta reformular tu mensaje.")
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

            _send(chat_id, f"""✅ *Aviso creado: {code}*
{scope_emoji} _{scope_label}_

📋 {data.get('description', '-')}
{equip_line}{comp_line}{failure_block}
🔴 Criticidad: {data.get('criticality', 'Media')}
📅 {date.today().isoformat()}

📷 _Envia una foto para adjuntarla._""")
        else:
            _send(chat_id, f"❌ Error creando aviso: {err}")
        return

    elif action == 'close_ot':
        code, err = _close_ot(app, data)
        if code:
            _send(chat_id, f"✅ *{code} cerrada*\n📝 {data.get('comments', '-')}")
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
            _send(chat_id, f"✅ *Lubricacion registrada*\n🔧 Punto: {code} — {pname}\n📅 Fecha: {ed}\n👤 Por: {eb}{qty_line}{extra}")
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
                        if _seen_update(update_id):
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
                                    transcribed = _transcribe_voice(file_id)
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
