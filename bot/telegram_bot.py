"""Telegram Bot for CMMS — full data access, actions, alerts via DeepSeek AI."""
import os
import json
import logging
import threading
import time
import requests
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
POLL_INTERVAL = 2

# Authorized chat_ids — only these can use the bot
OWNER_CHAT_ID = 1853592586
_allowed_chats = {OWNER_CHAT_ID}

# Store admin chat_ids for daily alerts
_admin_chats = set()


def _tg_api(method, **kwargs):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}'
    r = requests.post(url, json=kwargs, timeout=30)
    return r.json()


def _send(chat_id, text):
    for i in range(0, len(text), 4000):
        _tg_api('sendMessage', chat_id=chat_id, text=text[i:i+4000], parse_mode='Markdown')


# ── Data Context ─────────────────────────────────────────────────────────────

def _get_cmms_context(app):
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
            n_total = _db.session.execute(text("SELECT count(*) FROM maintenance_notices")).scalar()
            n_pending = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE status = 'Pendiente'")).scalar()

            ctx.append("=== RESUMEN CMMS ===")
            ctx.append(f"OTs totales: {wo_total} | Abiertas: {wo_open} | En Progreso: {wo_progress} | Programadas: {wo_prog} | Cerradas: {wo_closed}")
            ctx.append(f"Avisos totales: {n_total} | Pendientes: {n_pending}")

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

            # Notices (last 30)
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
                eq = f"{n[10] or ''} {n[9] or '-'}".strip()
                ctx.append(f"  {n[1]} | {n[2]} | {eq} | {n[12] or '-'} | {n[3] or '-'} | Crit: {n[4] or '-'} | id:{n[0]}")

            # Rotative Assets
            assets = _db.session.execute(text("""
                SELECT ra.code, ra.name, ra.category, ra.brand, ra.model, ra.status,
                       e.name, c.name FROM rotative_assets ra
                LEFT JOIN equipments e ON ra.equipment_id = e.id
                LEFT JOIN components c ON ra.component_id = c.id
                WHERE ra.is_active = true ORDER BY ra.code LIMIT 50
            """)).fetchall()
            if assets:
                ctx.append(f"\n=== ACTIVOS ROTATIVOS ({len(assets)}) ===")
                for a in assets:
                    ctx.append(f"  {a[0]} {a[1]} | {a[2] or '-'} | {a[3] or ''} {a[4] or ''} | {a[5]} | En: {a[6] or '-'}/{a[7] or '-'}")

            # Overdue points
            try:
                lub = _db.session.execute(text("SELECT count(*) FROM lubrication_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                insp = _db.session.execute(text("SELECT count(*) FROM inspection_routes WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                mon = _db.session.execute(text("SELECT count(*) FROM monitoring_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                ctx.append(f"\n=== PUNTOS VENCIDOS (ROJO) === Lub: {lub} | Insp: {insp} | Mon: {mon}")
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

            # Component specs
            try:
                cspecs = _db.session.execute(text("""
                    SELECT e.tag, c.name, cs.key_name, cs.value_text, cs.unit
                    FROM component_specs cs
                    JOIN components c ON cs.component_id = c.id
                    JOIN systems s ON c.system_id = s.id
                    JOIN equipments e ON s.equipment_id = e.id
                    ORDER BY e.tag, c.name, cs.order_index LIMIT 100
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

            # KPI: corrective vs preventive ratio
            try:
                corr = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Correctivo'")).scalar() or 0
                prev = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Preventivo'")).scalar() or 0
                total_mt = corr + prev
                if total_mt > 0:
                    ctx.append(f"\n=== KPI MANTENIMIENTO ===")
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

def _resolve_equipment(db, text_module, data):
    """Resolve equipment/component IDs from tag or name."""
    equipment_id = line_id = area_id = system_id = component_id = None

    if data.get('equipment_tag'):
        row = db.session.execute(text_module("SELECT id, line_id FROM equipments WHERE tag = :t"), {"t": data['equipment_tag']}).fetchone()
        if row:
            equipment_id, line_id = row[0], row[1]
    elif data.get('equipment_name'):
        row = db.session.execute(text_module("SELECT id, line_id FROM equipments WHERE LOWER(name) LIKE :n LIMIT 1"), {"n": f"%{data['equipment_name'].lower()}%"}).fetchone()
        if row:
            equipment_id, line_id = row[0], row[1]

    if line_id:
        r = db.session.execute(text_module("SELECT area_id FROM lines WHERE id = :id"), {"id": line_id}).fetchone()
        if r:
            area_id = r[0]

    if equipment_id and data.get('component_name'):
        r = db.session.execute(text_module("""
            SELECT c.id, c.system_id FROM components c
            JOIN systems s ON c.system_id = s.id
            WHERE s.equipment_id = :eid AND LOWER(c.name) LIKE :n LIMIT 1
        """), {"eid": equipment_id, "n": f"%{data['component_name'].lower()}%"}).fetchone()
        if r:
            component_id, system_id = r[0], r[1]

    return equipment_id, line_id, area_id, system_id, component_id


def _create_notice(app, data):
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            max_id = _db.session.execute(text("SELECT COALESCE(MAX(id), 0) FROM maintenance_notices")).scalar()
            code = f"AV-{str(max_id + 1).zfill(4)}"

            eq_id, ln_id, ar_id, sys_id, comp_id = _resolve_equipment(_db, text, data)

            desc_parts = [data.get('description', 'Reporte desde Telegram')]
            if data.get('failure_mode'):
                desc_parts.append(f"[Modo de falla: {data['failure_mode']}]")
            if data.get('failure_category'):
                desc_parts.append(f"[Tipo: {data['failure_category']}]")

            _db.session.execute(text("""
                INSERT INTO maintenance_notices (code, description, criticality, priority, request_date,
                    maintenance_type, status, reporter_name, reporter_type,
                    area_id, line_id, equipment_id, system_id, component_id, shift)
                VALUES (:code, :desc, :crit, :prio, :rdate, :mtype, 'Pendiente', :reporter, 'telegram',
                    :ar, :ln, :eq, :sys, :comp, :shift)
            """), {
                "code": code, "desc": ' | '.join(desc_parts),
                "crit": data.get('criticality', 'Media'), "prio": data.get('priority', 'Normal'),
                "rdate": date.today().isoformat(), "mtype": data.get('maintenance_type', 'Correctivo'),
                "reporter": data.get('reporter_name', 'Bot Telegram'),
                "ar": ar_id, "ln": ln_id, "eq": eq_id, "sys": sys_id, "comp": comp_id,
                "shift": data.get('shift'),
            })
            _db.session.commit()
            nid = _db.session.execute(text("SELECT id FROM maintenance_notices WHERE code = :c"), {"c": code}).scalar()
            _db.session.remove()
            return code, nid, None
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
                _db.session.execute(text("UPDATE maintenance_notices SET status = 'Cerrado' WHERE id = :id"), {"id": row[2]})

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
            _db.session.commit()
            _db.session.remove()
        return url
    except Exception as e:
        logger.error(f"Photo upload error: {e}")
        return None


# ── DeepSeek AI ──────────────────────────────────────────────────────────────

def _ask_deepseek(question, cmms_context, is_action=False):
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}

    action_instructions = ""
    if is_action:
        action_instructions = """

ACCIONES DISPONIBLES — responde SOLO con JSON cuando el usuario quiera ejecutar una accion:

1. CREAR AVISO (reportar falla):
{"action": "create_notice", "data": {"description": "descripcion profesional orientada al modo de falla", "failure_mode": "Rotura|Desgaste|Fuga|Desalineacion|Sobrecalentamiento|Ruido anormal|Vibracion excesiva|Aflojamiento|Corrosion|Atascamiento|Descarrilamiento|Cortocircuito|Sobrecarga|Fatiga", "failure_category": "Mecanica|Electrica|Hidraulica|Neumatica|Instrumentacion|Lubricacion|Estructural", "equipment_tag": "D2", "equipment_name": "DIGESTOR #2", "component_name": "FAJA", "criticality": "Alta|Media|Baja", "priority": "Alta|Normal|Baja", "maintenance_type": "Correctivo"}}

2. CERRAR OT:
{"action": "close_ot", "data": {"ot_code": "OT-0034", "comments": "Trabajo completado - se reemplazo faja y se verifico alineacion"}}

3. INICIAR OT:
{"action": "start_ot", "data": {"ot_code": "OT-0034"}}

4. AGREGAR NOTA A BITACORA:
{"action": "add_log", "data": {"ot_code": "OT-0034", "comment": "Se cambio faja y se alineo poleas", "entry_type": "NOTA|AVANCE|MATERIAL|PROVEEDOR|INFORME"}}

5. REPROGRAMAR OT (cambiar fecha):
{"action": "reschedule_ot", "data": {"ot_code": "OT-0034", "new_date": "2026-04-10"}}
Convierte fechas relativas: "lunes" = proximo lunes, "mañana" = fecha de mañana. Hoy es """ + date.today().isoformat() + """.

REGLAS para interpretar avisos:
- description: Redacta profesionalmente orientado al modo de falla, NO copies textual al usuario.
  Ej: usuario dice "la faja se rompio" → "Rotura de faja de transmision - requiere inspeccion y reemplazo"
  Ej: "el motor suena raro" → "Ruido anormal en motor electrico - posible falla en rodamientos"
  Ej: "el reductor bota aceite" → "Fuga de aceite en caja reductora - revisar retenes y nivel"
- Busca el equipo en los DATOS del sistema por tag o nombre
- Si no sabes el equipo, PREGUNTA antes de generar JSON
- Si es consulta normal, responde con texto (NO JSON)"""

    system_prompt = f"""Eres el asistente de mantenimiento del CMMS Pro, sistema de gestion de mantenimiento industrial.
Responde en español, conciso y profesional. Usa SOLO datos reales del sistema.
NUNCA inventes datos ni confirmes acciones no realizadas.
Si no tienes info, di: "No tengo esa informacion."

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

    payload = {
        'model': 'deepseek-chat',
        'messages': [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': question}],
        'max_tokens': 2000, 'temperature': 0.2,
    }

    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
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

            # Low stock
            low_stock = _db.session.execute(text("""
                SELECT count(*) FROM warehouse_items WHERE is_active = true AND current_stock <= min_stock
            """)).scalar() or 0

            _db.session.remove()

            # Build message
            msg = f"""📊 *Resumen Diario CMMS* — {date.today().isoformat()}

📋 OTs abiertas: *{wo_open}* | En progreso: *{wo_progress}*
🔔 Avisos pendientes: *{n_pending}*"""

            if lub + insp + mon > 0:
                msg += f"\n\n🔴 *Puntos vencidos:*\n  Lubricacion: {lub} | Inspeccion: {insp} | Monitoreo: {mon}"

            if overdue:
                msg += f"\n\n⏰ *OTs vencidas ({len(overdue)}):*"
                for o in overdue:
                    msg += f"\n  {o[0]} — prog: {o[2]} — {(o[1] or '-')[:50]}"

            if reports_due:
                msg += f"\n\n📄 *Informes vencidos ({len(reports_due)}):*"
                for r in reports_due:
                    msg += f"\n  {r[0]} — vencio: {r[1]}"

            if low_stock:
                msg += f"\n\n📦 *{low_stock} items con stock bajo*"

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
• Despues de crear aviso, envia foto

*Analisis:*
• _% correctivo vs preventivo_
• _Que repuestos necesito stockear?_
• _Resumen ejecutivo para gerencia_""")
        return

    # Process
    _send(chat_id, "⏳ Consultando datos...")
    context = _get_cmms_context(app)
    is_action = any(kw in text.lower() for kw in ACTION_KEYWORDS)
    answer = _ask_deepseek(text, context, is_action=is_action)

    # Handle JSON actions
    if is_action:
        action_data = _extract_json(answer)
        if action_data and isinstance(action_data, dict):
            action = action_data.get('action')
            data = action_data.get('data', {})

            if action == 'create_notice':
                code, nid, err = _create_notice(app, data)
                if code and nid:
                    _pending_photos[chat_id] = {"entity_type": "notice", "entity_id": nid, "code": code}
                    fm = data.get('failure_mode', '-')
                    fc = data.get('failure_category', '-')
                    eq = data.get('equipment_tag') or data.get('equipment_name') or '-'
                    _send(chat_id, f"""✅ *Aviso creado: {code}*

📋 {data.get('description', '-')}
⚙️ Equipo: {eq}
🔧 Componente: {data.get('component_name', '-')}
⚠️ Modo de falla: {fm}
🏷️ Tipo: {fc}
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

    _send(chat_id, answer)


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
                        offset = update['update_id'] + 1
                        msg = update.get('message', {})
                        chat_id = msg.get('chat', {}).get('id')
                        txt = msg.get('text', '')
                        photos = msg.get('photo')
                        caption = msg.get('caption', '')
                        if chat_id and (txt or photos):
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

    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=daily_alerts, daemon=True).start()
    logger.info("Telegram bot + daily alerts started.")
