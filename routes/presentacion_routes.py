"""Indicadores Mensuales de Mantenimiento — presentacion para gerencia.

Corre EN PARALELO al Diagnostico Mensual, no lo reemplaza. La diferencia es
deliberada: aqui NO se habla de toneladas. Ni las no producidas ni las
elaboradas. El unico dato que entra desde produccion es la meta, y solo para
responder una pregunta de mantenimiento:

    ¿cuanta disponibilidad necesito en cada area para que la planta cumpla?

De ahi en adelante todo se expresa en horas y porcentajes, que es el lenguaje
sobre el que mantenimiento puede actuar.

El orden de las laminas sigue el informe que la jefatura ya venia presentando:
    1. Disponibilidad          (area + desglose por linea)
    2. MTBF                    (contra el TEP, tiempo efectivo del periodo)
    3. MTTR                    (tiempo medio de reparacion)
    4. Cumplimiento de mantenimiento preventivo
    5. Cumplimiento de mantenimiento correctivo programado
    6. Confiabilidad
mas una lamina inicial de disponibilidad requerida.
"""
import calendar
import datetime as dt

from flask import jsonify, render_template, request


# Areas del proceso productivo, en el orden del flujo. Las demas areas
# (calderas, subestacion, vahos...) se calculan igual pero van despues.
AREAS_PROCESO = ['COCCION', 'SECADO', 'MOLINO']

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre']
MESES_CORTO = ['', 'ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN',
               'JUL', 'AGO', 'SET', 'OCT', 'NOV', 'DIC']


def register_presentacion_routes(app, db, logger):
    from models import (Area, Equipment, Line, ProductionGoal, WorkOrder)

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

    # ── Datos base, una sola lectura para todos los meses ────────────────

    def _contexto():
        """Todo lo que se consulta a la BD, de una vez."""
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
        for e in equipos:
            if not e.include_in_kpi or e.line_id not in lines:
                continue
            cap = (eq_harina_tm_day(e, rend)
                   if eq_produces(e) and e.in_service else 0.0)
            cap_eq[e.id] = cap
            aid = lines[e.line_id].area_id
            cap_area[aid] = cap_area.get(aid, 0.0) + cap
            cap_linea[e.line_id] = cap_linea.get(e.line_id, 0.0) + cap

        return {'areas': areas, 'lines': lines, 'equipos': equipos,
                'rendimiento': rend, 'cap_eq': cap_eq, 'cap_area': cap_area,
                'cap_linea': cap_linea}

    def _ots_cerradas():
        """OTs cerradas como dicts, que es lo que espera _calc_indicators."""
        out = []
        for o in WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all():
            d = {
                'id': o.id, 'code': o.code, 'description': o.description,
                'maintenance_type': o.maintenance_type, 'status': o.status,
                'equipment_id': o.equipment_id, 'shutdown_id': o.shutdown_id,
                'caused_downtime': o.caused_downtime,
                'downtime_hours': o.downtime_hours,
                'downtime_planned': o.downtime_planned,
                'real_duration': o.real_duration,
                'scheduled_date': o.scheduled_date,
                'fecha': str(o.real_end_date or o.real_start_date
                             or o.scheduled_date or '')[:10],
            }
            out.append(d)
        return out

    # ── Indicadores de un mes ────────────────────────────────────────────

    def _indicadores_mes(ctx, ots, ym, modo, horizonte):
        """Disponibilidad, MTBF, MTTR y confiabilidad del mes, por area y por
        linea. La agregacion a area es PONDERADA POR CAPACIDAD: se calcula
        equipo por equipo y se pesa por lo que cada uno aporta a la planta."""
        from routes.indicators_routes import _calc_indicators
        ini, fin = _limites(ym)
        tep = ((fin - ini).days + 1) * 24          # tiempo efectivo del periodo
        s_ini, s_fin = ini.isoformat(), fin.isoformat()

        del_mes = [o for o in ots if o['fecha'] and s_ini <= o['fecha'] <= s_fin]
        por_equipo = {}
        for o in del_mes:
            if o['equipment_id']:
                por_equipo.setdefault(o['equipment_id'], []).append(o)

        def indicadores_de(eq_ids):
            """Pondera por capacidad los indicadores de un conjunto de equipos."""
            num = {'disponibilidad': 0.0, 'mtbf': 0.0, 'confiabilidad': 0.0}
            peso = 0.0
            paro_total, fallas = 0.0, 0
            for eid in eq_ids:
                cap = ctx['cap_eq'].get(eid, 0.0)
                ind = _calc_indicators(por_equipo.get(eid, []), tep, mode=modo,
                                       reliability_hours=horizonte)
                paro_total += ind['downtime_hours']
                fallas += ind['failure_count']
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
                todas = [o for eid in eq_ids for o in por_equipo.get(eid, [])]
                ind = _calc_indicators(todas, tep, mode=modo,
                                       reliability_hours=horizonte)
                res = {'disponibilidad': ind['availability'], 'mtbf': ind['mtbf'],
                       'confiabilidad': ind['reliability'], 'ponderado': False}
            # MTTR: cuanto cuesta reparar una averia, sin ponderar
            res['mttr'] = round(paro_total / fallas, 2) if fallas else 0.0
            res['fallas'] = fallas
            res['horas_paro'] = round(paro_total, 2)
            res['tep'] = tep
            return res

        salida = {}
        for aid, area in ctx['areas'].items():
            if not area.include_in_kpi:
                continue
            eq_area = [e.id for e in ctx['equipos']
                       if e.include_in_kpi and e.line_id in ctx['lines']
                       and ctx['lines'][e.line_id].area_id == aid]
            if not eq_area:
                continue
            datos = indicadores_de(eq_area)

            # Desglose por linea (lo que el informe llama "LINEAS")
            lineas = []
            for lid, ln in ctx['lines'].items():
                if ln.area_id != aid:
                    continue
                eq_ln = [e.id for e in ctx['equipos']
                         if e.include_in_kpi and e.line_id == lid]
                if not eq_ln:
                    continue
                d_ln = indicadores_de(eq_ln)
                d_ln['linea'] = ln.name
                d_ln['etiqueta'] = _etiqueta_linea(ctx, lid, ln.name)
                d_ln['capacidad'] = round(ctx['cap_linea'].get(lid, 0.0), 2)
                lineas.append(d_ln)
            lineas.sort(key=lambda x: x['etiqueta'])
            datos['lineas'] = lineas
            salida[aid] = datos
        return salida

    def _etiqueta_linea(ctx, line_id, nombre):
        """Etiqueta corta para el grafico: el tag del equipo con capacidad de
        la linea (D1, MOL1...) o el nombre de la linea sin la palabra LINEA."""
        tags = [e.tag for e in ctx['equipos']
                if e.line_id == line_id and e.include_in_kpi
                and ctx['cap_eq'].get(e.id, 0) > 0 and e.tag]
        if len(tags) == 1:
            return tags[0]
        corto = (nombre or '').upper().replace('LINEA ', '').replace('LÍNEA ', '')
        return corto.strip()[:14] or (nombre or '')[:14]

    # ── Cumplimiento (preventivo y correctivo programado) ────────────────

    def _cumplimiento(ots_todas, ym):
        """Programadas vs ejecutadas del mes, separando preventivo de
        correctivo programado — los dos indicadores del informe."""
        ini, fin = _limites(ym)
        s_ini, s_fin = ini.isoformat(), fin.isoformat()

        prev_prog = prev_ejec = corr_prog = corr_term = 0
        for o in ots_todas:
            f = str(o.scheduled_date or '')[:10]
            if not f or not (s_ini <= f <= s_fin):
                continue
            mt = (o.maintenance_type or '').strip().lower()
            cerrada = (o.status == 'Cerrada')
            if mt in ('preventivo', 'predictivo'):
                prev_prog += 1
                prev_ejec += 1 if cerrada else 0
            elif mt == 'correctivo':
                # Correctivo PROGRAMADO: el que tenia fecha planificada
                corr_prog += 1
                corr_term += 1 if cerrada else 0
        return {
            'preventivo': {'programadas': prev_prog, 'ejecutadas': prev_ejec,
                           'pct': round(prev_ejec / prev_prog * 100, 1) if prev_prog else None},
            'correctivo': {'programados': corr_prog, 'terminados': corr_term,
                           'pct': round(corr_term / corr_prog * 100, 1) if corr_prog else None},
        }

    # ── Disponibilidad requerida ─────────────────────────────────────────

    def _requerida(ctx, ym, indicadores):
        """Cuanta disponibilidad necesita cada area para cumplir la meta.

        La meta viene en toneladas, pero NO se muestra: solo se usa para
        despejar el porcentaje y el presupuesto de horas de parada, que es
        con lo que mantenimiento puede trabajar.

            disponibilidad requerida = meta del mes / capacidad del mes
            presupuesto de parada    = (1 - requerida) x horas del periodo
        """
        ini, fin = _limites(ym)
        dias = (fin - ini).days + 1
        horas = dias * 24

        metas = {}
        for g in ProductionGoal.query.filter_by(goal_period=ym).all():
            if g.area_id and g.monthly_target_tons:
                metas[g.area_id] = float(g.monthly_target_tons)

        out = []
        for aid, datos in indicadores.items():
            area = ctx['areas'][aid]
            cap_dia = ctx['cap_area'].get(aid, 0.0)
            if cap_dia <= 0 or aid not in metas:
                continue
            cap_periodo = cap_dia * dias
            req = metas[aid] / cap_periodo * 100
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
        """month=YYYY-MM · meses=N (default 4, como el informe actual)
        modo=inherente|operativa · horizonte=horas para R(t) (default 168)"""
        try:
            hoy = dt.date.today()
            mes_actual = hoy.strftime('%Y-%m')
            month = (request.args.get('month') or _mes_anterior(mes_actual))[:7]
            n = max(1, min(request.args.get('meses', default=4, type=int), 12))
            modo = (request.args.get('modo') or 'inherente').lower()
            horizonte = request.args.get('horizonte', default=168, type=float)

            ctx = _contexto()
            ots = _ots_cerradas()
            todas = WorkOrder.query.all()
            meses = _meses_atras(month, n)

            # Indicadores mes a mes
            por_mes = {ym: _indicadores_mes(ctx, ots, ym, modo, horizonte)
                       for ym in meses}
            cumpl = {ym: _cumplimiento(todas, ym) for ym in meses}

            # Reorganizado por area: una serie por indicador
            areas_out = []
            for aid in {a for m in por_mes.values() for a in m}:
                area = ctx['areas'][aid]
                serie = []
                for ym in meses:
                    d = por_mes[ym].get(aid)
                    serie.append({
                        'month': ym, 'label': _corto(ym),
                        'disponibilidad': d['disponibilidad'] if d else None,
                        'mtbf': d['mtbf'] if d else None,
                        'mttr': d['mttr'] if d else None,
                        'confiabilidad': d['confiabilidad'] if d else None,
                        'fallas': d['fallas'] if d else 0,
                        'horas_paro': d['horas_paro'] if d else 0,
                        'tep': d['tep'] if d else 0,
                    })
                # Desglose por linea de cada mes (para el grafico de barras)
                lineas = []
                etiquetas = []
                for ym in meses:
                    d = por_mes[ym].get(aid)
                    for ln in (d or {}).get('lineas', []):
                        if ln['etiqueta'] not in etiquetas:
                            etiquetas.append(ln['etiqueta'])
                for et in etiquetas:
                    fila = {'etiqueta': et, 'valores': []}
                    for ym in meses:
                        d = por_mes[ym].get(aid)
                        m = next((x for x in (d or {}).get('lineas', [])
                                  if x['etiqueta'] == et), None)
                        fila['valores'].append({
                            'month': ym, 'label': _corto(ym),
                            'disponibilidad': m['disponibilidad'] if m else None,
                            'mtbf': m['mtbf'] if m else None,
                            'mttr': m['mttr'] if m else None,
                            'confiabilidad': m['confiabilidad'] if m else None,
                        })
                    lineas.append(fila)
                orden = (AREAS_PROCESO.index(area.name.upper())
                         if area.name.upper() in AREAS_PROCESO else 99)
                areas_out.append({
                    'area_id': aid, 'area': area.name, 'orden': orden,
                    'es_proceso': orden < 99,
                    'capacidad_dia': round(ctx['cap_area'].get(aid, 0.0), 2),
                    'serie': serie, 'lineas': lineas,
                    'actual': serie[-1],
                })
            areas_out.sort(key=lambda x: (x['orden'], x['area']))

            return jsonify({
                'meta': {
                    'month': month, 'label': _label(month),
                    'meses': [{'month': m, 'label': _corto(m),
                               'nombre': _label(m)} for m in meses],
                    'modo': modo,
                    'horizonte_h': horizonte,
                    'rendimiento_pct': round(ctx['rendimiento'] * 100, 1),
                    'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                },
                'areas': areas_out,
                'requerida': _requerida(ctx, month, por_mes[month]),
                'cumplimiento': {
                    'preventivo': [dict(month=m, label=_corto(m),
                                        **cumpl[m]['preventivo']) for m in meses],
                    'correctivo': [dict(month=m, label=_corto(m),
                                        **cumpl[m]['correctivo']) for m in meses],
                },
            })
        except Exception as e:
            logger.exception('presentacion_data error')
            return jsonify({'error': str(e)}), 500
