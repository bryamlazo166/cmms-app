"""Indicadores de Mantenimiento — presentacion para gerencia.

Corre EN PARALELO al Diagnostico Mensual, no lo reemplaza. La diferencia es
deliberada: aqui NO se habla de toneladas. Ni las no producidas ni las
elaboradas. El unico dato que entra desde produccion es la meta, y solo para
responder una pregunta de mantenimiento:

    ¿cuanta disponibilidad necesito en cada area para que la planta cumpla?

De ahi en adelante todo se expresa en horas y porcentajes, que es el lenguaje
sobre el que mantenimiento puede actuar.

DOS VISTAS, porque el informe se presenta cada semana y al cierre del mes:

  · Vista SEMANAL — el eje son las semanas del mes hasta la que se elige.
    Al cerrar la semana 1 se presenta S1; al cerrar la semana 2 se ven S1 y
    S2 juntas, y asi. Ademas de la barra de cada semana se lleva la linea
    ACUMULADA (del dia 1 hasta el fin de esa semana), que es la que responde
    "¿como va el mes?".
  · Vista MENSUAL — el mes cerrado contra los meses anteriores.

El orden de las laminas sigue el informe que la jefatura ya venia presentando:
    01 Disponibilidad requerida para cumplir la meta
    02 Disponibilidad
    03 MTBF (contra el TEP, tiempo efectivo del periodo)
    04 MTTR (tiempo medio de reparacion)
    05 Cumplimiento de mantenimiento preventivo
    06 Cumplimiento de mantenimiento correctivo programado
    07 Confiabilidad

En pantalla se muestran los indicadores GLOBALES (planta y area). El detalle
—equipo por equipo y las ordenes que generaron el paro— sale al hacer click,
que es cuando alguien pregunta "¿y eso por que?".
"""
import calendar
import datetime as dt
import time

from flask import jsonify, render_template, request, send_file


# Areas del proceso productivo, en el orden del flujo. Las demas areas
# (calderas, subestacion, vahos...) se calculan igual pero van despues.
AREAS_PROCESO = ['COCCION', 'SECADO', 'MOLINO']

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre']

# El programa preventivo no son solo las OTs. La lubricacion, las rutas de
# inspeccion y el monitoreo de condicion son mantenimiento preventivo (tareas
# sistematicas basadas en tiempo) y viven en sus propias tablas, con su
# frecuencia y sus ejecuciones, sin pasar por WorkOrder. Contar solo las OTs
# dejaba fuera casi todo el trabajo preventivo: en julio 2026 fueron 33 OTs
# contra 396 ejecuciones de lubricacion.
#
# No se funden en un solo numero a proposito: la lubricacion aplastaria a las
# OTs y el cumplimiento dejaria de decir si los preventivos mecanicos se
# hicieron. Se apilan por fuente, con su porcentaje cada una y el total.
FUENTES_PREVENTIVAS = [
    ('OT', 'OT preventiva / predictiva'),
    ('LUB', 'Lubricacion'),
    ('INS', 'Rutas de inspeccion'),
    ('MON', 'Monitoreo de condicion'),
]

# Que un programa este cargado no significa que este en vigor. Las rutas de
# inspeccion pueden tener sus 22 rutas creadas y alguna ejecucion de prueba
# mientras se implementan: cobrarles el plan teorico hunde el cumplimiento por
# trabajo que todavia no se le exige a nadie.
#
# No se resuelve con una heuristica sobre los datos (una ejecucion suelta no
# distingue "programa en marcha" de "prueba"). Es una decision de la jefatura,
# asi que se guarda como tal y se muestra en la propia lamina: quien presenta
# declara que fuentes entran, y se ve en pantalla.
SETTING_FUENTES = 'preventivo_fuentes'
FUENTES_POR_DEFECTO = 'OT,LUB'

# Que laminas se presentan.
#
# No todas sirven todos los meses: una lamina cuyo dato todavia no se termina
# de cargar —la carga de trabajo necesita la asignacion de personal— resta mas
# de lo que aporta si se proyecta a medias. Se elige antes de presentar y la
# decision se guarda en la BD, no en el navegador, para que valga igual desde
# la laptop de la sala de reuniones. Las laminas ocultas desaparecen tambien
# del indice de la portada y las visibles se renumeran, para no dejar huecos.
LAMINAS = [
    ('requerida', 'Disponibilidad requerida para cumplir la meta'),
    ('disponibilidad', 'Disponibilidad'),
    ('mtbf', 'MTBF — Tiempo Medio Entre Fallas'),
    ('mttr', 'MTTR — Tiempo Medio de Reparacion'),
    ('preventivo', 'Cumplimiento del Programa Preventivo'),
    ('correctivo', 'Cumplimiento de Mantenimiento Correctivo Programado'),
    ('carga', 'Carga de trabajo — en que se va el recurso'),
    ('confiabilidad', 'Confiabilidad'),
    ('pareto', 'Modos de falla y equipos que concentran las paradas'),
]
SETTING_LAMINAS = 'presentacion_laminas_ocultas'

# Clase de trabajo: en que se va el personal de mantenimiento.
#
# Se separa del tipo de mantenimiento porque responden a preguntas distintas.
# Un proyecto o una obra de infraestructura consumen al mismo tecnico que
# tendria que estar haciendo el preventivo, pero NO son mantenimiento del
# activo: no entran al cumplimiento preventivo ni cuentan como falla en el
# MTBF/MTTR (su paro es planificado). Lo que si hacen es competir por horas,
# y esa competencia es la que hay que poder mostrar.
CLASES_TRABAJO = [
    ('MANTENIMIENTO', 'Mantenimiento del activo',
     ('preventivo', 'predictivo', 'correctivo', 'correctiva', 'corrective',
      'ronda diaria')),
    ('MEJORA', 'Mejoras', ('mejora',)),
    ('PROYECTO', 'Proyectos', ('proyecto', 'proyectos')),
    ('INFRAESTRUCTURA', 'Infraestructura', ('infraestructura', 'obra civil')),
]
_CLASE_DE_TIPO = {t: c for c, _n, tipos in CLASES_TRABAJO for t in tipos}
NOMBRE_CLASE = {c: n for c, n, _t in CLASES_TRABAJO}


def clase_de_trabajo(maintenance_type):
    """Clase a la que pertenece una OT segun su tipo. Lo no reconocido cae en
    mantenimiento, que es lo conservador: no infla los proyectos."""
    return _CLASE_DE_TIPO.get((maintenance_type or '').strip().lower(),
                              'MANTENIMIENTO')
MESES_CORTO = ['', 'ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN',
               'JUL', 'AGO', 'SET', 'OCT', 'NOV', 'DIC']

# Quien ejecuta el trabajo. El maestro de tecnicos tiene tambien gente dada de
# baja y perfiles que no van a campo; medir la capacidad contra los 23 nombres
# registrados infla la cuadrilla y hace ver el backlog mucho mas sano de lo
# que es. Los que toman una herramienta son los mecanicos y los electricistas.
ESPECIALIDADES_EJECUTORAS = ('MECANIC', 'ELECTRIC')

# Jornada legal en Peru: 6 dias x 8 h. Es lo que convierte el backlog de horas
# a semanas de trabajo, que es como se lee (SMRP: sano entre 2 y 4 semanas).
HORAS_SEMANA_TECNICO = 48.0

# Estados que sacan a la orden del backlog sin haberse ejecutado.
ANULADAS = ('anulada', 'anulado', 'cancelada', 'cancelado', 'rechazada')


def es_ejecutor(especialidad):
    """Si esa especialidad ejecuta trabajo en campo."""
    e = (especialidad or '').strip().upper()
    return any(e.startswith(x) for x in ESPECIALIDADES_EJECUTORAS)


def _kpi(base, ots, tep, modo, horizonte):
    """Indicadores de un conjunto de OTs, con el catalogo de paradas.

    El mapa de paradas NO es opcional: sin el, toda orden ejecutada dentro de
    una parada se asume planificada, y las paradas que la jefatura marco como
    AVERIA (is_planned = False) se descontaban de la disponibilidad inherente
    como si fueran mantenimiento programado. La pagina de Indicadores ya lo
    pasaba y esta presentacion no, asi que los dos tableros no daban lo mismo
    para el mismo mes.
    """
    from routes.indicators_routes import _calc_indicators
    return _calc_indicators(ots, tep, base['shutdowns'], mode=modo,
                            unplanned_shutdown_ids=base['sh_no_plan'],
                            reliability_hours=horizonte)


def _duracion_parada(sh):
    """Horas que duro una parada, segun el motor de indicadores."""
    from routes.indicators_routes import _shutdown_duration
    return _shutdown_duration(sh) if sh is not None else 0.0


def _paro_h(ot):
    """Horas que la orden tuvo el equipo detenido. Mismo criterio que el motor
    de indicadores: si no se cargo el downtime se usa la duracion real, y solo
    cuenta si la OT declara que causo paro."""
    if not ot.get('caused_downtime'):
        return 0.0
    return float(ot.get('downtime_hours') or ot.get('real_duration') or 0)


def _planificado(base, ot):
    """Si el paro de esa orden se considera planificado.

    Manda la parada: una orden ejecutada dentro de una parada hereda su
    clasificacion, igual que en el motor de indicadores. Fuera de una parada
    decide la propia orden (correctivo = averia).
    """
    from routes.indicators_routes import _ot_downtime_planned
    sid = ot.get('shutdown_id')
    if sid:
        return sid not in base['sh_no_plan']
    return _ot_downtime_planned(ot)


def _descripcion(texto):
    """La descripcion como se lee en la reunion.

    Las OTs traen pegado al final el metadato del formulario
    ("| [Modo de falla: Rotura] | [Tipo: Mecanica]"), que en pantalla solo hace
    ruido: el modo de falla se muestra en su propia columna.
    """
    t = (texto or '').split('|')[0].strip()
    return t[:200] if t else '—'


def _modo(ot):
    """Modo de falla de la orden. Si el campo no se lleno, se rescata del
    metadato que quedo escrito en la descripcion."""
    m = (ot.get('failure_mode') or '').strip()
    if not m:
        d = ot.get('description') or ''
        marca = 'Modo de falla:'
        if marca in d:
            m = d.split(marca, 1)[1].split(']')[0].strip()
    return m.upper() if m else ''


def _legible(nombre, linea, tag):
    """Nombre del equipo como lo entiende quien no vive en el CMMS.

    El tag (D6, SECA-SECA2, TH1-ENF2) no dice nada en una reunion de gerencia,
    pero el nombre solo tampoco alcanza: hay siete equipos que se llaman
    "SECADOR" o "TH1" y solo la linea los distingue. Se compone nombre + linea,
    salvo cuando uno ya contiene al otro.
    """
    n = (nombre or '').strip()
    l = (linea or '').strip()
    # "LINEA DIGESTOR #6" es la linea; el equipo es el "DIGESTOR #6" que hay
    # dentro. Sin quitar el prefijo, el digestor se presentaria como su propia
    # linea y el nombre saldria mas largo sin decir nada nuevo.
    if l.upper().startswith('LINEA '):
        l = l[6:].strip()
    if not n:
        return l or (tag or '').strip() or 'Equipo sin nombre'
    if not l:
        return n
    if n.upper() == l.upper():
        return n
    if n.upper() in l.upper():
        return l                      # "SECADOR" dentro de "SECADOR #2"
    if l.upper() in n.upper():
        return n
    return n + ' — ' + l         # "TH1" del "ENFRIADOR #2"

# La lectura de catalogo + ordenes es lo unico que toca la BD y no cambia
# entre un cambio de mes, de modo o de vista. Se cachea unos segundos para
# que mover los selectores de la presentacion sea instantaneo.
_CACHE_TTL_S = 90.0
_CACHE = {'t': 0.0, 'data': None}


def _invalidar_cache():
    _CACHE['t'], _CACHE['data'] = 0.0, None


def register_presentacion_routes(app, db, logger):
    from models import (AppSetting, Area, Equipment, InspectionExecution,
                        InspectionRoute, Line, LubricationExecution,
                        LubricationPoint, MonitoringPoint, MonitoringReading,
                        OTPersonnel, ProductionGoal, Shutdown, Technician,
                        WorkOrder)

    def _cuadrilla():
        """La cuadrilla que realmente ejecuta: mecanicos y electricistas de
        alta. Es el divisor de la capacidad y del backlog."""
        filas = (Technician.query
                 .with_entities(Technician.specialty, Technician.is_active)
                 .all())
        por_esp, ejecutores = {}, 0
        for esp, activo in filas:
            if not activo:
                continue
            nombre = (esp or 'SIN ESPECIALIDAD').strip().upper()
            if es_ejecutor(nombre):
                ejecutores += 1
                por_esp[nombre] = por_esp.get(nombre, 0) + 1
        return {
            'registrados': len(filas),
            'activos': sum(1 for _e, a in filas if a),
            'ejecutores': ejecutores,
            'detalle': sorted(({'especialidad': k, 'tecnicos': v}
                               for k, v in por_esp.items()),
                              key=lambda x: -x['tecnicos']),
            'horas_semana': HORAS_SEMANA_TECNICO,
            'capacidad_semana_h': round(ejecutores * HORAS_SEMANA_TECNICO, 1),
        }

    def _fuentes_en_vigor():
        """Fuentes que la jefatura declara en vigor. Se lee en cada peticion
        —no se cachea— para que al cambiarlas el numero se corrija de
        inmediato, incluso si responde otro worker de gunicorn."""
        validos = {c for c, _ in FUENTES_PREVENTIVAS}
        try:
            fila = db.session.get(AppSetting, SETTING_FUENTES)
            crudo = (fila.value if fila and fila.value else FUENTES_POR_DEFECTO)
        except Exception:
            crudo = FUENTES_POR_DEFECTO
        sel = {c.strip().upper() for c in crudo.split(',') if c.strip()} & validos
        sel.add('OT')                # las ordenes siempre entran al indicador
        return sel

    def _laminas_ocultas():
        """Laminas que quien presenta decidio no mostrar. Se lee en cada
        peticion, igual que las fuentes."""
        validas = {c for c, _ in LAMINAS}
        try:
            fila = db.session.get(AppSetting, SETTING_LAMINAS)
            crudo = (fila.value if fila and fila.value else '')
        except Exception:
            crudo = ''
        return {c.strip() for c in crudo.split(',') if c.strip()} & validas

    # ── Utilidades de periodo ────────────────────────────────────────────

    def _mes_anterior(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"

    def _meses_atras(ym, n):
        out, cur = [], ym
        for _ in range(n):
            out.append(cur)
            cur = _mes_anterior(cur)
        out.reverse()
        return out

    def _limites(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])

    def _label(ym):
        return f"{MESES[int(ym[5:7])]} {ym[:4]}"

    def _corto(ym):
        return MESES_CORTO[int(ym[5:7])]

    def _bloques_semana(ym):
        """Semanas del mes como bloques de 7 dias desde el dia 1.

        No se usan semanas ISO a proposito: el informe es mensual y una
        semana ISO se reparte entre dos meses, con lo que la suma de las
        semanas dejaria de cuadrar con el mes. Si el ultimo bloque queda
        con menos de 3 dias se absorbe en el anterior, para no presentar
        una "semana" de un dia.
        """
        dias = _limites(ym)[1].day
        bloques, d = [], 1
        while d <= dias:
            h = min(d + 6, dias)
            bloques.append((d, h))
            d = h + 1
        if len(bloques) > 1 and (bloques[-1][1] - bloques[-1][0] + 1) < 3:
            ultimo = bloques.pop()
            bloques[-1] = (bloques[-1][0], ultimo[1])
        return bloques

    def _periodo(ini, fin, key, label, nombre):
        dias = (fin - ini).days + 1
        return {'key': key, 'label': label, 'nombre': nombre,
                'ini': ini, 'fin': fin, 'dias': dias, 'tep': dias * 24,
                'desde': ini.isoformat(), 'hasta': fin.isoformat()}

    def _periodos(month, vista, semana, n_meses):
        """Eje X de toda la presentacion."""
        if vista == 'semana':
            bloques = _bloques_semana(month)
            n = len(bloques) if not semana else max(1, min(semana, len(bloques)))
            y, m = int(month[:4]), int(month[5:7])
            out = []
            for i, (a, b) in enumerate(bloques[:n], start=1):
                out.append(_periodo(
                    dt.date(y, m, a), dt.date(y, m, b),
                    f'{month}-S{i}', f'S{i}',
                    f'Semana {i} · {a}–{b} de {MESES[m]}'))
            return out
        out = []
        for ym in _meses_atras(month, n_meses):
            ini, fin = _limites(ym)
            out.append(_periodo(ini, fin, ym, _corto(ym), _label(ym)))
        return out

    def _acumulados(periodos):
        """Para la vista semanal: del dia 1 hasta el cierre de cada semana."""
        if len(periodos) < 2:
            return []
        ini = periodos[0]['ini']
        return [_periodo(ini, p['fin'], p['key'] + '-ACUM', p['label'],
                         f"Acumulado hasta {p['nombre'].split('·')[-1].strip()}")
                for p in periodos]

    # ── Datos base: una sola lectura de BD para todo ─────────────────────

    def _leer_base():
        from utils.kpi_helpers import (eq_harina_tm_day, eq_produces,
                                       plant_yield_factor)
        areas = {a.id: a for a in Area.query.all()}
        lines = {l.id: l for l in Line.query.all()}
        equipos = Equipment.query.all()
        rend = plant_yield_factor(equipos)

        # Capacidad de harina por equipo y por area (solo lo que produce y
        # esta en servicio). Es el peso de la ponderacion y la base de la
        # disponibilidad requerida.
        cap_eq, cap_area, cap_linea = {}, {}, {}
        eq_de_area, nombre_eq, linea_de_eq = {}, {}, {}
        for e in equipos:
            linea_nom = lines[e.line_id].name if e.line_id in lines else ''
            nombre_eq[e.id] = {'nombre': e.name or '', 'tag': e.tag or '',
                               'legible': _legible(e.name, linea_nom, e.tag)}
            if not e.include_in_kpi or e.line_id not in lines:
                continue
            cap = (eq_harina_tm_day(e, rend)
                   if eq_produces(e) and e.in_service else 0.0)
            cap_eq[e.id] = cap
            aid = lines[e.line_id].area_id
            cap_area[aid] = cap_area.get(aid, 0.0) + cap
            cap_linea[e.line_id] = cap_linea.get(e.line_id, 0.0) + cap
            eq_de_area.setdefault(aid, []).append(e.id)
            linea_de_eq[e.id] = e.line_id

        # UNA sola pasada por las ordenes: de ahi salen las cerradas (para
        # los indicadores) y las programadas (para el cumplimiento).
        filas = WorkOrder.query.with_entities(
            WorkOrder.id, WorkOrder.code, WorkOrder.description,
            WorkOrder.maintenance_type, WorkOrder.status, WorkOrder.equipment_id,
            WorkOrder.shutdown_id, WorkOrder.caused_downtime,
            WorkOrder.downtime_hours, WorkOrder.downtime_planned,
            WorkOrder.real_duration, WorkOrder.scheduled_date,
            WorkOrder.real_start_date, WorkOrder.real_end_date,
            WorkOrder.failure_mode, WorkOrder.estimated_duration).all()

        cerradas, programadas, pendientes = [], [], []
        for f in filas:
            if f.scheduled_date:
                programadas.append({'fecha': str(f.scheduled_date)[:10],
                                    'maintenance_type': f.maintenance_type,
                                    'status': f.status})
            if f.status != 'Cerrada':
                # Lo que queda abierto es el backlog: trabajo ya comprometido
                # que sigue compitiendo por las horas de la cuadrilla.
                if (f.status or '').strip().lower() not in ANULADAS:
                    eqp = nombre_eq.get(f.equipment_id, {})
                    pendientes.append({
                        'id': f.id, 'code': f.code, 'status': f.status,
                        'maintenance_type': f.maintenance_type,
                        'equipo': eqp.get('legible', ''),
                        'estimado_h': (float(f.estimated_duration)
                                       if f.estimated_duration else None),
                        'scheduled_date': (str(f.scheduled_date)[:10]
                                           if f.scheduled_date else None),
                    })
                continue
            eq = nombre_eq.get(f.equipment_id, {})
            cerradas.append({
                'id': f.id, 'code': f.code, 'description': f.description,
                'maintenance_type': f.maintenance_type, 'status': f.status,
                'equipment_id': f.equipment_id, 'shutdown_id': f.shutdown_id,
                'caused_downtime': f.caused_downtime,
                'downtime_hours': f.downtime_hours,
                'downtime_planned': f.downtime_planned,
                'real_duration': f.real_duration,
                'scheduled_date': f.scheduled_date,
                'equipment_name': eq.get('nombre', ''),
                'equipment_tag': eq.get('tag', ''),
                'equipo_legible': eq.get('legible', ''),
                'failure_mode': f.failure_mode,
                'fecha': str(f.real_end_date or f.real_start_date
                             or f.scheduled_date or '')[:10],
            })

        metas = {}
        for g in ProductionGoal.query.all():
            if g.area_id and g.monthly_target_tons and g.goal_period:
                metas.setdefault(str(g.goal_period)[:7], {})[g.area_id] = \
                    float(g.monthly_target_tons)

        # Rutinas preventivas que no pasan por WorkOrder. Un punto sobre un
        # equipo fuera de servicio (overhaul) no exige servicio: si se
        # contara, el programa se incumpliria por un equipo que no opera.
        fuera = {e.id for e in equipos if not e.in_service}

        def rutinas(Punto, Ejecucion, col_fecha):
            puntos = [(p.frequency_days, p.equipment_id) for p in
                      Punto.query.with_entities(Punto.frequency_days,
                                                Punto.equipment_id)
                      .filter(Punto.is_active.is_(True)).all()
                      if p.equipment_id not in fuera]
            fechas = sorted(str(r[0])[:10] for r in
                            Ejecucion.query.with_entities(col_fecha).all() if r[0])
            # Una fuente entra al indicador desde su PRIMERA ejecucion, no
            # antes: un programa que se esta implementando ya tiene sus puntos
            # cargados, y contarle el plan teorico hundiria el cumplimiento por
            # trabajo que todavia no se le pide a nadie. El dia que se registre
            # la primera ejecucion empieza a medirse solo.
            return {'puntos': puntos, 'fechas': fechas,
                    'desde': fechas[0] if fechas else None}

        # Horas-hombre REALES: salen de ot_personnel.hours_worked, que es lo
        # que se carga en "Personal que ejecuto" al cerrar la OT.
        #
        # NO se usa real_duration x tech_count: se verifico que real_duration
        # es exactamente (fin - inicio) en las 361 OTs cerradas con fechas, o
        # sea tiempo TRANSCURRIDO, no trabajado. Un traslado de equipos que
        # tuvo la OT abierta 42 dias daria 1 010 horas-hombre de una persona.
        hh_ot, esp_ot = {}, {}
        filas_p = (OTPersonnel.query
                   .with_entities(OTPersonnel.work_order_id,
                                  OTPersonnel.hours_worked,
                                  OTPersonnel.specialty).all())
        for wo_id, horas, esp in filas_p:
            if horas and horas > 0:
                hh_ot[wo_id] = hh_ot.get(wo_id, 0.0) + float(horas)
                clave = (wo_id, (esp or 'SIN ESPECIALIDAD').upper())
                esp_ot[clave] = esp_ot.get(clave, 0.0) + float(horas)

        rutinas_prev = {
            'LUB': rutinas(LubricationPoint, LubricationExecution,
                           LubricationExecution.execution_date),
            'INS': rutinas(InspectionRoute, InspectionExecution,
                           InspectionExecution.execution_date),
            'MON': rutinas(MonitoringPoint, MonitoringReading,
                           MonitoringReading.reading_date),
        }

        linea_critica = {lid: bool(getattr(l, 'stops_area', False))
                         for lid, l in lines.items()}

        # Catalogo de paradas: cuanto duro cada una y si fue programada o una
        # averia. Son pocas filas y hacen falta en cada calculo.
        paradas = {sh.id: sh for sh in Shutdown.query.all()}
        no_plan = {i for i, sh in paradas.items()
                   if getattr(sh, 'is_planned', True) is False}

        return {'areas': areas, 'lines': lines, 'equipos': equipos,
                'rendimiento': rend, 'cap_eq': cap_eq, 'cap_area': cap_area,
                'cap_linea': cap_linea, 'linea_de_eq': linea_de_eq,
                'linea_critica': linea_critica,
                'eq_de_area': eq_de_area, 'ots': cerradas,
                'programadas': programadas, 'metas': metas,
                'rutinas': rutinas_prev, 'hh_ot': hh_ot, 'esp_ot': esp_ot,
                'pendientes': pendientes, 'nombre_eq': nombre_eq,
                'shutdowns': paradas, 'sh_no_plan': no_plan,
                'cuadrilla': _cuadrilla()}

    def _base():
        ahora = time.monotonic()
        if (not app.config.get('TESTING') and _CACHE['data'] is not None
                and ahora - _CACHE['t'] < _CACHE_TTL_S):
            return _CACHE['data']
        datos = _leer_base()
        _CACHE['t'], _CACHE['data'] = ahora, datos
        return datos

    # ── Motor de indicadores ─────────────────────────────────────────────

    def _por_equipo(ots, ini, fin):
        """Indice equipo → OTs del periodo. La fecha de la OT es la de cierre
        real; asi las semanas de un mes suman exactamente el mes."""
        idx = {}
        for o in ots:
            if o['fecha'] and ini <= o['fecha'] <= fin and o['equipment_id']:
                idx.setdefault(o['equipment_id'], []).append(o)
        return idx

    def _ots_de_linea(base, eq_ids, idx, lid):
        """OTs de todos los equipos de la linea, vistas como si fueran de UNA
        sola maquina.

        Renombrar el equipo no es un truco de conveniencia: dentro de una
        linea los equipos van EN SERIE. Si para el TH de salida del secador
        #1, esa linea de secado para completa, igual que si parara el
        secador. Al presentarlas con el mismo equipment_id, _calc_indicators
        las suma como paros de la linea y consolida en uno solo los trabajos
        que compartieron parada, que es justo lo que ocurre en planta.
        """
        salida = []
        for eid in eq_ids:
            if base['linea_de_eq'].get(eid) != lid:
                continue
            for o in idx.get(eid, []):
                copia = dict(o)
                copia['equipment_id'] = -1000000 - lid
                salida.append(copia)
        return salida

    def _ponderar(base, eq_ids, idx, tep, modo, horizonte):
        """Indicadores de un conjunto de equipos, PONDERADOS POR CAPACIDAD.

        Dos niveles, porque la planta tiene dos topologias:

          · DENTRO de una linea los equipos van EN SERIE. La linea SECADOR #1
            son el secador y 7 auxiliares (TH alimentador, TH de salida, TH
            fino, ciclon de finos...): si cualquiera para, esa linea de
            secado para. Por eso la linea se mide como una sola maquina y no
            solo por su secador.
          · ENTRE lineas van EN PARALELO, asi que se ponderan por capacidad.
            Sumar las horas de paro de los 9 digestores como si estuvieran en
            serie es lo que antes devolvia disponibilidades imposibles.
        """
        num = {'disponibilidad': 0.0, 'mtbf': 0.0, 'confiabilidad': 0.0}
        peso = 0.0
        paro_total, fallas, n_ots = 0.0, 0, 0

        # Totales crudos: horas-equipo y averias, equipo a equipo
        for eid in eq_ids:
            ind = _kpi(base, idx.get(eid, []), tep, modo, horizonte)
            paro_total += ind['downtime_hours']
            fallas += ind['failure_count']
            n_ots += ind['total_ots']

        # Disponibilidad, MTBF y confiabilidad: una medicion por LINEA
        for lid in {base['linea_de_eq'].get(e) for e in eq_ids} - {None}:
            cap = base['cap_linea'].get(lid, 0.0)
            if cap <= 0:
                continue                    # linea auxiliar: no pondera
            ind = _kpi(base, _ots_de_linea(base, eq_ids, idx, lid), tep,
                       modo, horizonte)
            num['disponibilidad'] += ind['availability'] * cap
            num['mtbf'] += ind['mtbf'] * cap
            num['confiabilidad'] += ind['reliability'] * cap
            peso += cap

        if peso > 0:
            res = {k: round(v / peso, 2) for k, v in num.items()}
            res['ponderado'] = True
        else:
            # Sin lineas con capacidad: se mide el conjunto directamente
            todas = [o for eid in eq_ids for o in idx.get(eid, [])]
            ind = _kpi(base, todas, tep, modo, horizonte)
            res = {'disponibilidad': ind['availability'], 'mtbf': ind['mtbf'],
                   'confiabilidad': ind['reliability'], 'ponderado': False}

        # Lineas auxiliares CRITICAS: no tienen equipo productivo, pero por
        # ellas pasa todo el flujo del area, asi que van EN SERIE con ella.
        # La zaranda y el ciclon de ensaque detienen la molienda porque
        # despues de ellos se ensaca; los percoladores o el purificador no,
        # porque hay by-pass. Se marca linea por linea en Alcance de
        # Indicadores, no se adivina.
        criticas = [lid for lid in {base['linea_de_eq'].get(e) for e in eq_ids} - {None}
                    if base['cap_linea'].get(lid, 0.0) <= 0
                    and base['linea_critica'].get(lid)]
        res['lineas_criticas'] = len(criticas)
        if criticas and peso > 0:
            ots_crit = []
            for lid in criticas:
                for o in _ots_de_linea(base, eq_ids, idx, lid):
                    copia = dict(o)
                    copia['equipment_id'] = -2000000   # todas, una sola maquina
                    ots_crit.append(copia)
            ind_c = _kpi(base, ots_crit, tep, modo, horizonte)
            res['disp_criticas'] = ind_c['availability']
            res['horas_criticas'] = ind_c['downtime_hours']
            # Composicion en serie: el area produce solo si el bloque en
            # paralelo Y las lineas criticas estan operando.
            res['disponibilidad'] = round(
                res['disponibilidad'] * ind_c['availability'] / 100, 2)
            res['confiabilidad'] = round(
                res['confiabilidad'] * ind_c['reliability'] / 100, 2)
            # En serie las tasas de falla se suman: 1/MTBF = Σ 1/MTBFi
            if res['mtbf'] > 0 and ind_c['mtbf'] > 0:
                res['mtbf'] = round(1 / (1 / res['mtbf'] + 1 / ind_c['mtbf']), 2)
        # MTTR: cuanto cuesta reparar una averia, no se pondera
        res['mttr'] = round(paro_total / fallas, 2) if fallas else 0.0
        res['fallas'] = fallas
        res['horas_paro'] = round(paro_total, 2)
        res['ots'] = n_ots
        res['tep'] = tep
        return res

    def _areas_kpi(base):
        """Areas que entran al informe, ordenadas por el flujo del proceso."""
        out = []
        for aid, area in base['areas'].items():
            if not area.include_in_kpi or not base['eq_de_area'].get(aid):
                continue
            nom = (area.name or '').upper()
            orden = AREAS_PROCESO.index(nom) if nom in AREAS_PROCESO else 99
            out.append({'id': aid, 'nombre': area.name, 'orden': orden})
        out.sort(key=lambda x: (x['orden'], x['nombre']))
        return out

    def _punto(base, eq_ids, per, modo, horizonte, idx=None):
        i = idx if idx is not None else _por_equipo(base['ots'], per['desde'], per['hasta'])
        d = _ponderar(base, eq_ids, i, per['tep'], modo, horizonte)
        d.update(key=per['key'], label=per['label'], nombre=per['nombre'],
                 desde=per['desde'], hasta=per['hasta'], dias=per['dias'])
        return d

    # ── Cumplimiento (preventivo y correctivo programado) ────────────────

    def _plan_rutina(rut, dias):
        """Servicios que el programa exige en el periodo.

        Cada punto activo pide `dias del periodo / frecuencia` servicios: un
        punto de 15 dias pide 2,07 en un mes de 31 y 0,47 en una semana. Es
        el plan teorico que declara la frecuencia configurada, y por eso la
        lamina lo dice explicitamente: no es una lista de tareas emitidas.
        """
        total = 0.0
        for freq, _eq in rut['puntos']:
            if freq and freq > 0:
                total += dias / freq
        return total

    def _cumplimiento(base, per, en_vigor=None):
        """Programadas vs ejecutadas del periodo, separando preventivo de
        correctivo programado — los dos indicadores del informe.

        El preventivo suma las cuatro fuentes (OT, lubricacion, inspeccion y
        monitoreo) y ademas las devuelve desglosadas, para que el total no
        esconda de donde sale.
        """
        ini, fin = per['desde'], per['hasta']
        en_vigor = en_vigor if en_vigor is not None else {'OT', 'LUB'}
        prev_prog = prev_ejec = corr_prog = corr_term = 0
        for o in base['programadas']:
            if not (ini <= o['fecha'] <= fin):
                continue
            mt = (o['maintenance_type'] or '').strip().lower()
            cerrada = (o['status'] == 'Cerrada')
            if mt in ('preventivo', 'predictivo'):
                prev_prog += 1
                prev_ejec += 1 if cerrada else 0
            elif mt == 'correctivo':
                # Correctivo PROGRAMADO: el que tenia fecha planificada
                corr_prog += 1
                corr_term += 1 if cerrada else 0

        fuentes = [{'codigo': 'OT', 'nombre': dict(FUENTES_PREVENTIVAS)['OT'],
                    'programadas': prev_prog, 'ejecutadas': prev_ejec,
                    'activa': True, 'desde': None,
                    'pct': round(prev_ejec / prev_prog * 100, 1) if prev_prog else None}]
        for codigo, nombre in FUENTES_PREVENTIVAS[1:]:
            rut = base['rutinas'].get(codigo) or {'puntos': [], 'fechas': [],
                                                  'desde': None}
            plan = _plan_rutina(rut, per['dias'])
            ejec = sum(1 for f in rut['fechas'] if ini <= f <= fin)
            if not plan and not ejec:
                continue                       # fuente sin usar, no se muestra
            # Un programa que la jefatura no declara en vigor se lista aparte,
            # con su plan a la vista, pero no arrastra el cumplimiento.
            activa = codigo in en_vigor
            fuentes.append({
                'codigo': codigo, 'nombre': nombre,
                'programadas': int(round(plan)) if activa else 0,
                'ejecutadas': ejec if activa else 0,
                'plan_teorico': int(round(plan)),
                'puntos': len(rut['puntos']),
                'activa': activa, 'desde': rut['desde'],
                'pct': round(ejec / plan * 100, 1) if (activa and plan) else None,
            })

        tot_prog = sum(f['programadas'] for f in fuentes if f['activa'])
        tot_ejec = sum(f['ejecutadas'] for f in fuentes if f['activa'])
        return {
            'preventivo': {
                'programadas': tot_prog, 'ejecutadas': tot_ejec,
                'pct': round(tot_ejec / tot_prog * 100, 1) if tot_prog else None,
                'fuentes': fuentes,
                # El indicador que se venia presentando, para no perder la
                # serie historica al ampliar el alcance
                'solo_ot': {'programadas': prev_prog, 'ejecutadas': prev_ejec,
                            'pct': round(prev_ejec / prev_prog * 100, 1) if prev_prog else None},
            },
            'correctivo': {'programados': corr_prog, 'terminados': corr_term,
                           'pct': round(corr_term / corr_prog * 100, 1) if corr_prog else None},
        }

    # ── Backlog: trabajo comprometido que todavia no se ejecuta ──────────

    def _backlog(base):
        """Cuantas semanas de trabajo tiene la cuadrilla por delante.

            backlog (semanas) = horas pendientes / (tecnicos x 48 h)

        El divisor son los mecanicos y electricistas de alta, no el maestro
        completo: contra los 23 nombres registrados el backlog sale cuatro
        veces mas sano de lo que es. Referencia SMRP: entre 2 y 4 semanas es
        sano; por debajo sobra capacidad, por encima el preventivo se empieza
        a desplazar solo.

        No todas las ordenes abiertas tienen duracion estimada. Las que no la
        tienen se valorizan con el promedio de las que si —es preferible a
        contarlas como cero, que seria decir que no cuestan nada— y la
        cobertura del dato se informa siempre.
        """
        pend = base['pendientes']
        cuad = base['cuadrilla']
        con_est = [o for o in pend if o['estimado_h']]
        horas_reg = sum(o['estimado_h'] for o in con_est)
        prom = (horas_reg / len(con_est)) if con_est else 0.0
        sin_est = len(pend) - len(con_est)
        horas_tot = horas_reg + prom * sin_est
        cap = cuad['capacidad_semana_h']

        por_clase = {}
        for o in pend:
            c = clase_de_trabajo(o.get('maintenance_type'))
            d = por_clase.setdefault(c, {'clase': c, 'nombre': NOMBRE_CLASE[c],
                                         'ots': 0, 'horas': 0.0})
            d['ots'] += 1
            d['horas'] += o['estimado_h'] or prom
        for d in por_clase.values():
            d['horas'] = round(d['horas'], 1)

        # Lo mas viejo primero: una orden programada hace meses que sigue
        # abierta explica el backlog mejor que cualquier promedio.
        hoy = dt.date.today().isoformat()
        atrasadas = sorted((o for o in pend if o['scheduled_date']),
                           key=lambda o: o['scheduled_date'])[:8]
        return {
            'ots': len(pend),
            'ots_con_estimado': len(con_est),
            'cobertura_pct': (round(len(con_est) / len(pend) * 100, 1)
                              if pend else None),
            'horas_registradas': round(horas_reg, 1),
            'horas_estimadas': round(horas_tot, 1),
            'horas_promedio_ot': round(prom, 1),
            'semanas': round(horas_tot / cap, 1) if cap else None,
            'tecnicos': cuad['ejecutores'],
            'capacidad_semana_h': cap,
            'horas_semana': cuad['horas_semana'],
            'por_clase': sorted(por_clase.values(), key=lambda d: -d['horas']),
            'vencidas': sum(1 for o in pend if o['scheduled_date']
                            and o['scheduled_date'] < hoy),
            'mas_antiguas': [{'code': o['code'], 'equipo': o['equipo'],
                              'programada': o['scheduled_date'],
                              'estado': o['status']} for o in atrasadas],
        }

    # ── Carga de trabajo: en que se va el personal ───────────────────────

    def _carga(base, per):
        """Horas-hombre por clase de trabajo en el periodo.

        Responde "¿en que se me va el recurso?": cuanto se fue en mantener el
        activo y cuanto en proyectos y obra, que consumen al mismo tecnico que
        deberia estar haciendo el preventivo.

        La fuente es ot_personnel.hours_worked — las horas que se cargan al
        cerrar la OT en "Personal que ejecuto". Se informa siempre la
        COBERTURA: si solo el 12 % de las OTs tiene personal cargado, el
        numero es una muestra y hay que decirlo, no presentarlo como total.
        """
        ini, fin = per['desde'], per['hasta']
        por_clase = {c: {'clase': c, 'nombre': n, 'ots': 0, 'ots_con_horas': 0,
                         'horas': 0.0}
                     for c, n, _t in CLASES_TRABAJO}
        por_esp = {}
        for o in base['ots']:
            if not (o['fecha'] and ini <= o['fecha'] <= fin):
                continue
            c = clase_de_trabajo(o.get('maintenance_type'))
            d = por_clase[c]
            d['ots'] += 1
            h = base['hh_ot'].get(o['id'])
            if h:
                d['ots_con_horas'] += 1
                d['horas'] += h
                for (wo, esp), v in base['esp_ot'].items():
                    if wo == o['id']:
                        por_esp[esp] = por_esp.get(esp, 0.0) + v

        clases = []
        for c, _n, _t in CLASES_TRABAJO:
            d = por_clase[c]
            if not d['ots']:
                continue
            d['horas'] = round(d['horas'], 1)
            d['cobertura_pct'] = (round(d['ots_con_horas'] / d['ots'] * 100, 1)
                                  if d['ots'] else None)
            clases.append(d)

        tot_h = round(sum(c['horas'] for c in clases), 1)
        tot_ots = sum(c['ots'] for c in clases)
        tot_con = sum(c['ots_con_horas'] for c in clases)
        for c in clases:
            c['pct_horas'] = round(c['horas'] / tot_h * 100, 1) if tot_h else None

        # Cuanto del recurso NO fue a mantener el activo
        fuera = sum(c['horas'] for c in clases if c['clase'] != 'MANTENIMIENTO')
        return {
            'clases': clases,
            'horas_total': tot_h,
            'ots_total': tot_ots,
            'ots_con_horas': tot_con,
            'cobertura_pct': round(tot_con / tot_ots * 100, 1) if tot_ots else None,
            'horas_fuera_mantenimiento': round(fuera, 1),
            'pct_fuera_mantenimiento': round(fuera / tot_h * 100, 1) if tot_h else None,
            'especialidades': sorted(
                ({'especialidad': k, 'horas': round(v, 1)} for k, v in por_esp.items()),
                key=lambda x: -x['horas']),
            'cuadrilla': base['cuadrilla'],
            'backlog': _backlog(base),
        }

    # ── Disponibilidad requerida ─────────────────────────────────────────

    def _requerida(base, per, indicadores):
        """Cuanta disponibilidad necesita cada area para cumplir la meta.

        La meta viene en toneladas, pero NO se muestra: solo se usa para
        despejar el porcentaje y el presupuesto de horas de parada, que es
        con lo que mantenimiento puede trabajar.

            disponibilidad requerida = meta del periodo / capacidad del periodo
            presupuesto de parada    = (1 - requerida) x horas del periodo

        En vista semanal la meta se prorratea por dias. El porcentaje sale
        igual (meta y capacidad escalan juntas); lo que cambia, y es lo util,
        es el presupuesto de horas: en una semana son 168 h, no 744.
        """
        fin = dt.date.fromisoformat(per['hasta'])
        ym = f"{fin.year}-{fin.month:02d}"
        dias_mes = calendar.monthrange(fin.year, fin.month)[1]
        metas = base['metas'].get(ym, {})
        horas = per['tep']

        out = []
        for aid, datos in indicadores.items():
            area = base['areas'][aid]
            cap_dia = base['cap_area'].get(aid, 0.0)
            if cap_dia <= 0 or aid not in metas:
                continue
            meta_periodo = metas[aid] * per['dias'] / dias_mes
            cap_periodo = cap_dia * per['dias']
            req = meta_periodo / cap_periodo * 100
            alcanzable = req <= 100
            real = datos['disponibilidad']
            presupuesto = (1 - min(req, 100) / 100) * horas
            # Horas EQUIVALENTES de area que costaron las paradas. No es la
            # suma cruda de horas-equipo: en COCCION los 9 digestores trabajan
            # en paralelo y esa suma (591 h) supera las horas del mes, con lo
            # que el saldo salia negativo aunque el area cumpliera la meta.
            consumido = (1 - real / 100) * horas
            out.append({
                'area': area.name,
                'area_id': aid,
                'requerida_pct': round(req, 1),
                'real_pct': real,
                'brecha_pp': round(real - req, 1),
                'alcanzable': alcanzable,
                'presupuesto_h': round(presupuesto, 1),
                'consumido_h': round(consumido, 1),
                'saldo_h': round(presupuesto - consumido, 1),
                # Suma cruda de horas-equipo, informativa
                'horas_equipo_h': round(datos['horas_paro'], 1),
                'capacidad_dia': round(cap_dia, 2),
                'horas_periodo': horas,
            })
        out.sort(key=lambda x: (x['alcanzable'], x['brecha_pp']))
        return out

    # ── Rutas ────────────────────────────────────────────────────────────

    @app.route('/indicadores-mensuales', methods=['GET'])
    def presentacion_page():
        return render_template('presentacion.html')

    @app.route('/api/presentacion/data', methods=['GET'])
    def presentacion_data():
        """month=YYYY-MM · vista=mes|semana · semana=N (vista semanal)
        meses=N historico (vista mensual) · modo=inherente|operativa
        horizonte=horas para R(t) (default 168)"""
        try:
            hoy = dt.date.today()
            month = (request.args.get('month')
                     or _mes_anterior(hoy.strftime('%Y-%m')))[:7]
            vista = (request.args.get('vista') or 'mes').lower()
            vista = 'semana' if vista.startswith('sem') else 'mes'
            semana = request.args.get('semana', default=0, type=int)
            n = max(1, min(request.args.get('meses', default=4, type=int), 12))
            modo = (request.args.get('modo') or 'inherente').lower()
            horizonte = request.args.get('horizonte', default=168, type=float)
            if request.args.get('refrescar'):
                _invalidar_cache()

            base = _base()
            periodos = _periodos(month, vista, semana, n)
            acums = _acumulados(periodos) if vista == 'semana' else []
            actual = periodos[-1]
            areas = _areas_kpi(base)
            eq_proceso = [e for a in areas if a['orden'] < 99
                          for e in base['eq_de_area'].get(a['id'], [])]

            # Un indice de OTs por periodo, reutilizado por todas las areas
            idx = {p['key']: _por_equipo(base['ots'], p['desde'], p['hasta'])
                   for p in periodos + acums}

            def serie_de(eq_ids, lista):
                return [_punto(base, eq_ids, p, modo, horizonte, idx[p['key']])
                        for p in lista]

            areas_out = []
            for a in areas:
                eq_ids = base['eq_de_area'].get(a['id'], [])
                serie = serie_de(eq_ids, periodos)
                areas_out.append({
                    'area_id': a['id'], 'area': a['nombre'], 'orden': a['orden'],
                    'es_proceso': a['orden'] < 99,
                    'capacidad_dia': round(base['cap_area'].get(a['id'], 0.0), 2),
                    'serie': serie,
                    'acumulado': serie_de(eq_ids, acums),
                    'actual': serie[-1],
                })

            # PLANTA: las areas de proceso ponderadas por capacidad, que es
            # el indicador "global" que abre cada lamina.
            glob_serie = serie_de(eq_proceso, periodos)
            planta = {'area': 'PLANTA', 'area_id': 0,
                      'serie': glob_serie,
                      'acumulado': serie_de(eq_proceso, acums),
                      'actual': glob_serie[-1]}

            indic_actual = {a['area_id']: a['serie'][-1] for a in areas_out}
            en_vigor = _fuentes_en_vigor()
            cumpl = [dict(key=p['key'], label=p['label'], nombre=p['nombre'],
                          **_cumplimiento(base, p, en_vigor)) for p in periodos]

            n_semanas = len(_bloques_semana(month))
            return jsonify({
                'meta': {
                    'month': month, 'label': _label(month),
                    'vista': vista,
                    'semana': len(periodos) if vista == 'semana' else 0,
                    'semanas_mes': n_semanas,
                    'periodo_actual': actual['nombre'],
                    'eje': ('Semanas de ' + _label(month)) if vista == 'semana'
                           else f'Ultimos {len(periodos)} meses',
                    'periodos': [{k: p[k] for k in
                                  ('key', 'label', 'nombre', 'desde', 'hasta', 'dias', 'tep')}
                                 for p in periodos],
                    'modo': modo,
                    'horizonte_h': horizonte,
                    'rendimiento_pct': round(base['rendimiento'] * 100, 1),
                    'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'fuentes_disponibles': [{'codigo': c, 'nombre': n,
                                             'en_vigor': c in en_vigor}
                                            for c, n in FUENTES_PREVENTIVAS],
                    'laminas': [{'clave': c, 'nombre': n,
                                 'visible': c not in _laminas_ocultas()}
                                for c, n in LAMINAS],
                },
                'planta': planta,
                'areas': areas_out,
                'requerida': _requerida(base, actual, indic_actual),
                'carga': [dict(key=p['key'], label=p['label'], nombre=p['nombre'],
                               **_carga(base, p)) for p in periodos],
                'cumplimiento': {
                    'preventivo': [dict(key=c['key'], label=c['label'],
                                        nombre=c['nombre'], **c['preventivo'])
                                   for c in cumpl],
                    'correctivo': [dict(key=c['key'], label=c['label'],
                                        nombre=c['nombre'], **c['correctivo'])
                                   for c in cumpl],
                },
            })
        except Exception as e:
            logger.exception('presentacion_data error')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/presentacion/fuentes', methods=['POST'])
    def presentacion_fuentes():
        """Declara que programas preventivos estan EN VIGOR.

        Un programa en implementacion tiene sus puntos cargados pero todavia
        no se le exige a nadie: cobrarle el plan teorico hunde el cumplimiento
        con trabajo que no se pidio. Como no hay dato que distinga
        "implementando" de "no se hizo", la declaracion es explicita y queda
        a la vista en la propia lamina.
        """
        try:
            datos = request.get_json(silent=True) or {}
            pedidos = datos.get('fuentes')
            if not isinstance(pedidos, list):
                return jsonify({'error': 'Se espera una lista de fuentes'}), 400
            validos = {c for c, _ in FUENTES_PREVENTIVAS}
            sel = {str(c).strip().upper() for c in pedidos} & validos
            sel.add('OT')
            orden = [c for c, _ in FUENTES_PREVENTIVAS if c in sel]

            fila = db.session.get(AppSetting, SETTING_FUENTES)
            if fila is None:
                fila = AppSetting(key=SETTING_FUENTES)
                db.session.add(fila)
            fila.value = ','.join(orden)
            db.session.commit()
            logger.info('presentacion: fuentes preventivas en vigor = %s', fila.value)
            return jsonify({'ok': True, 'fuentes': orden})
        except Exception as e:
            db.session.rollback()
            logger.exception('presentacion_fuentes error')
            return jsonify({'error': str(e)}), 500

    # ── Entregable: la presentacion en Excel, amarrada a sus datos ───────

    def _export_historico(hasta_ym, n_meses, horizonte):
        """Historico mes a mes y area por area, en magnitudes crudas.

        El Excel recalcula los indicadores con formulas sobre estas columnas,
        asi que aqui NO se exportan disponibilidades ya calculadas: se
        exportan las horas y los eventos de los que salen. Es lo que permite
        que el libro siga vivo cuando el CMMS ya no este.
        """
        base = _base()
        areas = [a for a in _areas_kpi(base) if a['orden'] < 99]
        periodos = []
        for ym in _meses_atras(hasta_ym, n_meses):
            ini, fin = _limites(ym)
            periodos.append(_periodo(ini, fin, ym, _corto(ym), _label(ym)))

        en_vigor = _fuentes_en_vigor()
        filas, cumplimiento = [], []
        for per in periodos:
            idx = _por_equipo(base['ots'], per['desde'], per['hasta'])
            for a in areas:
                eq_ids = base['eq_de_area'].get(a['id'], [])
                pp = pn = 0.0
                fallas = n_ots = 0
                for eid in eq_ids:
                    ind = _kpi(base, idx.get(eid, []), per['tep'], 'inherente', horizonte)
                    pp += ind['downtime_planned_hours']
                    pn += ind['downtime_unplanned_hours']
                    fallas += ind['failure_count']
                    n_ots += ind['total_ots']
                filas.append({
                    'mes': per['key'], 'periodo': per['nombre'], 'area': a['nombre'],
                    'dias': per['dias'], 'tep': per['tep'],
                    'capacidad': round(base['cap_area'].get(a['id'], 0.0), 2),
                    'paro_plan': round(pp, 2), 'paro_no_plan': round(pn, 2),
                    'averias': fallas, 'ots': n_ots,
                })
            c = _cumplimiento(base, per, en_vigor)
            cumplimiento.append({
                'periodo': per['nombre'],
                'prev_plan': c['preventivo']['programadas'],
                'prev_ejec': c['preventivo']['ejecutadas'],
                'corr_plan': c['correctivo']['programados'],
                'corr_ejec': c['correctivo']['terminados'],
            })

        # Detalle de ordenes del historico: el respaldo de cada cifra
        desde, hasta = periodos[0]['desde'], periodos[-1]['hasta']
        area_de_eq = {}
        for aid, eids in base['eq_de_area'].items():
            nombre = base['areas'][aid].name if aid in base['areas'] else ''
            for eid in eids:
                area_de_eq[eid] = nombre
        ordenes = []
        for o in base['ots']:
            if not (o['fecha'] and desde <= o['fecha'] <= hasta):
                continue
            if o['equipment_id'] not in area_de_eq:
                continue
            ordenes.append({
                'code': o.get('code') or f"OT-{o['id']}",
                'fecha': o['fecha'], 'mes': o['fecha'][:7],
                'area': area_de_eq.get(o['equipment_id'], ''),
                'equipo': (base['nombre_eq'].get(o['equipment_id'], {}) or {}).get('legible', ''),
                'tipo': o.get('maintenance_type') or '',
                'modo': _modo(o),
                'paro': bool(o.get('caused_downtime')),
                'horas': round(_paro_h(o), 2),
                'planificado': _planificado(base, o),
                'descripcion': _descripcion(o.get('description')),
            })
        ordenes.sort(key=lambda x: (x['fecha'], x['code']))

        return {
            'meta': {'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                     'desde': periodos[0]['nombre'], 'hasta': periodos[-1]['nombre']},
            'meses': [(p['key'], p['nombre']) for p in periodos],
            'areas': [a['nombre'] for a in areas],
            'filas': filas,
            'cumplimiento': cumplimiento,
            'ordenes': ordenes,
        }

    @app.route('/api/presentacion/export-excel', methods=['GET'])
    def presentacion_export_excel():
        """Descarga la presentacion mensual como libro de Excel autonomo."""
        try:
            from utils.presentacion_excel import build_presentation_workbook
            hoy = dt.date.today()
            month = (request.args.get('month')
                     or _mes_anterior(hoy.strftime('%Y-%m')))[:7]
            meses = max(1, min(request.args.get('meses', default=24, type=int), 60))
            horizonte = request.args.get('horizonte', default=168, type=float)
            datos = _export_historico(month, meses, horizonte)
            bio = build_presentation_workbook(datos)
            nombre = f'Indicadores_Mantenimiento_{month}.xlsx'
            return send_file(
                bio, as_attachment=True, download_name=nombre,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except Exception as e:
            logger.exception('presentacion_export_excel error')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/presentacion/export-datos', methods=['GET'])
    def presentacion_export_datos():
        """El mismo historico en JSON: lo consume la version en navegador."""
        try:
            hoy = dt.date.today()
            month = (request.args.get('month')
                     or _mes_anterior(hoy.strftime('%Y-%m')))[:7]
            meses = max(1, min(request.args.get('meses', default=24, type=int), 60))
            horizonte = request.args.get('horizonte', default=168, type=float)
            return jsonify(_export_historico(month, meses, horizonte))
        except Exception as e:
            logger.exception('presentacion_export_datos error')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/presentacion/laminas', methods=['POST'])
    def presentacion_laminas():
        """Guarda que laminas se presentan.

        Se recibe la lista de las VISIBLES y se persiste el complemento: asi,
        si manana se agrega una lamina nueva, aparece por defecto en vez de
        quedar escondida sin que nadie lo note.
        """
        try:
            datos = request.get_json(silent=True) or {}
            pedidas = datos.get('visibles')
            if not isinstance(pedidas, list):
                return jsonify({'error': 'Se espera una lista de laminas'}), 400
            validas = [c for c, _ in LAMINAS]
            vis = {str(c).strip() for c in pedidas} & set(validas)
            if not vis:
                return jsonify({'error': 'Deja al menos una lamina encendida'}), 400
            ocultas = [c for c in validas if c not in vis]

            fila = db.session.get(AppSetting, SETTING_LAMINAS)
            if fila is None:
                fila = AppSetting(key=SETTING_LAMINAS)
                db.session.add(fila)
            fila.value = ','.join(ocultas)
            db.session.commit()
            logger.info('presentacion: laminas ocultas = %s', fila.value or '(ninguna)')
            return jsonify({'ok': True, 'ocultas': ocultas,
                            'laminas': [{'clave': c, 'nombre': n,
                                         'visible': c not in ocultas}
                                        for c, n in LAMINAS]})
        except Exception as e:
            db.session.rollback()
            logger.exception('presentacion_laminas error')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/presentacion/pareto', methods=['GET'])
    def presentacion_pareto():
        """Pareto de modos de falla y equipos que concentran las paradas.

        Dos ventanas sobre los mismos datos: el mes que se esta presentando
        —lo que hay que explicar hoy— y los ultimos seis meses, que es donde
        se ve si un modo de falla fue un evento aislado o el problema de
        fondo. Un modo que aparece arriba en las dos ventanas ya no es mala
        suerte: es diseño, operacion o plan de mantenimiento.

        El ranking de equipos usa el mismo motor que la lamina de
        disponibilidad —misma consolidacion por parada, misma clasificacion
        de averia— para que las horas coincidan con el detalle que se abre al
        hacer click en el grafico.
        """
        try:
            hoy = dt.date.today()
            month = (request.args.get('month')
                     or _mes_anterior(hoy.strftime('%Y-%m')))[:7]
            meses = max(2, min(request.args.get('meses', default=6, type=int), 12))
            modo = (request.args.get('modo') or 'inherente').lower()
            horizonte = request.args.get('horizonte', default=168, type=float)
            top = max(5, min(request.args.get('top', default=10, type=int), 25))
            base = _base()

            def bloque(desde, hasta, etiqueta):
                dias = ((dt.date.fromisoformat(hasta)
                         - dt.date.fromisoformat(desde)).days + 1)
                tep = dias * 24
                idx = _por_equipo(base['ots'], desde, hasta)
                del_periodo = [o for o in base['ots']
                               if o['fecha'] and desde <= o['fecha'] <= hasta]

                # Cuando varias ordenes se ejecutan en la misma parada, sus
                # horas NO se suman: es la misma hora de planta detenida. El
                # motor la cuenta una sola vez, asi que aqui esa hora se
                # reparte entre las ordenes de la parada en proporcion a lo
                # que cada una declaro. Sin esto, una parada con cinco
                # trabajos dentro multiplicaria por cinco su paro.
                grupos = {}
                for o in del_periodo:
                    if o.get('shutdown_id') and _paro_h(o) > 0:
                        grupos.setdefault((o['shutdown_id'],
                                           o.get('equipment_id') or 0),
                                          []).append(o)
                reparto = {}
                for miembros in grupos.values():
                    horas = [_paro_h(x) for x in miembros]
                    sh = base['shutdowns'].get(miembros[0]['shutdown_id'])
                    dur = _duracion_parada(sh)
                    consolidada = dur if dur > 0 else max(horas)
                    suma = sum(horas)
                    for x, h in zip(miembros, horas):
                        reparto[x['id']] = (consolidada * h / suma) if suma else 0.0

                # Dos magnitudes, y las dos importan: EVENTOS cuenta cuantas
                # veces aparecio el modo de falla —uno que se repite doce
                # veces sin detener la linea igual consume cuadrilla y
                # anuncia la rotura que viene— y HORAS suma solo el paro no
                # planificado, para hablar del mismo universo que la
                # disponibilidad inherente de la lamina 02.
                modos = {}
                for o in del_periodo:
                    paro = reparto.get(o['id'], _paro_h(o))
                    correctivo = (o.get('maintenance_type') or '').strip() \
                        .lower().startswith('correctiv')
                    plan = _planificado(base, o)
                    if not correctivo and (paro <= 0 or plan):
                        continue
                    m = _modo(o) or 'SIN REGISTRAR'
                    d = modos.setdefault(m, {'modo': m, 'eventos': 0,
                                             'horas': 0.0, 'horas_plan': 0.0,
                                             'equipos': set()})
                    d['eventos'] += 1
                    if plan:
                        d['horas_plan'] += paro
                    else:
                        d['horas'] += paro
                    if o.get('equipment_id'):
                        d['equipos'].add(o['equipment_id'])
                lista = sorted(
                    ({'modo': d['modo'], 'eventos': d['eventos'],
                      'horas': round(d['horas'], 1),
                      'horas_planificadas': round(d['horas_plan'], 1),
                      'equipos': len(d['equipos']),
                      'sin_dato': d['modo'] == 'SIN REGISTRAR'}
                     for d in modos.values()),
                    key=lambda d: (-d['horas'], -d['eventos']))

                equipos = []
                for eid, ots_eq in idx.items():
                    ind = _kpi(base, ots_eq, tep, modo, horizonte)
                    if ind['downtime_hours'] <= 0:
                        continue
                    equipos.append({
                        'equipo': (base['nombre_eq'].get(eid, {}).get('legible')
                                   or f'Equipo {eid}'),
                        'paradas': ind['failure_count'],
                        'horas': round(ind['downtime_hours'], 1),
                        'mttr': ind['mttr'],
                        'disponibilidad': ind['availability'],
                    })
                equipos.sort(key=lambda e: (-e['horas'], -e['paradas']))
                ev = sum(d['eventos'] for d in lista)

                return {
                    'etiqueta': etiqueta, 'desde': desde, 'hasta': hasta,
                    'dias': dias,
                    'modos': lista,
                    'modos_total_eventos': ev,
                    'modos_total_horas': round(sum(d['horas'] for d in lista), 1),
                    'sin_registrar_pct': (
                        round(sum(d['eventos'] for d in lista if d['sin_dato'])
                              / ev * 100, 1) if ev else None),
                    'equipos': equipos[:top],
                    'equipos_total': len(equipos),
                    'horas_total': round(sum(e['horas'] for e in equipos), 1),
                    'horas_top': round(sum(e['horas'] for e in equipos[:top]), 1),
                }

            ini, fin = _limites(month)
            historico = _meses_atras(month, meses)
            desde_hist = _limites(historico[0])[0]

            return jsonify({
                'meta': {'month': month, 'label': _label(month),
                         'meses': meses, 'modo': modo, 'top': top},
                'mes': bloque(ini.isoformat(), fin.isoformat(), _label(month)),
                'historico': bloque(
                    desde_hist.isoformat(), fin.isoformat(),
                    _label(historico[0]) + ' a ' + _label(month)),
            })
        except Exception as e:
            logger.exception('presentacion_pareto error')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/presentacion/detalle', methods=['GET'])
    def presentacion_detalle():
        """Drill-down de una barra del grafico: equipo por equipo y las
        ordenes que generaron el paro. Es lo que se abre cuando en la
        reunion preguntan "¿y por que bajo esa area?"."""
        try:
            aid = request.args.get('area_id', default=0, type=int)
            desde = (request.args.get('desde') or '')[:10]
            hasta = (request.args.get('hasta') or '')[:10]
            modo = (request.args.get('modo') or 'inherente').lower()
            horizonte = request.args.get('horizonte', default=168, type=float)
            if not desde or not hasta:
                return jsonify({'error': 'Falta el rango de fechas'}), 400

            base = _base()
            areas = _areas_kpi(base)
            if aid:
                eq_ids = base['eq_de_area'].get(aid, [])
                titulo = base['areas'][aid].name if aid in base['areas'] else 'Area'
            else:
                eq_ids = [e for a in areas if a['orden'] < 99
                          for e in base['eq_de_area'].get(a['id'], [])]
                titulo = 'PLANTA (areas de proceso)'

            dias = ((dt.date.fromisoformat(hasta)
                     - dt.date.fromisoformat(desde)).days + 1)
            tep = dias * 24
            idx = _por_equipo(base['ots'], desde, hasta)
            resumen = _ponderar(base, eq_ids, idx, tep, modo, horizonte)

            nombres = {eid: (v.get('legible') or f'Equipo {eid}')
                       for eid, v in base['nombre_eq'].items()}

            # Las lineas primero: son la unidad de medida de la
            # disponibilidad, porque dentro de ellas los equipos van en serie.
            lineas = []
            for lid in {base['linea_de_eq'].get(e) for e in eq_ids} - {None}:
                cap = base['cap_linea'].get(lid, 0.0)
                miembros = [e for e in eq_ids if base['linea_de_eq'].get(e) == lid]
                ind = _kpi(base, _ots_de_linea(base, eq_ids, idx, lid), tep,
                           modo, horizonte)
                detuvieron = []
                for eid in miembros:
                    ie = _kpi(base, idx.get(eid, []), tep, modo, horizonte)
                    if ie['downtime_hours'] > 0:
                        detuvieron.append({
                            'equipo': nombres.get(eid, f'EQ-{eid}'),
                            'horas': ie['downtime_hours'],
                            'fallas': ie['failure_count'],
                            'auxiliar': base['cap_eq'].get(eid, 0.0) <= 0,
                        })
                detuvieron.sort(key=lambda x: -x['horas'])
                critica = cap <= 0 and base['linea_critica'].get(lid)
                if cap <= 0 and not detuvieron and not critica:
                    continue
                lineas.append({
                    'linea': (base['lines'][lid].name if lid in base['lines']
                              else f'LINEA {lid}'),
                    'equipos': len(miembros),
                    'capacidad': round(cap, 2),
                    'pesa': cap > 0,
                    'critica': bool(critica),
                    'disponibilidad': ind['availability'],
                    'mtbf': ind['mtbf'],
                    'horas_paro': ind['downtime_hours'],
                    'fallas': ind['failure_count'],
                    'detuvieron': detuvieron,
                })
            lineas.sort(key=lambda x: (-x['capacidad'], x['disponibilidad']))

            equipos, ots = [], []
            for eid in eq_ids:
                de_eq = idx.get(eid, [])
                ind = _kpi(base, de_eq, tep, modo, horizonte)
                if ind['total_ots'] == 0 and ind['downtime_hours'] == 0:
                    continue
                equipos.append({
                    'equipo': nombres.get(eid, f'EQ-{eid}'),
                    'capacidad': round(base['cap_eq'].get(eid, 0.0), 2),
                    'disponibilidad': ind['availability'],
                    'mtbf': ind['mtbf'], 'mttr': ind['mttr'],
                    'confiabilidad': ind['reliability'],
                    'fallas': ind['failure_count'],
                    'horas_paro': ind['downtime_hours'],
                    'ots': ind['total_ots'],
                })
                for o in de_eq:
                    paro = 0.0
                    if o.get('caused_downtime'):
                        paro = float(o.get('downtime_hours')
                                     or o.get('real_duration') or 0)
                    ots.append({
                        'code': o.get('code') or f"OT-{o['id']}",
                        'equipo': nombres.get(eid, ''),
                        'tipo': o.get('maintenance_type') or '—',
                        'descripcion': _descripcion(o.get('description')),
                        'modo_falla': _modo(o),
                        'fecha': o.get('fecha'),
                        'horas_paro': round(paro, 2),
                        'planificado': bool(o.get('downtime_planned')) if o.get('downtime_planned') is not None
                                       else (o.get('maintenance_type') or '').strip().lower() != 'correctivo',
                    })
            equipos.sort(key=lambda x: (-x['horas_paro'], x['equipo']))
            ots.sort(key=lambda x: (-x['horas_paro'], x['fecha'] or ''))

            return jsonify({
                'titulo': titulo,
                'periodo': f'{desde} a {hasta}',
                'dias': dias, 'tep': tep, 'modo': modo,
                'resumen': resumen,
                'lineas': lineas,
                'equipos': equipos,
                'ots': ots,
            })
        except Exception as e:
            logger.exception('presentacion_detalle error')
            return jsonify({'error': str(e)}), 500
