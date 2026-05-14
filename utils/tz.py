"""Helpers de zona horaria para el CMMS.

Politica: TODO el CMMS opera en hora local de Lima (America/Lima, UTC-5
sin horario de verano). En producción (Render/Linux) se setea TZ via env
var y `datetime.now()` ya devuelve hora Lima automaticamente. Estos
helpers son para:
  - Garantizar Lima time incluso si el SO no respeta TZ (Windows).
  - Obtener datetime tz-aware cuando se necesita explicitar.

Uso recomendado:
  from utils.tz import now_lima, today_lima, now_lima_iso
  ts = now_lima_iso()  # '2026-05-13T14:30:15'
"""
from datetime import datetime, date, timezone, timedelta

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    LIMA_TZ = ZoneInfo("America/Lima")
except Exception:  # pragma: no cover
    # Fallback: Lima es UTC-5 fijo (sin DST desde 1990).
    LIMA_TZ = timezone(timedelta(hours=-5), name="America/Lima")


def now_lima():
    """Datetime tz-aware en hora de Lima."""
    return datetime.now(LIMA_TZ)


def now_lima_naive():
    """Datetime naive cuyo wall-time corresponde a Lima.

    Sirve para columnas de DB que no soportan tz-aware (la mayoria de
    nuestros DateTime).
    """
    return now_lima().replace(tzinfo=None)


def today_lima():
    """Fecha del dia segun reloj de Lima."""
    return now_lima().date()


def now_lima_iso(with_seconds=True):
    """ISO string sin tz para inputs y comparaciones simples.

    `with_seconds=False` => 'YYYY-MM-DDTHH:MM' (formato datetime-local).
    `with_seconds=True`  => 'YYYY-MM-DDTHH:MM:SS'.
    """
    n = now_lima_naive()
    return n.strftime('%Y-%m-%dT%H:%M:%S' if with_seconds else '%Y-%m-%dT%H:%M')


def today_lima_iso():
    """'YYYY-MM-DD' segun Lima."""
    return today_lima().isoformat()


def to_lima(dt):
    """Convierte un datetime (naive UTC, aware, o naive Lima) a aware Lima."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Asumimos que naive datetimes en este sistema son UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LIMA_TZ)
