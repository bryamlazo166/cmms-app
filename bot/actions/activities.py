"""Accion: consultar actividades realizadas en un rango de fechas.

Devuelve un resumen ejecutivo (OTs cerradas, avisos, lubricaciones e
inspecciones ejecutadas) listo para imprimir en Telegram.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def _parse_date(value, fallback=None):
    if not value:
        return fallback
    try:
        if isinstance(value, date):
            return value
        s = str(value)[:10]
        y, m, d = s.split('-')
        return date(int(y), int(m), int(d))
    except Exception:
        return fallback


def _resolve_range(data):
    """Acepta start_date/end_date explicitos o un preset 'window' (last_7d,
    last_30d, this_week, last_week, this_month). Devuelve (start, end)."""
    today = date.today()
    window = (data.get('window') or '').lower().strip()
    if window in ('last_7d', '7d', 'last_week_rolling'):
        return today - timedelta(days=6), today
    if window in ('last_30d', '30d', 'last_month_rolling'):
        return today - timedelta(days=29), today
    if window == 'this_week':
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if window == 'last_week':
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start, end
    if window == 'this_month':
        start = today.replace(day=1)
        return start, today
    s = _parse_date(data.get('start_date'))
    e = _parse_date(data.get('end_date'))
    if s and e:
        return (s, e) if s <= e else (e, s)
    if s and not e:
        return s, today
    if e and not s:
        return e - timedelta(days=6), e
    # Default: ultimos 7 dias
    return today - timedelta(days=6), today


def query_activities_range(app, data):
    """Consulta agregada de actividades en el rango.

    Llama internamente al endpoint /api/reports/weekly-plan via test_client
    (asi reusamos la logica completa de filtros y conteo).

    Returns: (summary_text, web_url, error | None).
    """
    start, end = _resolve_range(data or {})
    try:
        client = app.test_client()
        # scope=all incluye Plan, FueraPlan y Generales para tener vision completa
        path = (f"/api/reports/weekly-plan?start_date={start.isoformat()}"
                f"&end_date={end.isoformat()}&window=custom&scope=PLAN,FUERA_PLAN,GENERAL")
        resp = client.get(path)
        if resp.status_code != 200:
            return None, None, f"HTTP {resp.status_code}"
        payload = resp.get_json() or {}
    except Exception as e:
        logger.exception("query_activities_range failed")
        return None, None, str(e)

    summary = payload.get('summary') or {}
    items = payload.get('items') or []
    lubrications = payload.get('lubrications') or []
    inspections = payload.get('inspections') or []

    days = max((end - start).days + 1, 1)
    closed = summary.get('closed', 0)
    in_progress = sum(1 for i in items if (i.get('status') or '').lower() == 'en progreso')
    open_count = sum(1 for i in items if (i.get('status') or '').lower() in {'abierta', 'programada'})
    blocked = summary.get('blocked', 0)
    preventive = summary.get('preventive', 0)
    corrective = summary.get('corrective', 0)

    insp_ok = sum(1 for i in inspections if i.get('overall_result') == 'OK')
    insp_findings = sum(1 for i in inspections if i.get('overall_result') == 'CON_HALLAZGOS')
    insp_notexec = sum(1 for i in inspections if i.get('overall_result') == 'NO_EJECUTADA')

    lub_anomalies = sum(1 for l in lubrications if l.get('leak_detected') or l.get('anomaly_detected'))

    lines = [
        f"📋 *Actividades del {start.strftime('%d/%m')} al {end.strftime('%d/%m/%Y')}* ({days} dias)",
        "",
        "🔧 *ORDENES DE TRABAJO*",
        f"  • Cerradas: *{closed}* ({preventive} preventivas, {corrective} correctivas)",
        f"  • En progreso: *{in_progress}*",
        f"  • Abiertas/Programadas: *{open_count}*",
    ]
    if blocked:
        lines.append(f"  • 🔒 Bloqueadas por logistica: *{blocked}*")

    lines.extend([
        "",
        "🛢️ *LUBRICACIONES*",
        f"  • Puntos atendidos: *{len(lubrications)}*",
    ])
    if lub_anomalies:
        lines.append(f"  • ⚠ Con anomalia/fuga: *{lub_anomalies}*")

    lines.extend([
        "",
        "🔍 *INSPECCIONES*",
        f"  • Rutas ejecutadas: *{len(inspections)}*"
        + (f" — {insp_ok} OK, {insp_findings} con hallazgos, {insp_notexec} no ejecutadas"
           if inspections else ""),
    ])

    web_url = f"/reportes?start={start.isoformat()}&end={end.isoformat()}"
    lines.append("")
    lines.append("📊 Ver detalle completo en el modulo Reportes (rango ya aplicado).")

    return "\n".join(lines), web_url, None
