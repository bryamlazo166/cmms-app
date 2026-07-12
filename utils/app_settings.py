"""Lectura de configuracion global (tabla app_settings).

Valores clave/valor simples con default. Cache corto en memoria para no
consultar la BD en cada request (los reportes leen week_start_day varias
veces por pagina).
"""
import time

_cache = {}
_CACHE_TTL = 60  # segundos


def get_setting(key, default=None):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[1] < _CACHE_TTL:
        return hit[0]
    try:
        from models import AppSetting
        s = AppSetting.query.get(key)
        value = s.value if (s and s.value is not None) else default
    except Exception:
        value = default
    _cache[key] = (value, now)
    return value


def set_setting_cache(key, value):
    """Actualiza el cache tras un PUT (evita servir el valor viejo 60s)."""
    _cache[key] = (value, time.time())


def get_week_start_day():
    """Dia de inicio del corte semanal: 0=lunes ... 6=domingo. Default 0."""
    try:
        return int(get_setting('week_start_day', '0')) % 7
    except (TypeError, ValueError):
        return 0
