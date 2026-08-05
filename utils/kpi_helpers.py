"""Helpers compartidos entre indicadores y produccion vs mantenimiento.

Centraliza el calculo de capacidad por equipo y produccion teorica para
evitar duplicacion entre routes/indicators_routes.py,
routes/production_routes.py y routes/diagnostico_routes.py.

CAPACIDAD REAL DE LA PLANTA
---------------------------
La planta procesa por lotes: cada digestor se llena N veces al dia hasta un
% de su capacidad fisica. De ahi sale la unica cifra que importa para valorar
una parada:

    TM/dia del equipo = capacidad de la llenada (kg) x % llenado x llenadas/dia / 1000
    TM/h  del equipo  = TM/dia / horas operativas del dia

Ejemplo real: digestor #1 = 8000 kg x 75% x 4 llenadas = 24 TM/dia = 1 TM/h.

Las TM que se dejan de producir por una parada se calculan SIEMPRE con la
capacidad del equipo que paro, nunca con el rendimiento de toda el area: si
para un digestor de 9, se pierde lo de ese digestor, no lo de la planta.
"""
import datetime as dt
import re


# Capacidad de la llenada (kg) de cada digestor. Fallback para equipos cuyo
# batch_capacity_kg aun no se ha llenado en la BD.
# OJO: historicamente este diccionario se llamaba EQUIPMENT_CAPACITY y se leia
# como "TM/mes", lo que inflaba x11 las toneladas perdidas. Son KG POR LLENADA.
BATCH_CAPACITY_KG = {
    'D1': 8000, 'D2': 8000, 'D3': 8000, 'D4': 6000, 'D5': 7000,
    'D6': 12000, 'D7': 12000, 'D8': 12000, 'D9': 12000,
}
EQUIPMENT_CAPACITY = BATCH_CAPACITY_KG  # alias legacy

# Regimen de operacion por defecto de los equipos por lotes.
DEFAULT_FILL_PCT = 75.0        # los digestores se llenan al 75%
DEFAULT_BATCHES_PER_DAY = 4.0  # 4 llenadas en 24 h (ciclo de 6 h)

DAYS_PER_MONTH = 30.4375  # promedio (365.25/12), para pasar TM/dia <-> TM/mes

# Areas con calculo de disponibilidad en serie (no ponderado por capacidad)
SERIES_AREAS = {'MOLINO'}


def eq_batch_kg(eq):
    """Capacidad de una llenada en kg, o 0 si el equipo no trabaja por lotes."""
    kg = getattr(eq, 'batch_capacity_kg', None)
    if kg is not None and kg > 0:
        return float(kg)
    return float(BATCH_CAPACITY_KG.get(getattr(eq, 'tag', '') or '', 0) or 0)


def eq_batch_regime(eq):
    """(% de llenado, llenadas por dia) con los defaults de planta."""
    fill = getattr(eq, 'fill_pct', None)
    batches = getattr(eq, 'batches_per_day', None)
    return (float(fill) if fill is not None and fill > 0 else DEFAULT_FILL_PCT,
            float(batches) if batches is not None and batches > 0 else DEFAULT_BATCHES_PER_DAY)


def eq_capacity_tm_day(eq):
    """TM de materia prima que el equipo procesa en un dia completo.

    Orden de prioridad:
      1. Equipo por lotes  -> kg de la llenada x % llenado x llenadas/dia
      2. capacity_tm_day   -> capturado a mano en Alcance de Indicadores
      3. capacity_tm       -> legacy en TM/mes, se reparte entre los dias
    """
    kg = eq_batch_kg(eq)
    if kg > 0:
        fill, batches = eq_batch_regime(eq)
        return kg * (fill / 100.0) * batches / 1000.0
    d = getattr(eq, 'capacity_tm_day', None)
    if d is not None and d > 0:
        return float(d)
    m = getattr(eq, 'capacity_tm', None)
    if m is not None and m > 0:
        return float(m) / DAYS_PER_MONTH
    return 0.0


def eq_is_batch(eq):
    return eq_batch_kg(eq) > 0


def eq_input_tph(eq):
    """TM/h de materia prima del equipo (capacidad diaria / jornada)."""
    cap_day = eq_capacity_tm_day(eq)
    if cap_day <= 0:
        return 0.0
    shift_h, _ = eq_jornada(eq)
    return cap_day / shift_h if shift_h > 0 else 0.0


def eq_output_tph(eq):
    """TM/h de producto final (materia prima x rendimiento del equipo)."""
    return eq_input_tph(eq) * eq_yield_factor(eq)


def eq_capacity(eq):
    """Capacidad nominal en TM/mes del equipo (compatibilidad con el codigo
    que razona en meses). Derivada de la capacidad diaria real."""
    return eq_capacity_tm_day(eq) * DAYS_PER_MONTH


def _normalize_name(name):
    """'PERCOLADOR #2' -> 'PERCOLADOR', 'TRITURADOR 100 HP' -> 'TRITURADOR'.

    Sirve para detectar equipos gemelos (que trabajan en paralelo) dentro de
    un area: si hay 2 molinos, cada uno carga la mitad de la planta.
    """
    s = (name or '').upper().strip()
    s = re.sub(r'[#Nn]?\s*\d+([.,]\d+)?\s*(HP|KW|TM|BHP)?', ' ', s)
    return re.sub(r'\s+', ' ', s).strip() or (name or '').upper().strip()


def plant_capacity_tm_day(equipments):
    """Capacidad de proceso de la planta en TM/dia de materia prima.

    Es la suma de los equipos por lotes (digestores) que estan EN SERVICIO y
    dentro del alcance de KPIs: son el cuello de botella y definen cuanto
    puede entrar a planta. Un digestor en overhaul no suma capacidad.

    Si la planta no trabaja por lotes, se toma la capacidad del equipo mas
    grande configurado: los equipos en serie llevan el flujo completo, asi que
    ese es el techo de lo que puede procesarse.
    """
    total = 0.0
    mayor = 0.0
    for eq in equipments:
        if not getattr(eq, 'include_in_kpi', True) or not getattr(eq, 'in_service', True):
            continue
        cap = eq_capacity_tm_day(eq)
        if eq_is_batch(eq):
            total += cap
        mayor = max(mayor, cap)
    return total if total > 0 else mayor


def plant_yield_factor(equipments):
    """Rendimiento materia prima -> producto final de la planta.

    Se toma el de los digestores (donde se define el rendimiento del proceso)
    ponderado por capacidad. Se usa para toda la cadena porque la capacidad de
    cada equipo esta expresada en materia prima equivalente. Si no hay equipos
    por lotes, se pondera con todos los que tengan capacidad.
    """
    def _ponderado(solo_batch):
        num = den = 0.0
        for eq in equipments:
            if not getattr(eq, 'in_service', True):
                continue
            if solo_batch and not eq_is_batch(eq):
                continue
            cap = eq_capacity_tm_day(eq)
            if cap <= 0:
                continue
            num += eq_yield_factor(eq) * cap
            den += cap
        return (num / den) if den > 0 else None

    return _ponderado(True) or _ponderado(False) or 1.0


def suggest_capacities(equipments, lines):
    """Sugiere la capacidad TM/dia de los equipos que no trabajan por lotes.

    Reglas, en orden:
      1. Si en su LINEA hay equipos por lotes, hereda esa capacidad (el
         transportador que alimenta al digestor #1 vale lo que el digestor #1).
      2. Si no, se reparte la capacidad de planta entre sus equipos gemelos
         del area (2 molinos -> mitad de planta cada uno; equipo unico en
         serie -> planta completa: si para, para todo).

    Devuelve {equipment_id: tm_dia_sugerida}. No escribe en la BD.
    """
    plant = plant_capacity_tm_day(equipments)
    line_area = {l.id: l.area_id for l in lines}

    batch_por_linea = {}
    for eq in equipments:
        if eq_is_batch(eq) and getattr(eq, 'in_service', True):
            batch_por_linea[eq.line_id] = (batch_por_linea.get(eq.line_id, 0.0)
                                           + eq_capacity_tm_day(eq))

    # Gemelos por area: (area_id, nombre normalizado) -> cuantos son
    gemelos = {}
    for eq in equipments:
        if eq_is_batch(eq) or not getattr(eq, 'include_in_kpi', True):
            continue
        key = (line_area.get(eq.line_id), _normalize_name(eq.name))
        gemelos[key] = gemelos.get(key, 0) + 1

    out = {}
    for eq in equipments:
        if eq_is_batch(eq) or not getattr(eq, 'include_in_kpi', True):
            continue
        heredada = batch_por_linea.get(eq.line_id, 0.0)
        if heredada > 0:
            out[eq.id] = round(heredada, 3)
            continue
        n = gemelos.get((line_area.get(eq.line_id), _normalize_name(eq.name)), 1)
        out[eq.id] = round(plant / max(n, 1), 3) if plant > 0 else 0.0
    return out


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
