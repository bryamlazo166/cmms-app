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


def eq_is_batch(eq):
    return eq_batch_kg(eq) > 0


def eq_produces(eq):
    """True si la parada de este equipo cuesta toneladas de producto.

    En esta planta transforman producto los digestores (por lotes), los
    secadores y los molinos. Los transportadores, ciclones, percoladores,
    fajas y vahos son auxiliares: mueven o acondicionan, no producen harina,
    y contarlos multiplicaba las toneladas perdidas de un mismo flujo.
    """
    if eq_is_batch(eq):
        return True
    return bool(getattr(eq, 'is_production_unit', False))


def eq_capacity_basis(eq):
    """En que esta medida la capacidad del equipo.

      'MP'       -> toneladas de materia prima que entran. Son los digestores:
                    ellos GENERAN la harina, asi que hay que aplicarles el
                    rendimiento para saber cuanta harina sale.
      'PRODUCTO' -> toneladas de harina que pasan por el equipo. Son los
                    secadores y los molinos: no generan nada, PROCESAN la
                    harina que ya salio de los digestores, asi que su
                    capacidad ya esta en harina y no se vuelve a multiplicar
                    por el rendimiento.
    """
    return 'MP' if eq_is_batch(eq) else 'PRODUCTO'


def eq_stage(eq):
    """Etapa del proceso a la que pertenece el equipo productivo.

    Las etapas van en SERIE (coccion -> secado -> molienda), asi que la
    planta produce lo que permita la mas limitada de las tres.
    """
    return 'COCCION' if eq_is_batch(eq) else _normalize_name(eq.name)


def eq_capacity_tm_day(eq):
    """TM de materia prima que el equipo procesa en un dia completo.

    Solo tienen capacidad los equipos productivos: un auxiliar devuelve 0
    aunque tenga un valor guardado (asi no resta toneladas ni pondera la
    disponibilidad, pero el dato queda por si se le marca como productivo).

    Orden de prioridad:
      1. Equipo por lotes  -> kg de la llenada x % llenado x llenadas/dia
      2. capacity_tm_day   -> capturado a mano en Alcance de Indicadores
      3. capacity_tm       -> legacy en TM/mes, se reparte entre los dias
    """
    if not eq_produces(eq):
        return 0.0
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


def eq_input_tph(eq):
    """TM/h que pasan por el equipo, en la unidad de su capacidad."""
    cap_day = eq_capacity_tm_day(eq)
    if cap_day <= 0:
        return 0.0
    shift_h, _ = eq_jornada(eq)
    return cap_day / shift_h if shift_h > 0 else 0.0


def eq_harina_tm_day(eq, plant_yield=None):
    """TM de HARINA al dia que deja de salir si este equipo para.

    Un digestor genera: sus TM de materia prima se convierten en harina con
    el rendimiento. Un secador o un molino ya trabaja sobre harina, asi que
    su capacidad se toma tal cual.
    """
    cap = eq_capacity_tm_day(eq)
    if cap <= 0:
        return 0.0
    if eq_capacity_basis(eq) == 'MP':
        return cap * (eq_yield_factor(eq) if plant_yield is None else plant_yield)
    return cap


def eq_output_tph(eq, plant_yield=None):
    """TM/h de harina que se dejan de producir mientras el equipo esta parado."""
    dia = eq_harina_tm_day(eq, plant_yield)
    if dia <= 0:
        return 0.0
    shift_h, _ = eq_jornada(eq)
    return dia / shift_h if shift_h > 0 else 0.0


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


def plant_stages(equipments):
    """Capacidad de harina de cada etapa: {etapa: {tm_dia, equipos, ...}}.

    Solo suman los equipos EN SERVICIO: si el molino #1 esta desactivado, la
    molienda queda a la mitad y la planta entera con el, porque las etapas
    van en serie.
    """
    rend = plant_yield_factor(equipments)
    etapas = {}
    for eq in equipments:
        if not eq_produces(eq) or not getattr(eq, 'include_in_kpi', True):
            continue
        st = etapas.setdefault(eq_stage(eq), {
            'etapa': eq_stage(eq), 'tm_dia': 0.0, 'equipos': 0,
            'operativos': 0, 'fuera_servicio': [],
            'base': eq_capacity_basis(eq),
        })
        st['equipos'] += 1
        if getattr(eq, 'in_service', True):
            st['operativos'] += 1
            st['tm_dia'] += eq_harina_tm_day(eq, rend)
        else:
            st['fuera_servicio'].append(getattr(eq, 'tag', None) or eq.name)
    return etapas


def plant_harina_tm_day(equipments):
    """TM de harina al dia que puede sacar la planta.

    Es la etapa mas limitada: coccion, secado y molienda estan en serie, asi
    que la planta no produce mas de lo que permita la mas corta de las tres.
    """
    etapas = plant_stages(equipments)
    caps = [s['tm_dia'] for s in etapas.values() if s['tm_dia'] > 0]
    return min(caps) if caps else 0.0


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


# Equipos que transforman producto ademas de los digestores: definen una
# etapa del proceso y si paran, esa etapa deja de producir.
DEFAULT_PRODUCTION_NAMES = {'SECADOR', 'MOLINO'}


def suggest_production_units(equipments):
    """IDs de los equipos que deberian marcarse como productivos.

    Los digestores ya lo son por trabajar por lotes; aqui se detectan los
    secadores y los molinos por su nombre. Todo lo demas queda auxiliar.
    """
    return {eq.id for eq in equipments
            if not eq_is_batch(eq)
            and getattr(eq, 'include_in_kpi', True)
            and _normalize_name(eq.name) in DEFAULT_PRODUCTION_NAMES}


def suggest_capacities(equipments, lines=None):
    """Sugiere la capacidad de los equipos productivos que no son de lotes:
    en esta planta, los secadores y los molinos.

    Su capacidad va en TM de HARINA (procesan lo que generaron los
    digestores), y se reparte la harina que sale de coccion entre los equipos
    de la etapa: con 2 molinos, cada uno se lleva la mitad. Asi, si uno falla
    y solo trabaja el otro, se pierde la mitad de la molienda — que es lo que
    pasa en planta.

    Los auxiliares no reciben capacidad: su parada no resta toneladas.
    Devuelve {equipment_id: tm_dia_sugerida}. No escribe en la BD.
    """
    rend = plant_yield_factor(equipments)
    # Harina que entrega la coccion: es lo que las etapas siguientes deben
    # ser capaces de procesar.
    harina_coccion = sum(eq_harina_tm_day(eq, rend) for eq in equipments
                         if eq_is_batch(eq) and getattr(eq, 'in_service', True)
                         and getattr(eq, 'include_in_kpi', True))

    def productivo(eq):
        return (eq_produces(eq) and not eq_is_batch(eq)
                and getattr(eq, 'include_in_kpi', True))

    # Equipos de cada etapa (los 2 molinos, los 2 secadores...)
    por_etapa = {}
    for eq in equipments:
        if productivo(eq):
            por_etapa[eq_stage(eq)] = por_etapa.get(eq_stage(eq), 0) + 1

    out = {}
    for eq in equipments:
        if not productivo(eq):
            continue
        n = por_etapa.get(eq_stage(eq), 1)
        out[eq.id] = round(harina_coccion / max(n, 1), 3) if harina_coccion > 0 else 0.0
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
