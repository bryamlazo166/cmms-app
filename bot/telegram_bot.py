"""Telegram Bot for CMMS — queries and creates maintenance data via DeepSeek AI."""
import os
import json
import logging
import threading
import time
import requests
from datetime import datetime, date

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
POLL_INTERVAL = 2


def _tg_api(method, **kwargs):
    """Call Telegram Bot API."""
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}'
    r = requests.post(url, json=kwargs, timeout=30)
    return r.json()


def _send_message(chat_id, text):
    """Send a message to a Telegram chat (chunked if too long)."""
    for i in range(0, len(text), 4000):
        _tg_api('sendMessage', chat_id=chat_id, text=text[i:i+4000], parse_mode='Markdown')


def _get_cmms_context(app):
    """Build comprehensive context string with all CMMS data (except costs)."""
    ctx = []

    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            # ── Summary counts ──
            wo_total = _db.session.execute(text("SELECT count(*) FROM work_orders")).scalar()
            wo_open = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status != 'Cerrada'")).scalar()
            wo_closed = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'Cerrada'")).scalar()
            wo_progress = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'En Progreso'")).scalar()
            wo_programmed = _db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'Programada'")).scalar()
            n_total = _db.session.execute(text("SELECT count(*) FROM maintenance_notices")).scalar()
            n_pending = _db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE status = 'Pendiente'")).scalar()

            ctx.append("=== RESUMEN CMMS ===")
            ctx.append(f"OTs totales: {wo_total} | Abiertas: {wo_open} | En Progreso: {wo_progress} | Programadas: {wo_programmed} | Cerradas: {wo_closed}")
            ctx.append(f"Avisos totales: {n_total} | Pendientes: {n_pending}")

            # ── Areas and Lines ──
            areas = _db.session.execute(text("SELECT id, name FROM areas ORDER BY name")).fetchall()
            lines = _db.session.execute(text("SELECT id, name, area_id FROM lines ORDER BY name")).fetchall()
            ctx.append(f"\n=== AREAS ({len(areas)}) ===")
            for a in areas:
                area_lines = [l for l in lines if l[2] == a[0]]
                line_names = ', '.join(l[1] for l in area_lines)
                ctx.append(f"  {a[1]} (id:{a[0]}) — Lineas: {line_names or 'ninguna'}")

            # ── Equipment (all) ──
            equips = _db.session.execute(text("""
                SELECT e.id, e.name, e.tag, e.criticality, l.name as line_name
                FROM equipments e LEFT JOIN lines l ON e.line_id = l.id
                ORDER BY l.name, e.name
            """)).fetchall()
            ctx.append(f"\n=== EQUIPOS ({len(equips)}) ===")
            for e in equips:
                ctx.append(f"  {e[1]} [{e[2]}] | Criticidad: {e[3] or '-'} | Linea: {e[4] or '-'} | id:{e[0]}")

            # ── All Work Orders (last 50) ──
            all_ots = _db.session.execute(text("""
                SELECT w.id, w.code, w.maintenance_type, w.status, w.description,
                       w.scheduled_date, w.failure_mode, w.real_start_date, w.real_end_date,
                       e.name as eq_name, e.tag as eq_tag,
                       c.name as comp_name, s.name as sys_name, l.name as line_name,
                       w.notice_id, w.created_at
                FROM work_orders w
                LEFT JOIN equipments e ON w.equipment_id = e.id
                LEFT JOIN components c ON w.component_id = c.id
                LEFT JOIN systems s ON w.system_id = s.id
                LEFT JOIN lines l ON w.line_id = l.id
                ORDER BY w.id DESC LIMIT 50
            """)).fetchall()
            ctx.append(f"\n=== ULTIMAS {len(all_ots)} OTs ===")
            for ot in all_ots:
                eq = f"{ot[10] or ''} {ot[9] or '-'}".strip()
                comp = ot[11] or ''
                sys = ot[12] or ''
                ctx.append(f"  {ot[1]} | {ot[2] or '-'} | {ot[3]} | {eq} | {sys}/{comp} | {ot[4] or '-'} | Falla: {ot[6] or '-'} | Prog: {ot[5] or '-'}")

            # ── Notices (last 30) ──
            notices = _db.session.execute(text("""
                SELECT n.id, n.code, n.status, n.description, n.criticality, n.priority,
                       n.request_date, n.maintenance_type, n.reporter_name,
                       e.name as eq_name, e.tag as eq_tag, l.name as line_name,
                       c.name as comp_name
                FROM maintenance_notices n
                LEFT JOIN equipments e ON n.equipment_id = e.id
                LEFT JOIN lines l ON n.line_id = l.id
                LEFT JOIN components c ON n.component_id = c.id
                ORDER BY n.id DESC LIMIT 30
            """)).fetchall()
            ctx.append(f"\n=== ULTIMOS {len(notices)} AVISOS ===")
            for n in notices:
                eq = f"{n[10] or ''} {n[9] or '-'}".strip()
                ctx.append(f"  {n[1]} | {n[2]} | {eq} | {n[12] or '-'} | {n[3] or '-'} | Crit: {n[4] or '-'} | Prio: {n[5] or '-'} | Fecha: {n[6] or '-'}")

            # ── Rotative Assets ──
            assets = _db.session.execute(text("""
                SELECT ra.code, ra.name, ra.category, ra.brand, ra.model, ra.status,
                       e.name as eq_name, c.name as comp_name
                FROM rotative_assets ra
                LEFT JOIN equipments e ON ra.equipment_id = e.id
                LEFT JOIN components c ON ra.component_id = c.id
                WHERE ra.is_active = true
                ORDER BY ra.code LIMIT 50
            """)).fetchall()
            if assets:
                ctx.append(f"\n=== ACTIVOS ROTATIVOS ({len(assets)}) ===")
                for a in assets:
                    ctx.append(f"  {a[0]} {a[1]} | {a[2] or '-'} | {a[3] or ''} {a[4] or ''} | Estado: {a[5]} | En: {a[6] or '-'}/{a[7] or '-'}")

            # ── Overdue preventive points ──
            try:
                lub_r = _db.session.execute(text("SELECT count(*) FROM lubrication_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar()
                insp_r = _db.session.execute(text("SELECT count(*) FROM inspection_routes WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar()
                mon_r = _db.session.execute(text("SELECT count(*) FROM monitoring_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar()
                ctx.append(f"\n=== PUNTOS PREVENTIVOS VENCIDOS (ROJO) ===")
                ctx.append(f"  Lubricacion: {lub_r or 0} | Inspeccion: {insp_r or 0} | Monitoreo: {mon_r or 0}")
            except Exception:
                pass

            # ── Technicians ──
            techs = _db.session.execute(text("SELECT id, name, specialty FROM technicians WHERE is_active = true ORDER BY name")).fetchall()
            if techs:
                ctx.append(f"\n=== TECNICOS ({len(techs)}) ===")
                for t in techs:
                    ctx.append(f"  {t[1]} | {t[2] or '-'} | id:{t[0]}")

            # ── Warehouse items (low stock) ──
            try:
                low_stock = _db.session.execute(text("""
                    SELECT code, name, current_stock, min_stock, unit
                    FROM warehouse_items
                    WHERE is_active = true AND current_stock <= min_stock
                    ORDER BY name LIMIT 20
                """)).fetchall()
                if low_stock:
                    ctx.append(f"\n=== ALMACEN — STOCK BAJO ({len(low_stock)} items) ===")
                    for w in low_stock:
                        ctx.append(f"  {w[0]} {w[1]} | Stock: {w[2]} {w[4] or ''} | Min: {w[3]}")
            except Exception:
                pass

            # ── Failure recurrence (top 10 components with most corrective OTs) ──
            try:
                recurrence = _db.session.execute(text("""
                    SELECT c.name as comp, s.name as sys, e.name as equip, e.tag, l.name as linea,
                           count(w.id) as cnt
                    FROM work_orders w
                    JOIN components c ON w.component_id = c.id
                    JOIN systems s ON c.system_id = s.id
                    JOIN equipments e ON w.equipment_id = e.id
                    JOIN lines l ON e.line_id = l.id
                    WHERE w.maintenance_type = 'Correctivo'
                    GROUP BY c.name, s.name, e.name, e.tag, l.name
                    ORDER BY cnt DESC LIMIT 10
                """)).fetchall()
                if recurrence:
                    ctx.append(f"\n=== TOP FALLAS RECURRENTES (Correctivos) ===")
                    for r in recurrence:
                        ctx.append(f"  {r[0]} ({r[1]}) en {r[2]} [{r[3]}] {r[4]} — {r[5]} OTs")
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


# ── Actions: Create notices and work orders ──────────────────────────────────

def _create_notice(app, data):
    """Create a maintenance notice from bot data. Returns (notice_code, error)."""
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            # Get next code
            max_id = _db.session.execute(text("SELECT COALESCE(MAX(id), 0) FROM maintenance_notices")).scalar()
            next_code = f"AV-{str(max_id + 1).zfill(4)}"

            # Resolve equipment by tag or name
            equipment_id = None
            line_id = None
            area_id = None
            system_id = None
            component_id = None

            if data.get('equipment_tag'):
                row = _db.session.execute(text("SELECT id, line_id FROM equipments WHERE tag = :t"), {"t": data['equipment_tag']}).fetchone()
                if row:
                    equipment_id = row[0]
                    line_id = row[1]
                    line_row = _db.session.execute(text("SELECT area_id FROM lines WHERE id = :id"), {"id": line_id}).fetchone()
                    if line_row:
                        area_id = line_row[0]
            elif data.get('equipment_name'):
                row = _db.session.execute(text("SELECT id, line_id FROM equipments WHERE LOWER(name) LIKE :n LIMIT 1"), {"n": f"%{data['equipment_name'].lower()}%"}).fetchone()
                if row:
                    equipment_id = row[0]
                    line_id = row[1]
                    line_row = _db.session.execute(text("SELECT area_id FROM lines WHERE id = :id"), {"id": line_id}).fetchone()
                    if line_row:
                        area_id = line_row[0]

            if equipment_id and data.get('component_name'):
                comp_row = _db.session.execute(text("""
                    SELECT c.id, c.system_id FROM components c
                    JOIN systems s ON c.system_id = s.id
                    WHERE s.equipment_id = :eid AND LOWER(c.name) LIKE :n LIMIT 1
                """), {"eid": equipment_id, "n": f"%{data['component_name'].lower()}%"}).fetchone()
                if comp_row:
                    component_id = comp_row[0]
                    system_id = comp_row[1]

            # Build enriched description with failure info
            desc_parts = [data.get('description', 'Reporte desde Telegram')]
            if data.get('failure_mode'):
                desc_parts.append(f"[Modo de falla: {data['failure_mode']}]")
            if data.get('failure_category'):
                desc_parts.append(f"[Tipo: {data['failure_category']}]")
            full_desc = ' | '.join(desc_parts)

            _db.session.execute(text("""
                INSERT INTO maintenance_notices (code, description, criticality, priority, request_date,
                    maintenance_type, status, reporter_name, reporter_type,
                    area_id, line_id, equipment_id, system_id, component_id, shift)
                VALUES (:code, :desc, :crit, :prio, :rdate, :mtype, 'Pendiente', :reporter, :rtype,
                    :area_id, :line_id, :eq_id, :sys_id, :comp_id, :shift)
            """), {
                "code": next_code,
                "desc": full_desc,
                "crit": data.get('criticality', 'Media'),
                "prio": data.get('priority', 'Normal'),
                "rdate": date.today().isoformat(),
                "mtype": data.get('maintenance_type', 'Correctivo'),
                "reporter": data.get('reporter_name', 'Bot Telegram'),
                "rtype": "telegram",
                "area_id": area_id,
                "line_id": line_id,
                "eq_id": equipment_id,
                "sys_id": system_id,
                "comp_id": component_id,
                "shift": data.get('shift'),
            })
            _db.session.commit()

            # Get the created notice id
            notice_id = _db.session.execute(text("SELECT id FROM maintenance_notices WHERE code = :c"), {"c": next_code}).scalar()
            _db.session.remove()
            return next_code, notice_id, None
        except Exception as e:
            _db.session.rollback()
            _db.session.remove()
            return None, None, str(e)


def _upload_telegram_photo(app, file_id, entity_type, entity_id):
    """Download photo from Telegram and upload to Supabase Storage."""
    try:
        # Get file path from Telegram
        file_info = _tg_api('getFile', file_id=file_id)
        if not file_info.get('ok'):
            return None
        file_path = file_info['result']['file_path']
        download_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'

        # Download the photo
        photo_data = requests.get(download_url, timeout=30).content

        # Compress and upload
        from utils.photo_helpers import compress_photo, upload_to_supabase_storage
        compressed, dimensions = compress_photo(photo_data)
        url = upload_to_supabase_storage(compressed, f"telegram_{file_id}.jpg")

        # Save to DB
        with app.app_context():
            from database import db as _db
            from sqlalchemy import text
            _db.session.execute(text("""
                INSERT INTO photo_attachments (entity_type, entity_id, url, caption, original_size_kb, compressed_size_kb, created_at)
                VALUES (:etype, :eid, :url, :caption, :orig, :comp, NOW())
            """), {
                "etype": entity_type,
                "eid": entity_id,
                "url": url,
                "caption": "Foto desde Telegram",
                "orig": len(photo_data) // 1024,
                "comp": len(compressed) // 1024,
            })
            _db.session.commit()
            _db.session.remove()
        return url
    except Exception as e:
        logger.error(f"Photo upload error: {e}")
        return None


def _ask_deepseek(question, cmms_context, is_action=False):
    """Send question + CMMS context to DeepSeek and get response."""
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json',
    }

    action_instructions = ""
    if is_action:
        action_instructions = """

IMPORTANTE SOBRE ACCIONES — CREACION DE AVISOS:
Cuando el usuario quiera reportar una falla o crear un aviso, responde UNICAMENTE con un JSON.
Tu rol es INTERPRETAR el mensaje del usuario como un profesional de mantenimiento industrial y enriquecer los datos:

1. **description**: Redacta una descripcion profesional orientada al MODO DE FALLA, no copies textual lo que dijo el usuario.
   Ejemplos de buenas descripciones:
   - Usuario dice "la faja del digestor 2 se rompio" → "Rotura de faja de transmision - requiere inspeccion y reemplazo"
   - Usuario dice "el motor suena raro" → "Ruido anormal en motor electrico - posible falla en rodamientos"
   - Usuario dice "se salio la cadena del TH3" → "Descarrilamiento de cadena de transmision - verificar tension y estado de sprockets"
   - Usuario dice "el reductor bota aceite" → "Fuga de aceite en caja reductora - revisar retenes y nivel de aceite"

2. **failure_mode**: Clasifica el modo de falla usando terminologia estandar:
   - Rotura | Desgaste | Fuga | Desalineacion | Desbalanceo | Sobrecalentamiento | Ruido anormal | Vibracion excesiva | Aflojamiento | Corrosion | Atascamiento | Descarrilamiento | Cortocircuito | Sobrecarga | Deformacion | Fatiga

3. **failure_category**: Clasifica el tipo de falla:
   - Mecanica | Electrica | Hidraulica | Neumatica | Instrumentacion | Lubricacion | Estructural

4. **criticality**: Deduce la criticidad segun el impacto:
   - Alta: parada de linea, riesgo de seguridad, dano mayor
   - Media: degradacion de rendimiento, falla parcial
   - Baja: estetico, menor, no afecta produccion

5. **equipment_tag** / **equipment_name** / **component_name**: Identifica del arbol de equipos del CMMS.
   Busca coincidencias con los datos proporcionados. Si el usuario dice "digestor 2" busca "DIGESTOR #2" con tag "D2".
   Si dice "TH3" busca el equipo con tag "TH3". Si menciona "faja", "cadena", "motor", "reductor", busca el componente mas cercano.

Formato JSON de respuesta:
{"action": "create_notice", "data": {"description": "...", "failure_mode": "Rotura|Desgaste|...", "failure_category": "Mecanica|Electrica|...", "equipment_tag": "D2", "equipment_name": "DIGESTOR #2", "component_name": "FAJA", "criticality": "Alta|Media|Baja", "priority": "Alta|Normal|Baja", "maintenance_type": "Correctivo"}}

Solo incluye los campos que puedas deducir. Si no sabes el equipo, PREGUNTA antes de generar el JSON.
NO confirmes que creaste nada. Solo devuelve el JSON.
Si es una consulta normal (no una accion), responde normalmente con texto."""

    system_prompt = f"""Eres el asistente de mantenimiento del CMMS Pro, un sistema de gestion de mantenimiento industrial.
Responde en español, de forma concisa y profesional.
Usa UNICAMENTE los datos reales del sistema para responder.
Si no tienes la informacion, dilo claramente: "No tengo esa informacion en el sistema."
NUNCA inventes datos, codigos, ni confirmes acciones que no hayas realizado.
NUNCA digas que creaste un aviso, OT, o cualquier registro — tu NO puedes crear registros directamente.
Si el usuario pide crear algo, usa el formato JSON indicado.
{action_instructions}

DATOS ACTUALES DEL SISTEMA:
{cmms_context}
"""

    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': question},
        ],
        'max_tokens': 1500,
        'temperature': 0.2,
    }

    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            return f"Error DeepSeek: {r.status_code} {r.text[:200]}"
        data = r.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        return f"Error consultando IA: {e}"


# ── Pending photo state per chat ──
_pending_photos = {}  # chat_id -> {"entity_type": ..., "entity_id": ...}


def _process_message(app, chat_id, text, photos=None):
    """Process an incoming Telegram message."""
    text = (text or '').strip()

    # Handle photos
    if photos:
        pending = _pending_photos.get(chat_id)
        if pending:
            uploaded = 0
            for p in photos:
                file_id = p[-1]['file_id']  # Largest size
                url = _upload_telegram_photo(app, file_id, pending['entity_type'], pending['entity_id'])
                if url:
                    uploaded += 1
            if uploaded:
                _send_message(chat_id, f"📷 {uploaded} foto(s) subida(s) al {pending['entity_type']} {pending.get('code', '')}.")
            else:
                _send_message(chat_id, "❌ Error subiendo la foto.")
            return
        else:
            _send_message(chat_id, "📷 Foto recibida, pero no hay un aviso activo donde adjuntarla.\nPrimero reporta una falla y luego envia la foto.")
            return

    if not text:
        return

    # Simple commands
    if text.lower() in ('/start', '/help', 'hola', 'ayuda'):
        _send_message(chat_id, """*CMMS Pro Bot* 🏭

Puedo responder consultas y crear reportes:

*Consultas:*
• _Cuantas OTs abiertas hay?_
• _Estado del digestor #1_
• _Que componentes fallan mas?_
• _Hay puntos de lubricacion vencidos?_
• _Resumen de la planta_
• _Que activos rotativos hay instalados?_
• _Items con stock bajo en almacen_

*Crear avisos:*
• _Reportar falla en faja del digestor #2_
• _La cadena del TH3 esta rota_
• Despues de crear el aviso, envia una foto para adjuntarla

Solo escribe tu pregunta en lenguaje natural.""")
        return

    # Query AI with CMMS context
    _send_message(chat_id, "⏳ Consultando datos...")
    context = _get_cmms_context(app)

    # Check if this might be an action (create notice)
    action_keywords = ['reportar', 'crear aviso', 'falla', 'fallo', 'se rompio', 'roto', 'rota',
                       'daño', 'dañ', 'parada', 'parado', 'generar aviso', 'registrar',
                       'no funciona', 'no sirve', 'se salio', 'se solto', 'fuera de servicio']
    is_action = any(kw in text.lower() for kw in action_keywords)

    answer = _ask_deepseek(text, context, is_action=is_action)

    # Check if AI returned a JSON action
    if is_action and answer.strip().startswith('{'):
        try:
            # Extract JSON from response (might have markdown)
            json_str = answer.strip()
            if '```' in json_str:
                json_str = json_str.split('```')[1]
                if json_str.startswith('json'):
                    json_str = json_str[4:]
                json_str = json_str.strip()

            action_data = json.loads(json_str)
            if action_data.get('action') == 'create_notice':
                data = action_data.get('data', {})
                code, notice_id, err = _create_notice(app, data)
                if code and notice_id:
                    # Store pending photo state
                    _pending_photos[chat_id] = {
                        "entity_type": "notice",
                        "entity_id": notice_id,
                        "code": code
                    }

                    equip_info = data.get('equipment_tag') or data.get('equipment_name') or '-'
                    comp_info = data.get('component_name') or ''
                    desc = data.get('description', '-')
                    fm = data.get('failure_mode', '')
                    fc = data.get('failure_category', '')

                    _send_message(chat_id, f"""✅ *Aviso creado: {code}*

📋 {desc}
⚙️ Equipo: {equip_info}
🔧 Componente: {comp_info}
⚠️ Modo de falla: {fm or '-'}
🏷️ Tipo: {fc or '-'}
🔴 Criticidad: {data.get('criticality', 'Media')}
📅 Fecha: {date.today().isoformat()}

📷 _Puedes enviar una foto ahora para adjuntarla a este aviso._""")
                    return
                else:
                    _send_message(chat_id, f"❌ Error creando aviso: {err}")
                    return
        except (json.JSONDecodeError, KeyError, IndexError):
            pass  # Not valid JSON, treat as normal response

    _send_message(chat_id, answer)


def start_telegram_bot(app):
    """Start the Telegram bot in a background thread."""
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
                        text = msg.get('text', '')
                        photos = msg.get('photo')
                        caption = msg.get('caption', '')

                        if chat_id and (text or photos):
                            try:
                                _process_message(app, chat_id, text or caption, photos=[photos] if photos else None)
                            except Exception as e:
                                logger.error(f"Bot message error: {e}")
                                _send_message(chat_id, f"Error procesando consulta: {e}")
            except Exception as e:
                logger.error(f"Bot poll error: {e}")
                time.sleep(5)
            time.sleep(POLL_INTERVAL)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    logger.info(f"Telegram bot thread started (polling every {POLL_INTERVAL}s)")
