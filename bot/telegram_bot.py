"""Telegram Bot for CMMS — queries maintenance data via DeepSeek AI."""
import os
import json
import logging
import threading
import time
import requests

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
POLL_INTERVAL = 2  # seconds


def _tg_api(method, **kwargs):
    """Call Telegram Bot API."""
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}'
    r = requests.post(url, json=kwargs, timeout=30)
    return r.json()


def _send_message(chat_id, text):
    """Send a message to a Telegram chat."""
    # Telegram max message length is 4096
    for i in range(0, len(text), 4000):
        _tg_api('sendMessage', chat_id=chat_id, text=text[i:i+4000], parse_mode='Markdown')


def _query_cmms(app, path):
    """Query the CMMS API internally."""
    with app.test_client() as c:
        # Login as admin for API access
        from models import User
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            if admin:
                c.post('/login', data={'username': admin.username, 'password': ''})
                # Use session directly since we can't know the password
                # Instead, use Flask test client with login bypass
        r = c.get(path)
        if r.status_code == 200:
            return r.json
        return {"error": f"HTTP {r.status_code}"}


def _get_cmms_context(app):
    """Build a context string with current CMMS data for the AI."""
    ctx_parts = []

    with app.app_context():
        try:
            from models import WorkOrder, MaintenanceNotice, Equipment, Area, Line
            from models import LubricationPoint, MonitoringPoint, InspectionRoute

            # KPIs summary
            total_ots = WorkOrder.query.count()
            open_ots = WorkOrder.query.filter(WorkOrder.status != 'Cerrada').count()
            closed_ots = WorkOrder.query.filter_by(status='Cerrada').count()
            total_notices = MaintenanceNotice.query.count()
            pending_notices = MaintenanceNotice.query.filter_by(status='Pendiente').count()

            ctx_parts.append(f"RESUMEN CMMS:")
            ctx_parts.append(f"- OTs totales: {total_ots} (abiertas: {open_ots}, cerradas: {closed_ots})")
            ctx_parts.append(f"- Avisos totales: {total_notices} (pendientes: {pending_notices})")

            # Equipment list
            equipments = Equipment.query.order_by(Equipment.name).all()
            if equipments:
                eq_list = ', '.join(f"{e.tag or ''} {e.name} (id:{e.id})" for e in equipments[:20])
                ctx_parts.append(f"- Equipos: {eq_list}")

            # Recent OTs
            recent = WorkOrder.query.order_by(WorkOrder.id.desc()).limit(10).all()
            if recent:
                ctx_parts.append("\nULTIMAS 10 OTs:")
                for ot in recent:
                    eq = Equipment.query.get(ot.equipment_id) if ot.equipment_id else None
                    eq_name = f"{eq.tag or ''} {eq.name}" if eq else '-'
                    ctx_parts.append(f"  {ot.code} | {ot.maintenance_type or '-'} | {ot.status} | {eq_name} | {ot.description or '-'}")

            # Overdue points
            lub_overdue = LubricationPoint.query.filter_by(is_active=True, semaphore_status='ROJO').count()
            insp_overdue = InspectionRoute.query.filter_by(is_active=True, semaphore_status='ROJO').count()
            mon_overdue = MonitoringPoint.query.filter_by(is_active=True, semaphore_status='ROJO').count()

            if lub_overdue or insp_overdue or mon_overdue:
                ctx_parts.append(f"\nPUNTOS VENCIDOS (ROJO):")
                if lub_overdue: ctx_parts.append(f"  Lubricacion: {lub_overdue}")
                if insp_overdue: ctx_parts.append(f"  Inspeccion: {insp_overdue}")
                if mon_overdue: ctx_parts.append(f"  Monitoreo: {mon_overdue}")

            # Areas
            areas = Area.query.all()
            if areas:
                ctx_parts.append(f"\nAREAS: {', '.join(a.name for a in areas)}")

        except Exception as e:
            ctx_parts.append(f"Error cargando datos: {e}")

    return '\n'.join(ctx_parts)


def _ask_deepseek(question, cmms_context):
    """Send question + CMMS context to DeepSeek and get response."""
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json',
    }

    system_prompt = f"""Eres el asistente de mantenimiento del CMMS Pro, un sistema de gestion de mantenimiento industrial.
Responde en español, de forma concisa y profesional.
Usa los datos reales del sistema para responder.
Si no tienes la informacion, dilo claramente.
No inventes datos. Usa solo lo que se te proporciona.

DATOS ACTUALES DEL SISTEMA:
{cmms_context}
"""

    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': question},
        ],
        'max_tokens': 1000,
        'temperature': 0.3,
    }

    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            return f"Error DeepSeek: {r.status_code} {r.text[:200]}"
        data = r.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        return f"Error consultando IA: {e}"


def _process_message(app, chat_id, text):
    """Process an incoming Telegram message."""
    text = text.strip()

    # Simple commands
    if text.lower() in ('/start', '/help', 'hola', 'ayuda'):
        _send_message(chat_id, """*CMMS Pro Bot* 🏭

Puedo responder consultas sobre tu planta de mantenimiento:

• _Cuantas OTs abiertas hay?_
• _Que equipos tienen fallas recurrentes?_
• _Cual es la disponibilidad del digestor #1?_
• _Hay puntos de lubricacion vencidos?_
• _Resumen del estado de la planta_

Solo escribe tu pregunta en lenguaje natural.""")
        return

    # Query AI with CMMS context
    _send_message(chat_id, "⏳ Consultando datos...")
    context = _get_cmms_context(app)
    answer = _ask_deepseek(text, context)
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
                        if chat_id and text:
                            try:
                                _process_message(app, chat_id, text)
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
