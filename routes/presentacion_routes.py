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

from flask import jsonify, render_template, request


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
MESES_CORTO = ['', 'ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN',
               'JUL', 'AGO', 'SET', 'OCT', 'NOV', 'DIC']

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
                        ProductionGoal, WorkOrder)

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
        cap_eq, cap_area = {}, {}
        eq_de_area, nombre_eq = {}, {}
        for e in equipos:
            nombre_eq[e.id] = {'nombre': e.name or '', 'tag': e.tag or ''}
            if not e.include_in_kpi or e.line_id not in lines:
                continue
            cap = (eq_harina_tm_day(e, rend)
                   if eq_produces(e) and e.in_service else 0.0)
            cap_eq[e.id] = cap
            aid = lines[e.line_id].area_id
            cap_area[aid] = cap_area.get(aid, 0.0) + cap
            eq_de_area.setdefault(aid, []).append(e.id)

        # UNA sola pasada por las ordenes: de ahi salen las cerradas (para
        # los indicadores) y las programadas (para el cumplimiento).
        filas = WorkOrder.query.with_entities(
            WorkOrder.id, WorkOrder.code, WorkOrder.description,
            WorkOrder.maintenance_type, WorkOrder.status, WorkOrder.equipment_id,
            WorkOrder.shutdown_id, WorkOrder.caused_downtime,
            WorkOrder.downtime_hours, WorkOrder.downtime_planned,
            WorkOrder.real_duration, WorkOrder.scheduled_date,
            WorkOrder.real_start_date, WorkOrder.real_end_date).all()

        cerradas, programadas = [], []
        for f in filas:
            if f.scheduled_date:
                programadas.append({'fecha': str(f.scheduled_date)[:10],
                                    'maintenance_type': f.maintenance_type,
                                    'status': f.status})
            if f.status != 'Cerrada':
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

        rutinas_prev = {
            'LUB': rutinas(LubricationPoint, LubricationExecution,
                           LubricationExecution.execution_date),
            'INS': rutinas(InspectionRoute, InspectionExecution,
                           InspectionExecution.execution_date),
            'MON': rutinas(MonitoringPoint, MonitoringReading,
                           MonitoringReading.reading_date),
        }

        return {'areas': areas, 'lines': lines, 'equipos': equipos,
                'rendimiento': rend, 'cap_eq': cap_eq, 'cap_area': cap_area,
                'eq_de_area': eq_de_area, 'ots': cerradas,
                'programadas': programadas, 'metas': metas,
                'rutinas': rutinas_prev}

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

    def _ponderar(base, eq_ids, idx, tep, modo, horizonte):
        """Indicadores de un conjunto de equipos, PONDERADOS POR CAPACIDAD.

        Se calcula equipo por equipo y se pesa por lo que cada uno aporta a
        la planta. Sumar las horas de paro de equipos en paralelo (los 9
        digestores) como si estuvieran en serie es lo que antes devolvia
        disponibilidades imposibles.
        """
        from routes.indicators_routes import _calc_indicators
        num = {'disponibilidad': 0.0, 'mtbf': 0.0, 'confiabilidad': 0.0}
        peso = 0.0
        paro_total, fallas, n_ots = 0.0, 0, 0
        for eid in eq_ids:
            cap = base['cap_eq'].get(eid, 0.0)
            ind = _calc_indicators(idx.get(eid, []), tep, mode=modo,
                                   reliability_hours=horizonte)
            paro_total += ind['downtime_hours']
            fallas += ind['failure_count']
            n_ots += ind['total_ots']
            if cap <= 0:
                continue
            num['disponibilidad'] += ind['availability'] * cap
            num['mtbf'] += ind['mtbf'] * cap
            num['confiabilidad'] += ind['reliability'] * cap
            peso += cap
        if peso > 0:
            res = {k: round(v / peso, 2) for k, v in num.items()}
            res['ponderado'] = True
        else:
            # Sin equipos con capacidad: se mide el conjunto directamente
            todas = [o for eid in eq_ids for o in idx.get(eid, [])]
            ind = _calc_indicators(todas, tep, mode=modo,
                                   reliability_hours=horizonte)
            res = {'disponibilidad': ind['availability'], 'mtbf': ind['mtbf'],
                   'confiabilidad': ind['reliability'], 'ponderado': False}
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
                },
                'planta': planta,
                'areas': areas_out,
                'requerida': _requerida(base, actual, indic_actual),
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

    @app.route('/api/presentacion/detalle', methods=['GET'])
    def presentacion_detalle():
        """Drill-down de una barra del grafico: equipo por equipo y las
        ordenes que generaron el paro. Es lo que se abre cuando en la
        reunion preguntan "¿y por que bajo esa area?"."""
        try:
            from routes.indicators_routes import _calc_indicators
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

            nombres = {e.id: (e.tag or e.name or f'EQ-{e.id}')
                       for e in base['equipos']}
            equipos, ots = [], []
            for eid in eq_ids:
                de_eq = idx.get(eid, [])
                ind = _calc_indicators(de_eq, tep, mode=modo,
                                       reliability_hours=horizonte)
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
                        'descripcion': (o.get('description') or '')[:180],
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
                'equipos': equipos,
                'ots': ots,
            })
        except Exception as e:
            logger.exception('presentacion_detalle error')
            return jsonify({'error': str(e)}), 500
