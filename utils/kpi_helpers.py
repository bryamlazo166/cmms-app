"""Helpers compartidos entre indicadores y produccion vs mantenimiento.

Centraliza el calculo de capacidad por equipo y produccion teorica para
evitar duplicacion entre routes/indicators_routes.py y
routes/production_routes.py.
"""
import datetime as dt


# Capacidades legacy hardcoded — fallback para equipos cuyo capacity_tm aun
# no se ha llenado en la BD. Se mantiene aqui para que sea mas facil de
# encontrar (antes vivia en indicators_routes.py).
EQUIPMENT_CAPACITY = {
    'D1': 8000, 'D2': 8000, 'D3': 8000, 'D4': 6000, 'D5': 7000,
    'D6': 12000, 'D7': 12000, 'D8': 12000, 'D9': 12000,
}

# Areas con calculo de disponibilidad en serie (no ponderado por capacidad)
SERIES_AREAS = {'MOLINO'}


def eq_capacity(eq):
    """Devuelve la capacidad nominal en TM/mes del equipo.
    Prioriza Equipment.capacity_tm de la BD; cae al diccionario legacy si NULL.
    """
    cap_db = getattr(eq, 'capacity_tm', None)
    if cap_db is not None and cap_db > 0:
        return float(cap_db)
    return float(EQUIPMENT_CAPACITY.get(getattr(eq, 'tag', '') or '', 0) or 0)


def eq_yield_factor(eq):
    """Rendimiento materia prima → producto final (0..1). Default 1.0."""
    return float(getattr(eq, 'yield_factor', None) or 1.0)


def eq_jornada(eq):
    """(shift_hours_per_day, work_days_per_week) con defaults seguros."""
    h = float(getattr(eq, 'shift_hours_per_day', None) or 24.0)
    d = int(getattr(eq, 'work_days_per_week', None) or 7)
    return h, d


def calendar_hours_for_equipment(eq, start, end):
    """Horas operativas teoricas del equipo entre [start, end] respetando
    su jornada (shift_hours_per_day, work_days_per_week).
    Si work_days < 7 asume descanso empezando por domingo (orden tipico).
    """
    shift_h, work_days = eq_jornada(eq)
    rest_days = set()
    if work_days < 7:
        order = [6, 5, 0, 1, 2, 3, 4]  # dom, sab, lun, mar, mie, jue, vie
        for i in range(7 - work_days):
            rest_days.add(order[i])
    days_count = 0
    d = start
    while d <= end:
        if d.weekday() not in rest_days:
            days_count += 1
        d += dt.timedelta(days=1)
    return days_count * shift_h


def planned_downtime_for_equipment(Shutdown, eq, start, end, area_id):
    """Suma horas de paradas planificadas que afectan al area del equipo
    en el rango. Para PARCIAL valida que el area este en ShutdownArea.
    """
    try:
        sh_q = Shutdown.query.filter(
            Shutdown.shutdown_date >= start.isoformat(),
            Shutdown.shutdown_date <= end.isoformat(),
            Shutdown.status.in_(['COMPLETADA', 'EN_CURSO', 'PLANIFICADA']),
        )
        total_h = 0.0
        for sh in sh_q.all():
            if (sh.shutdown_type or '').upper() == 'PARCIAL':
                sh_areas = [sa.area_id for sa in (sh.areas or [])]
                if area_id not in sh_areas:
                    continue
            try:
                sh_t, eh = sh.start_time or '00:00', sh.end_time or '00:00'
                sh_h, sh_m = [int(x) for x in (sh_t or '00:00').split(':')]
                eh_h, eh_m = [int(x) for x in (eh or '00:00').split(':')]
                hours = max(0, (eh_h * 60 + eh_m - sh_h * 60 - sh_m) / 60.0)
                total_h += hours
            except Exception:
                total_h += 12.0  # default si formato raro
        return total_h
    except Exception:
        return 0.0
