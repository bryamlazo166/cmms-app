import datetime as dt
import math

from .reporting_helpers import _parse_date_flexible


def _calculate_lubrication_schedule(last_service, frequency_days, warning_days):
    if not last_service:
        return None, 'PENDIENTE'

    service_date = _parse_date_flexible(last_service)
    if not service_date:
        return None, 'PENDIENTE'

    due_date = service_date + dt.timedelta(days=max(1, int(frequency_days or 30)))
    today = dt.date.today()
    warning_delta = max(0, int(warning_days or 0))

    if due_date < today:
        status = 'ROJO'
    elif due_date <= today + dt.timedelta(days=warning_delta):
        status = 'AMARILLO'
    else:
        status = 'VERDE'

    return due_date.isoformat(), status


def _calculate_monitoring_schedule(last_measurement, frequency_days, warning_days):
    if not last_measurement:
        return None, 'PENDIENTE'

    measurement_date = _parse_date_flexible(last_measurement)
    if not measurement_date:
        return None, 'PENDIENTE'

    due_date = measurement_date + dt.timedelta(days=max(1, int(frequency_days or 7)))
    today = dt.date.today()
    warning_delta = max(0, int(warning_days or 0))

    if due_date < today:
        status = 'ROJO'
    elif due_date <= today + dt.timedelta(days=warning_delta):
        status = 'AMARILLO'
    else:
        status = 'VERDE'

    return due_date.isoformat(), status


def _monitoring_semaphore_for_value(point, value):
    try:
        val = float(value)
    except Exception:
        return 'PENDIENTE'

    if point.alarm_min is not None and val < float(point.alarm_min):
        return 'ROJO'
    if point.alarm_max is not None and val > float(point.alarm_max):
        return 'ROJO'

    if point.normal_min is not None and val < float(point.normal_min):
        return 'AMARILLO'
    if point.normal_max is not None and val > float(point.normal_max):
        return 'AMARILLO'

    return 'VERDE'


def _nice_axis_step(raw_step):
    if raw_step <= 0:
        return 1.0

    exponent = int(math.floor(math.log10(raw_step))) if raw_step > 0 else 0
    fraction = raw_step / (10 ** exponent)

    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10

    return nice * (10 ** exponent)
