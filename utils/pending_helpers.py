"""Helpers del modulo de Pendientes.

Los usan tanto las rutas web (routes/pending_routes.py) como el bot
(bot/actions/pending.py) para que un pendiente anotado por Telegram y uno
creado desde el CMMS se comporten igual: mismo correlativo, mismo parseo de
plazo y mismo cierre con bitacora.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta

PENDING_OPEN = 'Pendiente'
PENDING_DONE = 'Hecho'
PENDING_CANCELLED = 'Anulado'
PENDING_STATUSES = (PENDING_OPEN, PENDING_DONE, PENDING_CANCELLED)

PRIORITIES = ('Alta', 'Normal', 'Baja')


def _strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s or '')
                   if unicodedata.category(c) != 'Mn')


def next_pending_code(db, text_module):
    """Siguiente correlativo PEND-XXXX (mismo estilo que AV-/OT-)."""
    max_id = db.session.execute(
        text_module("SELECT COALESCE(MAX(id), 0) FROM pending_tasks")).scalar() or 0
    return f"PEND-{str(int(max_id) + 1).zfill(4)}"


# ── Plazo en lenguaje natural ────────────────────────────────────────────────
#
# El pendiente se escribe de corrido ("comprar el reten del D3 para el viernes")
# y el plazo sale del mismo texto. Si no hay plazo, el pendiente no vence: la
# fecha es opcional a proposito.

_WEEKDAYS = {
    'lunes': 0, 'martes': 1, 'miercoles': 2, 'jueves': 3,
    'viernes': 4, 'sabado': 5, 'domingo': 6,
}

_UNIT_DAYS = {'d': 1, 'dia': 1, 'dias': 1,
              'w': 7, 'semana': 7, 'semanas': 7,
              'm': 30, 'mes': 30, 'meses': 30}

_NUMBER_WORDS = {
    'un': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
    'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10, 'quince': 15,
}


def parse_due_phrase(raw, today=None):
    """Extrae el plazo del texto. Devuelve (due_date ISO | None, texto limpio).

    Reconoce: 'hoy', 'manana', 'pasado manana', 'en 2 semanas', 'en 3 dias',
    'en un mes', 'el viernes', '30d', '2w', '1.5m', '2026-06-15' y '15/06'.
    Lo que consume se quita del texto para que la descripcion no lo repita.
    """
    if not raw:
        return None, ''
    today = today or date.today()
    text = raw.strip()
    low = _strip_accents(text.lower())
    due = None
    cut = None   # (inicio, fin) del fragmento consumido

    def _take(m, value):
        nonlocal due, cut
        if due is None:
            due = value
            cut = (m.start(), m.end())

    m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', low)
    if m:
        try:
            _take(m, date.fromisoformat(m.group(1)))
        except ValueError:
            pass

    if due is None:
        m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', low)
        if m:
            d_, mo = int(m.group(1)), int(m.group(2))
            y = int(m.group(3) or today.year)
            if y < 100:
                y += 2000
            try:
                cand = date(y, mo, d_)
                if not m.group(3) and cand < today:
                    cand = date(y + 1, mo, d_)   # "15/06" ya pasado = el del ano que viene
                _take(m, cand)
            except ValueError:
                pass

    if due is None:
        m = re.search(r'\bpasado\s+manana\b', low)
        if m:
            _take(m, today + timedelta(days=2))

    if due is None:
        m = re.search(r'\bmanana\b', low)
        if m:
            _take(m, today + timedelta(days=1))

    if due is None:
        m = re.search(r'\bhoy\b', low)
        if m:
            _take(m, today)

    if due is None:
        # "en 2 semanas", "en un mes", "dentro de 3 dias"
        m = re.search(r'\b(?:en|dentro\s+de|para\s+dentro\s+de)\s+'
                      r'(\d+(?:[.,]\d+)?|' + '|'.join(_NUMBER_WORDS) + r')\s+'
                      r'(dias?|semanas?|meses|mes)\b', low)
        if m:
            qty_raw = m.group(1)
            qty = _NUMBER_WORDS.get(qty_raw)
            if qty is None:
                qty = float(qty_raw.replace(',', '.'))
            unit_raw = m.group(2)
            unit = ('mes' if unit_raw.startswith('mes')
                    else 'semana' if unit_raw.startswith('semana') else 'dia')
            days = _UNIT_DAYS[unit] * qty
            _take(m, today + timedelta(days=int(round(days))))

    if due is None:
        # Formato corto del comando /recordar: 30d, 2w, 1.5m
        m = re.search(r'\b(\d+(?:[.,]\d+)?)\s*([dwm])\b', low)
        if m:
            days = _UNIT_DAYS[m.group(2)] * float(m.group(1).replace(',', '.'))
            _take(m, today + timedelta(days=int(round(days))))

    if due is None:
        m = re.search(r'\b(?:el|este|proximo|para\s+el)\s+(' + '|'.join(_WEEKDAYS) + r')\b', low)
        if m:
            delta = (_WEEKDAYS[m.group(1)] - today.weekday()) % 7 or 7
            _take(m, today + timedelta(days=delta))

    clean = text
    if cut:
        clean = (text[:cut[0]] + ' ' + text[cut[1]:])
    clean = re.sub(r'\s{2,}', ' ', clean).strip(' ,.;:-')
    return (due.isoformat() if due else None), clean


# ── Prioridad desde el texto ────────────────────────────────────────────────

def infer_priority(raw):
    """'urgente'/'critico' -> Alta; 'cuando se pueda' -> Baja; si no, Normal."""
    low = _strip_accents((raw or '').lower())
    if re.search(r'\b(urgente|urge|critico|prioridad\s+alta|cuanto\s+antes|ya\b)', low):
        return 'Alta'
    if re.search(r'\b(cuando\s+se\s+pueda|sin\s+apuro|baja\s+prioridad|no\s+urge)\b', low):
        return 'Baja'
    return 'Normal'


# ── Cierre ──────────────────────────────────────────────────────────────────

def close_payload(status, who, comment, when=None):
    """Campos de cierre para pasar a HECHO o ANULADO.

    El pendiente nunca se borra: se marca, sale de la lista activa y queda la
    bitacora de quien lo cerro, cuando y con que comentario.
    """
    if status not in (PENDING_DONE, PENDING_CANCELLED):
        raise ValueError(f"status de cierre invalido: {status}")
    return {
        'status': status,
        'done_date': (when or date.today()).isoformat() if not isinstance(when, str) else when,
        'done_by': (who or '').strip() or None,
        'done_comment': (comment or '').strip() or None,
        'done_at': datetime.utcnow(),
    }


def reopen_payload():
    """Devuelve un pendiente cerrado a la lista activa, borrando su cierre."""
    return {'status': PENDING_OPEN, 'done_date': None, 'done_by': None,
            'done_comment': None, 'done_at': None}


def overdue_days(due_date, today=None):
    """Dias de atraso (>0 vencido, 0 vence hoy, <0 aun no vence, None sin plazo)."""
    if not due_date:
        return None
    try:
        d = date.fromisoformat(str(due_date)[:10])
    except ValueError:
        return None
    return ((today or date.today()) - d).days
