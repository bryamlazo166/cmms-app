"""Construccion del contexto que recibe el LLM en cada conversacion del bot.

Centraliza:
  - Carga del documento maestro (docs/cmms_guide.md) con cache por mtime.
  - Historial de chat por chat_id (sliding window con TTL).
  - _get_focused_equipment_context: cuando el usuario menciona un equipo
    explicito, inyecta su info completa al inicio del prompt.
  - _build_cmms_context_real: agrega resumen, taxonomia, OTs, avisos,
    KPIs, lubricacion, inspecciones, monitoreo, especificaciones, etc.
  - Cache global del contexto (TTL 60s).
"""
import os
import time
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Re-exportamos _tg_api/_send para que codigo que viva en context y necesite
# enviar typing actions pueda hacerlo sin import circular.
def _send_typing_proxy(chat_id):
    from bot.telegram_bot import _send_typing
    return _send_typing(chat_id)

# ── Carga del documento maestro CMMS ─────────────────────────────────────
_GUIDE_CACHE = {'path': None, 'mtime': 0.0, 'content': ''}


def _load_cmms_guide():
    """Carga docs/cmms_guide.md como conocimiento maestro del bot.

    Cache por mtime: si el archivo no cambio, no se relee. Asi podes editar
    el .md sin reiniciar el bot.
    """
    candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'docs', 'cmms_guide.md'),
        os.path.join(os.getcwd(), 'docs', 'cmms_guide.md'),
    ]
    path = next((p for p in candidates if os.path.isfile(p)), None)
    if not path:
        return ''
    try:
        mtime = os.path.getmtime(path)
        if _GUIDE_CACHE['path'] == path and _GUIDE_CACHE['mtime'] == mtime:
            return _GUIDE_CACHE['content']
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        _GUIDE_CACHE.update({'path': path, 'mtime': mtime, 'content': content})
        return content
    except Exception as e:
        logger.warning(f"No se pudo cargar cmms_guide.md: {e}")
        return ''


# ── Historial de chat ────────────────────────────────────────────────────
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


# ── Contexto CMMS para el LLM ────────────────────────────────────────────
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

    # Tambien capturar tags cortos LITERALES escritos directamente por el usuario
    # (ej: "TH2", "TH7", "D5", "MOLI2", "SEC2"). Sin necesidad de "TRANSPORTADOR".
    # Estos se usan ademas para FILTRAR estrictamente cuando un prefijo de linea
    # como "SEC2" matchea muchos hijos (SEC2-TH1..SEC2-TH10).
    explicit_short_tags = set()
    for m in re.finditer(
        r'\b(TH\d+|MR\d+|MOLI\d+|TRI\d+|PER\d+|VAHO\d+|SEC\d+|D\d+|H\d+)\b',
        msg_norm,
    ):
        explicit_short_tags.add(m.group(1))
    inferred_tags.update(explicit_short_tags)

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

            # ── FILTRO ESTRICTO POR TAG CORTO LITERAL ──────────────────
            # Si el usuario escribio "TH2" / "TH7" / "D5" textualmente, y la
            # inferencia de la linea (ej: SEC2 desde "secador 2") trajo todos
            # los hijos de esa linea, restringir al tag corto exacto.
            # Ej: "TH2 secador 2" -> NO traer SEC2-TH10, solo SEC2-TH2.
            if explicit_short_tags and len(matched_ids) > 1:
                try:
                    eqs_for_filter = _db.session.execute(text(
                        "SELECT id, tag FROM equipments WHERE id = ANY(:ids)"
                    ), {"ids": list(matched_ids)}).fetchall()
                    filtered_strict = set()
                    for ef in eqs_for_filter:
                        segs = set(((ef[1] or '').upper()).split('-'))
                        if explicit_short_tags & segs:
                            filtered_strict.add(ef[0])
                    if filtered_strict:
                        matched_ids = filtered_strict
                except Exception:
                    pass

            # ── DESAMBIGUACION: si hay multiples equipos del mismo nombre,
            # filtrar por LINEA o AREA mencionada en el mensaje, y priorizar
            # los que TIENEN component_specs (mas utiles para responder).
            # Umbral bajo (>=2) cuando el usuario menciona una linea/area:
            # asi "TH2 secador 2" elige SEC2-TH2 sobre TH2 (cocción).
            if len(matched_ids) >= 2:
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

            # ── HISTORIAL ENRIQUECIDO POR EQUIPO (Mejora 1) ──────────────
            # Por cada equipo identificado traemos: ultimas OTs cerradas,
            # ultimos avisos, preventivos vencidos/proximos, lecturas de espesor.
            try:
                from datetime import date as _date, timedelta as _td
                today_iso = _date.today().isoformat()
                soon_iso = (_date.today() + _td(days=30)).isoformat()

                # Ultimas OTs cerradas por equipo (top 5 c/u)
                ot_hist = _db.session.execute(text("""
                    SELECT equipment_id, code, real_end_date, maintenance_type,
                           failure_mode, description, execution_comments, technician_id
                    FROM work_orders
                    WHERE equipment_id = ANY(:ids) AND status = 'Cerrada'
                    ORDER BY equipment_id, real_end_date DESC NULLS LAST, id DESC
                """), {"ids": matched_list}).fetchall()
                ot_by_eq = {}
                for r in ot_hist:
                    ot_by_eq.setdefault(r[0], []).append(r)

                # Ultimos avisos por equipo (top 5 c/u)
                nt_hist = _db.session.execute(text("""
                    SELECT equipment_id, code, request_date, status, criticality,
                           failure_mode, blockage_object, description
                    FROM maintenance_notices
                    WHERE equipment_id = ANY(:ids)
                    ORDER BY equipment_id, request_date DESC NULLS LAST, id DESC
                """), {"ids": matched_list}).fetchall()
                nt_by_eq = {}
                for r in nt_hist:
                    nt_by_eq.setdefault(r[0], []).append(r)

                # Preventivos: lubricacion
                lub_rows = _db.session.execute(text("""
                    SELECT lp.equipment_id, lp.code, lp.lubricant_name, lp.frequency_days,
                           lp.last_service_date, lp.next_due_date
                    FROM lubrication_points lp
                    WHERE lp.equipment_id = ANY(:ids) AND lp.is_active = TRUE
                    ORDER BY lp.next_due_date NULLS LAST
                """), {"ids": matched_list}).fetchall()
                lub_by_eq = {}
                for r in lub_rows:
                    lub_by_eq.setdefault(r[0], []).append(r)

                # Preventivos: inspecciones (rutas)
                insp_rows = _db.session.execute(text("""
                    SELECT ir.equipment_id, ir.code, ir.name, ir.frequency_days,
                           ir.last_execution_date, ir.next_due_date, ir.semaphore_status
                    FROM inspection_routes ir
                    WHERE ir.equipment_id = ANY(:ids) AND ir.is_active = TRUE
                    ORDER BY ir.next_due_date NULLS LAST
                """), {"ids": matched_list}).fetchall()
                insp_by_eq = {}
                for r in insp_rows:
                    insp_by_eq.setdefault(r[0], []).append(r)

                # Monitoreo de condicion
                mon_rows = _db.session.execute(text("""
                    SELECT mp.equipment_id, mp.code, mp.name, mp.frequency_days,
                           mp.last_measurement_date, mp.next_due_date
                    FROM monitoring_points mp
                    WHERE mp.equipment_id = ANY(:ids) AND mp.is_active = TRUE
                    ORDER BY mp.next_due_date NULLS LAST
                """), {"ids": matched_list}).fetchall()
                mon_by_eq = {}
                for r in mon_rows:
                    mon_by_eq.setdefault(r[0], []).append(r)

                # Puntos de espesor (top criticos por equipo)
                tp_rows = _db.session.execute(text("""
                    SELECT tp.equipment_id, tp.group_name, tp.section, tp.position,
                           tp.nominal_thickness, tp.alarm_thickness, tp.scrap_thickness,
                           tp.last_value, tp.last_date, tp.status
                    FROM thickness_points tp
                    WHERE tp.equipment_id = ANY(:ids) AND tp.is_active = TRUE
                      AND tp.status IN ('CRITICO', 'ALERTA')
                    ORDER BY tp.status DESC, tp.last_value ASC NULLS LAST
                """), {"ids": matched_list}).fetchall()
                tp_by_eq = {}
                for r in tp_rows:
                    tp_by_eq.setdefault(r[0], []).append(r)

                # Render historial agrupado por equipo
                for eq in eqs_rows:
                    eq_id = eq[0]
                    hist_lines = []

                    ots = (ot_by_eq.get(eq_id) or [])[:5]
                    if ots:
                        hist_lines.append(f"    [HISTORIAL OTs CERRADAS]")
                        for r in ots:
                            fm = f" - {r[4]}" if r[4] else ""
                            tech = f" (tec: {r[7]})" if r[7] else ""
                            comments = (r[6] or '')[:120]
                            hist_lines.append(
                                f"      * {r[1]} | {r[3] or '-'} | cerrada: {r[2] or '?'}{fm}{tech}"
                            )
                            if r[5]:
                                hist_lines.append(f"        desc: {r[5][:160]}")
                            if comments:
                                hist_lines.append(f"        trabajo: {comments}")

                    nts = (nt_by_eq.get(eq_id) or [])[:5]
                    if nts:
                        hist_lines.append(f"    [HISTORIAL AVISOS]")
                        for r in nts:
                            fm = f" - {r[5]}" if r[5] else ""
                            blk = f" [bloqueo: {r[6]}]" if r[6] else ""
                            hist_lines.append(
                                f"      * {r[1]} | {r[3] or '-'} | fecha: {r[2] or '?'}"
                                f" | crit: {r[4] or '-'}{fm}{blk}"
                            )
                            if r[7]:
                                hist_lines.append(f"        desc: {r[7][:160]}")

                    # Preventivos clasificados: vencidos y proximos 30 dias
                    vencidos = []
                    proximos = []
                    for (code, tipo_label, next_due, extra) in [
                        *[(l[1], f"LUBRICACION - {l[2]}", l[5], f"cada {l[3]}d") for l in lub_by_eq.get(eq_id, [])],
                        *[(i[1], f"INSPECCION - {i[2]}", i[5], f"cada {i[3]}d") for i in insp_by_eq.get(eq_id, [])],
                        *[(m[1], f"MONITOREO - {m[2]}", m[5], f"cada {m[3]}d") for m in mon_by_eq.get(eq_id, [])],
                    ]:
                        if not next_due:
                            continue
                        if next_due < today_iso:
                            vencidos.append((code, tipo_label, next_due, extra))
                        elif next_due <= soon_iso:
                            proximos.append((code, tipo_label, next_due, extra))
                    if vencidos:
                        hist_lines.append(f"    [PREVENTIVOS VENCIDOS] (urgente)")
                        for c, t, d, x in vencidos[:8]:
                            hist_lines.append(f"      ! {c} | {t} | vencio: {d} ({x})")
                    if proximos:
                        hist_lines.append(f"    [PREVENTIVOS PROXIMOS 30 DIAS]")
                        for c, t, d, x in proximos[:8]:
                            hist_lines.append(f"      > {c} | {t} | vence: {d} ({x})")

                    # Espesores criticos/alerta
                    tps = tp_by_eq.get(eq_id, [])
                    if tps:
                        hist_lines.append(f"    [ESPESORES CRITICOS/ALERTA]")
                        for r in tps[:6]:
                            loc = ' - '.join(filter(None, [r[1], r[2], r[3]]))
                            hist_lines.append(
                                f"      * {r[9]} | {loc} | nominal {r[4]}mm,"
                                f" alarma {r[5]}mm, scrap {r[6]}mm"
                                f" | ultimo {r[7] or '?'}mm el {r[8] or '?'}"
                            )

                    if hist_lines:
                        # Insertar historial al final del bloque del equipo
                        lines.extend(hist_lines)
            except Exception as _e:
                logger.warning(f"Historial enriquecido fallo: {_e}")
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
        "\n"
        "  Los bloques [HISTORIAL OTs CERRADAS] y [HISTORIAL AVISOS] muestran el\n"
        "  historico de mantenimiento del equipo. USALOS para responder preguntas como:\n"
        "  - '¿cuando fue la ultima vez que cambie el tripode del D9?' -> busca\n"
        "    en 'trabajo:' o 'desc:' de OTs cerradas que mencionen 'tripode' y da\n"
        "    la fecha de cierre y el codigo OT.\n"
        "  - '¿cuando fallo la ultima X?' -> busca en avisos.\n"
        "  - '¿cuantas veces se rompio Y este ano?' -> cuenta OTs/avisos que\n"
        "    mencionen Y y responde con numero y codigos.\n"
        "\n"
        "  Los bloques [PREVENTIVOS VENCIDOS] y [PREVENTIVOS PROXIMOS 30 DIAS]\n"
        "  responden a '¿que mantenimiento le toca al equipo X?'. Lista los codigos\n"
        "  (LUB-xxx, RTA-xxx, MON-xxx) con el tipo y la fecha vencida o proxima.\n"
        "\n"
        "  [ESPESORES CRITICOS/ALERTA] muestra puntos UT del equipo con status\n"
        "  CRITICO o ALERTA. Si el usuario pregunta '¿donde esta mas delgado?' o\n"
        "  '¿hay riesgo en la chaqueta?', responde con los puntos listados.\n"
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

            # Work Orders (last 50) — ahora incluye report_required, report_status,
            # report_due_date y nombre del proveedor para preguntas tipo
            # "que OTs les falta informe" o "OTs de FAPMETAL sin informe".
            ots = _db.session.execute(text("""
                SELECT w.id, w.code, w.maintenance_type, w.status, w.description,
                       w.scheduled_date, w.failure_mode, w.real_start_date, w.real_end_date,
                       e.name, e.tag, c.name, s.name, l.name, w.notice_id,
                       t.name as tech_name, w.technician_id, w.report_url,
                       w.report_required, w.report_status, w.report_due_date,
                       p.name as provider_name
                FROM work_orders w
                LEFT JOIN equipments e ON w.equipment_id = e.id
                LEFT JOIN components c ON w.component_id = c.id
                LEFT JOIN systems s ON w.system_id = s.id
                LEFT JOIN lines l ON w.line_id = l.id
                LEFT JOIN technicians t ON CAST(w.technician_id AS INTEGER) = t.id
                LEFT JOIN providers p ON w.provider_id = p.id
                ORDER BY w.id DESC LIMIT 50
            """)).fetchall()
            ctx.append(f"\n=== ULTIMAS {len(ots)} OTs ===")
            ctx.append("INSTRUCCION: si el usuario pide 'el informe', 'el link',")
            ctx.append("'el archivo' o 'el reporte' de una OT, devuelve TAL CUAL la")
            ctx.append("URL que aparece tras 'Informe:' en esa OT como enlace")
            ctx.append("clickeable. Solo si esa OT no tiene 'Informe:' responde que")
            ctx.append("aun no hay informe cargado. El link puede ser un archivo o una")
            ctx.append("carpeta de Drive con varios documentos.")
            for o in ots:
                eq = f"{o[10] or ''} {o[9] or '-'}".strip()
                tech = o[15] or '-'
                report_part = f" | Informe: {o[17]}" if o[17] else ""
                # Marca explicita del estado del informe — clave para
                # responder "OTs sin informe".
                if o[18]:  # report_required
                    if o[17]:
                        report_status_part = " | InfReq:RECIBIDO"
                    elif o[19] == 'RECIBIDO':
                        report_status_part = " | InfReq:RECIBIDO_sin_url"
                    else:
                        due = f" venceN{o[20]}" if o[20] else ""
                        report_status_part = f" | InfReq:PENDIENTE{due}"
                else:
                    report_status_part = ""
                prov_part = f" | Prov:{o[21]}" if o[21] else ""
                ctx.append(f"  {o[1]} | {o[2] or '-'} | {o[3]} | {eq} | {o[12] or ''}/{o[11] or ''} | {o[4] or '-'} | Falla: {o[6] or '-'} | Tec: {tech} | Prog: {o[5] or '-'} | id:{o[0]}{prov_part}{report_part}{report_status_part}")

            # Seccion dedicada: OTs con informe pendiente — el LLM puede
            # responder rapido "que OTs les falta informe" o filtrarlas
            # por proveedor sin tener que escanear toda la lista de OTs.
            try:
                pendientes_inf = _db.session.execute(text("""
                    SELECT w.code, w.status, w.real_end_date, w.report_due_date,
                           e.tag, e.name, p.name as provider, w.description
                    FROM work_orders w
                    LEFT JOIN equipments e ON w.equipment_id = e.id
                    LEFT JOIN providers p ON w.provider_id = p.id
                    WHERE w.report_required = true
                      AND (w.report_status IS NULL OR w.report_status != 'RECIBIDO')
                      AND (w.report_url IS NULL OR w.report_url = '')
                    ORDER BY
                      CASE WHEN w.report_due_date IS NULL THEN 1 ELSE 0 END,
                      w.report_due_date ASC,
                      w.id DESC
                    LIMIT 40
                """)).fetchall()
                if pendientes_inf:
                    today_iso = date.today().isoformat()
                    ctx.append(f"\n=== OTs CON INFORME PENDIENTE ({len(pendientes_inf)}) ===")
                    ctx.append("INSTRUCCION: si el usuario pregunta 'que OTs les falta informe',")
                    ctx.append("'OTs sin informe', 'OTs de <PROVEEDOR> sin informe', usa esta lista.")
                    ctx.append("Filtra por proveedor si el usuario lo pide. Si la fecha de vencimiento")
                    ctx.append("es anterior a hoy ({}), marca el informe como VENCIDO.".format(today_iso))
                    for r in pendientes_inf:
                        eq = f"[{r[4] or '-'}] {r[5] or '-'}".strip()
                        prov = f"Prov:{r[6]}" if r[6] else "Prov:-"
                        if r[3] and r[3] < today_iso:
                            estado = f"VENCIDO desde {r[3]}"
                        elif r[3]:
                            delta = 0
                            try:
                                delta = (date.fromisoformat(r[3]) - date.today()).days
                            except Exception:
                                pass
                            estado = f"vence {r[3]} (en {delta}d)"
                        else:
                            estado = "sin fecha limite"
                        cierre = f"cerrada {r[2]}" if r[2] else f"estado {r[1]}"
                        desc = (r[7] or '')[:80]
                        ctx.append(f"  {r[0]} | {prov} | {eq} | {cierre} | informe: {estado} | {desc}")
            except Exception as e:
                ctx.append(f"(error informes pendientes: {e})")

            # Bitacora / Log entries — relevantes para responder "muestrame el informe / bitacora"
            # Trae las ultimas 80 entradas de las OTs visibles en contexto. Si una entrada
            # contiene una URL, el LLM debe devolverla como enlace clickeable al usuario.
            try:
                ot_ids_for_log = [o[0] for o in ots]
                if ot_ids_for_log:
                    logs = _db.session.execute(text("""
                        SELECT le.id, w.code, le.log_date, le.log_type, le.author, le.comment
                        FROM ot_log_entries le
                        JOIN work_orders w ON le.work_order_id = w.id
                        WHERE le.work_order_id = ANY(:ids)
                        ORDER BY le.id DESC LIMIT 80
                    """), {"ids": ot_ids_for_log}).fetchall()
                    if logs:
                        ctx.append(f"\n=== BITACORA DE OTs ({len(logs)} entradas recientes) ===")
                        ctx.append("INSTRUCCION: si el usuario pide 'el informe' o 'la bitacora' de una OT,")
                        ctx.append("busca aqui las entradas correspondientes. Si una entrada contiene una URL")
                        ctx.append("(http://... o https://...), devuelvela al usuario como enlace clickeable.")
                        ctx.append("Tambien revisa el campo 'Informe:' en la lista de OTs (es report_url directo).")
                        for lg in logs:
                            comment = (lg[5] or '').replace('\n', ' ')
                            if len(comment) > 240:
                                comment = comment[:240] + '...'
                            ctx.append(f"  {lg[1]} | {lg[2]} | {lg[3]} | {lg[4] or '-'} | {comment}")
            except Exception as e:
                ctx.append(f"(error bitacora: {e})")

            # Herramientas y materiales usados en OTs — clave para preguntas
            # tipo "que llave se usa para X", "que herramienta se uso en el
            # cambio de chumacera del TH3", "que repuestos se cambiaron en
            # la OT-0034". Une ot_materials con tools/warehouse_items para
            # traer el nombre legible. Limitado a 200 lineas para no inflar
            # el contexto del LLM.
            try:
                ot_ids_for_mat = [o[0] for o in ots]
                if ot_ids_for_mat:
                    mats = _db.session.execute(text("""
                        SELECT w.code,
                               COALESCE(om.subtype, om.item_type) AS tipo,
                               CASE
                                 WHEN om.item_type = 'tool'      THEN COALESCE(t.code || ' - ' || t.name, om.item_name_free)
                                 WHEN om.item_type = 'warehouse' THEN COALESCE(wi.code || ' - ' || wi.name, om.item_name_free)
                                 ELSE om.item_name_free
                               END AS nombre,
                               om.quantity, om.unit, om.is_installed,
                               e.tag, e.name, c.name
                        FROM ot_materials om
                        JOIN work_orders w ON om.work_order_id = w.id
                        LEFT JOIN tools t           ON om.item_type = 'tool'      AND om.item_id = t.id
                        LEFT JOIN warehouse_items wi ON om.item_type = 'warehouse' AND om.item_id = wi.id
                        LEFT JOIN equipments e ON w.equipment_id = e.id
                        LEFT JOIN components c ON w.component_id = c.id
                        WHERE om.work_order_id = ANY(:ids)
                        ORDER BY w.id DESC, om.id ASC
                        LIMIT 200
                    """), {"ids": ot_ids_for_mat}).fetchall()
                    if mats:
                        ctx.append(f"\n=== HERRAMIENTAS Y MATERIALES USADOS EN OTs ({len(mats)} items) ===")
                        ctx.append("INSTRUCCION: si el usuario pregunta 'que herramienta/llave/repuesto se uso para X',")
                        ctx.append("busca trabajos similares en esta lista (mismo equipo, componente o tipo de falla)")
                        ctx.append("y devuelve los items registrados. Si no hay coincidencia exacta, sugiere las OTs")
                        ctx.append("mas parecidas y los items que se usaron en cada una. Formato por linea:")
                        ctx.append("  OT | tipo (herramienta/consumible/repuesto/tool/warehouse/free) | nombre | cant unidad | instalado | equipo | componente")
                        for m in mats:
                            inst = '' if m[5] is None else (' [instalado]' if m[5] else ' [solo uso]')
                            qty = f"{m[3] or ''} {m[4] or ''}".strip() or '-'
                            eq = f"[{m[6] or '-'}] {m[7] or ''}".strip()
                            comp = m[8] or '-'
                            ctx.append(f"  {m[0]} | {m[1] or '-'} | {m[2] or '-'} | {qty}{inst} | {eq} | {comp}")
            except Exception as e:
                ctx.append(f"(error materiales: {e})")

            # Catalogo maestro de herramientas — preguntas tipo "que llave
            # mixta hay disponible", "que herramientas tenemos para medir
            # alineacion", etc.
            try:
                tools_master = _db.session.execute(text("""
                    SELECT id, code, name, category, description, status, location
                    FROM tools WHERE is_active = true
                    ORDER BY category NULLS LAST, name
                    LIMIT 150
                """)).fetchall()
                if tools_master:
                    ctx.append(f"\n=== CATALOGO DE HERRAMIENTAS ({len(tools_master)}) ===")
                    for h in tools_master:
                        loc = f" | Ubic: {h[6]}" if h[6] else ""
                        desc = f" | {h[4][:80]}" if h[4] else ""
                        ctx.append(f"  id:{h[0]} | {h[1] or '-'} | {h[2]} | {h[3] or '-'} | {h[5] or '-'}{loc}{desc}")
            except Exception as e:
                ctx.append(f"(error catalogo herramientas: {e})")

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

            # Modulo de SEGUIMIENTO (Activities + Milestones) — actividades
            # globales de fabricacion/compra/proyecto/parada/reunion con sus
            # hitos. Solo activas + ultimas N completadas para no saturar.
            try:
                acts = _db.session.execute(text("""
                    SELECT a.id, a.title, a.activity_type, a.priority, a.status,
                           a.responsible, a.start_date, a.target_date, a.completion_date,
                           e.tag, e.name, a.description
                    FROM activities a
                    LEFT JOIN equipments e ON a.equipment_id = e.id
                    WHERE a.status IN ('ABIERTA', 'EN_PROGRESO')
                    ORDER BY
                        CASE a.priority WHEN 'ALTA' THEN 0 WHEN 'MEDIA' THEN 1 ELSE 2 END,
                        a.target_date NULLS LAST
                """)).fetchall()
                if acts:
                    ctx.append(f"\n=== SEGUIMIENTO — ACTIVIDADES ACTIVAS ({len(acts)}) ===")
                    ctx.append("(Modulo /seguimiento: actividades globales tipo fabricacion, compra, proyecto, parada, reunion. NO confundir con OTs ni avisos)")
                    act_ids = []
                    for a in acts:
                        act_ids.append(a[0])
                        eq_part = f" | equipo: {a[9] or '-'} ({a[10] or '-'})" if a[9] or a[10] else ''
                        dates = []
                        if a[6]: dates.append(f"inicio:{a[6]}")
                        if a[7]: dates.append(f"meta:{a[7]}")
                        date_part = (" | " + ", ".join(dates)) if dates else ''
                        desc_part = f"\n    desc: {a[11][:200]}" if a[11] else ''
                        ctx.append(f"  id:{a[0]} | [{a[2]}] {a[1]} | {a[4]} | prio:{a[3]} | resp:{a[5] or '-'}{date_part}{eq_part}{desc_part}")

                    # Milestones de esas actividades (limitar a ~50 mas relevantes)
                    if act_ids:
                        ms_rows = _db.session.execute(text(f"""
                            SELECT activity_id, description, status, target_date, completion_date, comment
                            FROM milestones
                            WHERE activity_id IN ({','.join(str(x) for x in act_ids)})
                              AND is_active = true
                            ORDER BY activity_id, order_index, id
                            LIMIT 80
                        """)).fetchall()
                        ms_by_act = {}
                        for m in ms_rows:
                            ms_by_act.setdefault(m[0], []).append(m)
                        if ms_by_act:
                            ctx.append("\n=== SEGUIMIENTO — HITOS DE LAS ACTIVIDADES ===")
                            for aid, mlist in ms_by_act.items():
                                ctx.append(f"  Actividad id:{aid}:")
                                for m in mlist:
                                    icon = '✓' if m[2] == 'COMPLETADO' else ('▶' if m[2] == 'EN_PROGRESO' else '○')
                                    target = f" (meta:{m[3]})" if m[3] else ''
                                    done = f" [hecho:{m[4]}]" if m[4] else ''
                                    com = f" — {m[5][:120]}" if m[5] else ''
                                    ctx.append(f"    {icon} {m[1]}{target}{done}{com}")
            except Exception as _e:
                ctx.append(f"(error seguimiento: {_e})")

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

            # Hammer batches state (FAPMETAL) — para responder "que lote esta en M1", etc.
            try:
                hb_rows = _db.session.execute(text(
                    "SELECT code, state, hammers_count, refill_count "
                    "FROM hammer_batches WHERE is_active = true ORDER BY code"
                )).fetchall()
                if hb_rows:
                    ctx.append(f"\n=== LOTES DE MARTILLOS FAPMETAL ({len(hb_rows)} activos) ===")
                    state_label = {
                        'INSTALADO_M1': 'Molino #1',
                        'INSTALADO_M2': 'Molino #2',
                        'EN_FAPMETAL': 'En FAPMETAL (a rellenar)',
                        'RELLENADO_EN_STOCK': 'Rellenado en stock (listo)',
                    }
                    for r in hb_rows:
                        loc = state_label.get(r[1], r[1])
                        ctx.append(f"  {r[0]}: {loc} | {r[2]} martillos | rellenados acumulados: {r[3]}")
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
