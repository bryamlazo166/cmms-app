"""Diagnostico mensual de gestion de mantenimiento.

Pagina /diagnostico: informe ejecutivo con datos calculados EN VIVO desde la
BD (mismo formato siempre), narrativa generada con DeepSeek, modo presentacion
para gerencia, drill-down (Pareto/equipos -> OTs; confiabilidad por area via
/api/indicators/*), cuadro consolidado de 12 meses y programacion del resto
del mes en curso + mes siguiente para coordinar con produccion.
"""
import calendar
import datetime as dt
import math
from collections import defaultdict

from flask import jsonify, render_template, request


def register_diagnostico_routes(app, db, logger):
    from models import (
        WorkOrder, Equipment, Line, ProductionGoal,
        LubricationPoint, InspectionRoute, MonitoringPoint,
        RotativeAsset, WarehouseItem, Technician, Shutdown,
    )

    SACK_KG = 50  # 1 saco de harina = 50 kg (igual que el modulo Produccion)

    # ── Helpers de fechas (todas las fechas son strings ISO) ─────────────

    def _prev_month(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"

    def _next_month(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"

    def _month_label(ym):
        MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                 'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre']
        return f"{MESES[int(ym[5:7])]} {ym[:4]}"

    def _ot_close_month(ot):
        d = ot.real_end_date or ot.real_start_date or ot.scheduled_date
        return str(d)[:7] if d else None

    def _downtime(ot):
        if getattr(ot, 'caused_downtime', None):
            return float(ot.downtime_hours or ot.real_duration or 0)
        return 0.0

    def _mtype(ot):
        return (ot.maintenance_type or '').strip().lower()

    def _months_back(ym, n):
        out = []
        cur = ym
        for _ in range(n):
            out.append(cur)
            cur = _prev_month(cur)
        out.reverse()
        return out

    # ── Produccion: TM/h por area segun metas (modulo Produccion vs Mtto) ─

    def _goals_por_area():
        """{area_id: [(period, goal), ...] ordenado}."""
        out = {}
        for g in ProductionGoal.query.all():
            out.setdefault(g.area_id, []).append((g.goal_period, g))
        for k in out:
            out[k].sort(key=lambda x: x[0])
        return out

    def _goal_para(goals_area, ym):
        """Meta vigente para el mes: la ultima con period <= ym, o la primera."""
        if not goals_area:
            return None
        anteriores = [g for (p, g) in goals_area if p <= ym]
        return anteriores[-1] if anteriores else goals_area[0][1]

    def _tons_per_hour(goal):
        oh = goal.operating_hours_month or 720.0
        return (goal.monthly_avg_yield_tons / oh) if oh > 0 else 0.0

    def _area_resolver():
        line_map = {l.id: l for l in Line.query.all()}
        eq_map = {e.id: e for e in Equipment.query.all()}

        def resolver(ot):
            if ot.area_id:
                return ot.area_id
            if ot.line_id and ot.line_id in line_map:
                return line_map[ot.line_id].area_id
            if ot.equipment_id and ot.equipment_id in eq_map:
                e = eq_map[ot.equipment_id]
                if e.line_id and e.line_id in line_map:
                    return line_map[e.line_id].area_id
            return None
        return resolver, eq_map

    # ── Datos del diagnostico ─────────────────────────────────────────────

    @app.route('/diagnostico')
    def diagnostico_page():
        return render_template('diagnostico.html')

    def _build_diagnostico(month):
        """Arma el dict completo del diagnostico del mes. Lo usan el API
        JSON (/api/diagnostico/data) y el informe HTML descargable."""
        try:
            hoy = dt.date.today()
            mes_actual = hoy.strftime('%Y-%m')
            month = (month or mes_actual)[:7]
            prev = _prev_month(month)
            nxt = _next_month(month)

            ots = WorkOrder.query.all()
            closed = [o for o in ots if o.status == 'Cerrada']
            open_ots = [o for o in ots if (o.status or '') not in ('Cerrada', 'No Ejecutada')]
            eq_map = {e.id: e for e in Equipment.query.all()}

            # ── Stats por mes (incluye MTBF/Disp/Conf a nivel planta) ────
            # Planta tratada como un sistema en serie: uptime = horas del
            # periodo - downtime consolidado. Para el mes EN CURSO se usan
            # solo las horas transcurridas (KPIs parciales honestos).
            def month_stats(ym):
                mes = [o for o in closed if _ot_close_month(o) == ym]
                corr = [o for o in mes if _mtype(o) == 'correctivo']
                proa = [o for o in mes if _mtype(o) in ('preventivo', 'predictivo')]
                mejora = [o for o in mes if _mtype(o) == 'mejora']
                mix_base = len(corr) + len(proa)
                mttr_vals = [float(o.real_duration) for o in corr if o.real_duration]
                dt_total = sum(_downtime(o) for o in mes)

                dias_m = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
                en_curso = (ym == mes_actual)
                dias_efectivos = hoy.day if en_curso else dias_m
                horas_m = max(dias_efectivos * 24, 1)
                uptime = max(horas_m - dt_total, 0)
                n_fallas = len(corr)
                mtbf = round(uptime / n_fallas, 1) if n_fallas else None
                disp = round(uptime / horas_m * 100, 2)
                # Confiabilidad semanal R(168h) = e^(-168/MTBF)
                conf = (round(math.exp(-168.0 / mtbf) * 100, 1)
                        if mtbf and mtbf > 0 else None)

                return {
                    'month': ym,
                    'label': _month_label(ym),
                    'en_curso': en_curso,
                    'dias_efectivos': dias_efectivos,
                    'dias_mes': dias_m,
                    'closed_total': len(mes),
                    'correctivas': len(corr),
                    'proactivas': len(proa),
                    'mejoras': len(mejora),
                    'proactive_pct': round(len(proa) / mix_base * 100, 1) if mix_base else 0.0,
                    'reactive_pct': round(len(corr) / mix_base * 100, 1) if mix_base else 0.0,
                    'mttr_h': round(sum(mttr_vals) / len(mttr_vals), 1) if mttr_vals else None,
                    'downtime_h': round(dt_total, 1),
                    'mtbf_h': mtbf,
                    'disponibilidad_pct': disp,
                    'confiabilidad_pct': conf,
                }

            kpis_mes = month_stats(month)
            kpis_prev = month_stats(prev)

            # Cumplimiento del mes: programadas en el mes -> % cerradas
            prog_mes = [o for o in ots if (o.scheduled_date or '')[:7] == month]
            cerradas_prog = [o for o in prog_mes if o.status == 'Cerrada']
            kpis_mes['programadas'] = len(prog_mes)
            kpis_mes['cumplimiento_pct'] = (
                round(len(cerradas_prog) / len(prog_mes) * 100, 1) if prog_mes else None)

            # Tiempo de respuesta aviso->cierre en el mes
            resp = []
            for o in closed:
                if _ot_close_month(o) != month or not o.notice_id:
                    continue
                n = o.notice
                try:
                    d1 = dt.date.fromisoformat(str(n.request_date)[:10])
                    d2 = dt.date.fromisoformat(str(o.real_end_date)[:10])
                    resp.append((d2 - d1).days)
                except Exception:
                    pass
            kpis_mes['respuesta_dias'] = round(sum(resp) / len(resp), 1) if resp else None

            # ── Pareto de fallas (mes y ultimos 6 meses) ─────────────────
            def pareto(months_set):
                buckets = {}
                total = 0
                for o in ots:
                    if _mtype(o) != 'correctivo' or _ot_close_month(o) not in months_set:
                        continue
                    total += 1
                    key = (o.failure_mode or 'SIN MODO').strip().upper()
                    b = buckets.setdefault(key, {'label': key, 'count': 0, 'downtime_h': 0.0})
                    b['count'] += 1
                    b['downtime_h'] += _downtime(o)
                items = sorted(buckets.values(), key=lambda x: (-x['count'], -x['downtime_h']))
                cum = 0
                for it in items:
                    cum += it['count']
                    it['downtime_h'] = round(it['downtime_h'], 1)
                    it['cum_pct'] = round(cum / total * 100, 1) if total else 0
                return {'total': total, 'items': items[:12]}

            m6 = set(_months_back(month, 6))
            pareto_mes = pareto({month})
            pareto_6m = pareto(m6)

            # ── Top equipos por downtime (6 meses) ───────────────────────
            eq_buckets = {}
            for o in ots:
                if _mtype(o) != 'correctivo' or _ot_close_month(o) not in m6:
                    continue
                if o.equipment_id and o.equipment_id in eq_map:
                    e = eq_map[o.equipment_id]
                    key = f"[{e.tag}] {e.name}" if e.tag else e.name
                    eid = e.id
                else:
                    key, eid = '(sin equipo)', None
                b = eq_buckets.setdefault(key, {'equipo': key, 'equipment_id': eid,
                                                'fallas': 0, 'downtime_h': 0.0})
                b['fallas'] += 1
                b['downtime_h'] += _downtime(o)
            top_equipos = sorted(eq_buckets.values(),
                                 key=lambda x: (-x['downtime_h'], -x['fallas']))[:8]
            for t in top_equipos:
                t['downtime_h'] = round(t['downtime_h'], 1)

            # ── Tendencia y consolidado 12 meses ─────────────────────────
            trend = [month_stats(ym) for ym in _months_back(month, 12)]

            # ── Indicadores por semana del mes seleccionado ──────────────
            dias_m_sel = kpis_mes['dias_mes']
            en_curso_sel = kpis_mes['en_curso']
            semanas = []
            for w in range(5):
                d1 = 1 + 7 * w
                if d1 > dias_m_sel:
                    break
                d2 = dias_m_sel if w == 4 else min(d1 + 6, dias_m_sel)
                ini, fin = f"{month}-{d1:02d}", f"{month}-{d2:02d}"

                def in_week(o):
                    d = o.real_end_date or o.real_start_date or o.scheduled_date
                    return d and ini <= str(d)[:10] <= fin

                mes_w = [o for o in closed if in_week(o)]
                corr_w = [o for o in mes_w if _mtype(o) == 'correctivo']
                proa_w = [o for o in mes_w if _mtype(o) in ('preventivo', 'predictivo')]
                mix_w = len(corr_w) + len(proa_w)
                dt_w = sum(_downtime(o) for o in mes_w)
                mttr_vals_w = [float(o.real_duration) for o in corr_w if o.real_duration]

                # Semana futura (mes en curso): sin KPIs de horas
                futura = en_curso_sel and d1 > hoy.day
                if en_curso_sel:
                    dias_ef = max(0, min(d2, hoy.day) - d1 + 1)
                else:
                    dias_ef = d2 - d1 + 1
                horas_w = dias_ef * 24
                uptime_w = max(horas_w - dt_w, 0)
                mtbf_w = round(uptime_w / len(corr_w), 1) if corr_w and horas_w else None
                disp_w = round(uptime_w / horas_w * 100, 2) if horas_w else None

                prog_w = [o for o in ots if o.scheduled_date
                          and ini <= str(o.scheduled_date)[:10] <= fin]
                cerr_w = [o for o in prog_w if o.status == 'Cerrada']

                semanas.append({
                    'semana': f"Sem {w + 1}",
                    'rango': f"{d1:02d}-{d2:02d}",
                    'futura': futura,
                    'closed_total': len(mes_w),
                    'correctivas': len(corr_w),
                    'proactivas': len(proa_w),
                    'mejoras': len([o for o in mes_w if _mtype(o) == 'mejora']),
                    'proactive_pct': round(len(proa_w) / mix_w * 100, 1) if mix_w else None,
                    'downtime_h': round(dt_w, 1),
                    'mttr_h': (round(sum(mttr_vals_w) / len(mttr_vals_w), 1)
                               if mttr_vals_w else None),
                    'mtbf_h': mtbf_w,
                    'disponibilidad_pct': disp_w,
                    'programadas': len(prog_w),
                    'cumplimiento_pct': (round(len(cerr_w) / len(prog_w) * 100, 1)
                                         if prog_w else None),
                })

            # ── Backlog (foto actual) ────────────────────────────────────
            aging = {'<30': 0, '30-60': 0, '>60': 0, 'sin_fecha': 0}
            for o in open_ots:
                if not o.scheduled_date:
                    aging['sin_fecha'] += 1
                    continue
                try:
                    d = dt.date.fromisoformat(str(o.scheduled_date)[:10])
                    dias = (hoy - d).days
                    aging['>60' if dias > 60 else ('30-60' if dias > 30 else '<30')] += 1
                except Exception:
                    aging['sin_fecha'] += 1
            backlog = {
                'total': len(open_ots),
                'con_tecnico': len([o for o in open_ots if o.technician_id]),
                'programadas': len([o for o in open_ots if o.status == 'Programada']),
                'horas_estimadas': round(sum(float(o.estimated_duration or 0) for o in open_ots), 1),
                'aging': aging,
            }

            # ── Rutinas y predictivo ─────────────────────────────────────
            lub_pts = LubricationPoint.query.filter_by(is_active=True).all()
            insp_pts = InspectionRoute.query.filter_by(is_active=True).all()
            mon_pts = MonitoringPoint.query.filter_by(is_active=True).all()

            def sem_counts(points):
                c = defaultdict(int)
                for p in points:
                    c[(p.semaphore_status or 'PENDIENTE').upper()] += 1
                return dict(c)

            rutinas = {
                'lubricacion': sem_counts(lub_pts),
                'inspeccion': sem_counts(insp_pts),
                'monitoreo': sem_counts(mon_pts),
            }

            rot = RotativeAsset.query.filter_by(is_active=True).all()
            CATS = ('MOTOR', 'BOMBA', 'MOTORREDUCTOR', 'CAJA REDUCTORA', 'REDUCTOR')
            rot_pred = [a for a in rot
                        if getattr(a, 'is_electric_motor', False)
                        or any(c in (a.category or '').upper() for c in CATS)]
            electricos = [a for a in rot_pred if getattr(a, 'is_electric_motor', False)]
            predictivo = {
                'activos_criticos': len(rot_pred),
                'electricos': len(electricos),
                'megado_hecho': len([a for a in electricos if a.last_megado_date]),
                'megado_pendiente': len([a for a in electricos if not a.last_megado_date]),
                'megado_rojo': len([a for a in electricos if (a.megado_status or '') == 'ROJO']),
            }

            # ── Almacen / proveedores ────────────────────────────────────
            items_alm = WarehouseItem.query.filter_by(is_active=True).all()
            almacen = {
                'items': len(items_alm),
                'bajo_minimo': len([i for i in items_alm
                                    if i.min_stock and (i.stock or 0) <= i.min_stock]),
                'quiebres': len([i for i in items_alm
                                 if (i.stock or 0) == 0 and (i.min_stock or 0) > 0]),
            }
            informes = {
                'requeridos': len([o for o in ots if o.report_required]),
                'pendientes': len([o for o in ots if o.report_required
                                   and (o.report_status or 'PENDIENTE') != 'RECIBIDO'
                                   and not (o.report_url or '').strip()]),
            }

            # ── Impacto en produccion: TM y sacos no producidos ──────────
            # Misma metodologia del modulo Produccion vs Mtto:
            # tons_per_hour = rendimiento mensual / horas operativas de la
            # meta del area; TM perdidas = downtime del area x tons_per_hour.
            produccion = {'disponible': False}
            try:
                goals_map = _goals_por_area()
                resolver_area, _eqm = _area_resolver()

                def tons_mes(ym, acumular_equipos=None):
                    total_tons = 0.0
                    por_area = {}
                    for o in closed:
                        if _ot_close_month(o) != ym:
                            continue
                        dtx = _downtime(o)
                        if dtx <= 0:
                            continue
                        aid = resolver_area(o)
                        if not aid or aid not in goals_map:
                            continue
                        goal = _goal_para(goals_map.get(aid), ym)
                        if not goal:
                            continue
                        tph = _tons_per_hour(goal)
                        tons = dtx * tph
                        total_tons += tons
                        por_area[aid] = por_area.get(aid, 0.0) + tons
                        if acumular_equipos is not None and o.equipment_id:
                            acumular_equipos[o.equipment_id] = (
                                acumular_equipos.get(o.equipment_id, 0.0) + tons)
                    return total_tons, por_area

                if goals_map:
                    eq_tons = {}
                    tons_sel, tons_area_sel = tons_mes(month, eq_tons)
                    tons_prev, _pa = tons_mes(prev)
                    serie = []
                    for ym in _months_back(month, 12):
                        t, _ = tons_mes(ym)
                        serie.append({'month': ym, 'tons_lost': round(t, 1),
                                      'sacks_lost': int(t * 1000 / SACK_KG)})
                    meta_total = 0.0
                    for aid in goals_map:
                        g = _goal_para(goals_map[aid], month)
                        if g and g.monthly_target_tons:
                            meta_total += float(g.monthly_target_tons)

                    from models import Area as _Area
                    area_names = {a.id: a.name for a in _Area.query.all()}
                    top_eq = sorted(eq_tons.items(), key=lambda x: -x[1])[:8]

                    # Metas y rendimientos vigentes por area (para la lamina
                    # de produccion: de donde sale cada TM/h)
                    metas = []
                    for aid, lst in goals_map.items():
                        g = _goal_para(lst, month)
                        if not g:
                            continue
                        t_lost = tons_area_sel.get(aid, 0.0)
                        meta_a = float(g.monthly_target_tons or 0)
                        metas.append({
                            'area': area_names.get(aid, f'Area {aid}'),
                            'periodo_meta': g.goal_period,
                            'meta_tons': round(meta_a, 1),
                            'rendimiento_tons': round(float(g.monthly_avg_yield_tons or 0), 1),
                            'horas_mes': round(float(g.operating_hours_month or 720.0), 0),
                            'tons_por_hora': round(_tons_per_hour(g), 3),
                            'tons_lost': round(t_lost, 1),
                            'sacks_lost': int(t_lost * 1000 / SACK_KG),
                            'pct_de_su_meta': (round(t_lost / meta_a * 100, 2)
                                               if meta_a else None),
                        })
                    metas.sort(key=lambda x: (-x['tons_lost'], x['area']))

                    produccion = {
                        'disponible': True,
                        'tons_lost_mes': round(tons_sel, 1),
                        'sacks_lost_mes': int(tons_sel * 1000 / SACK_KG),
                        'tons_lost_prev': round(tons_prev, 1),
                        'meta_mes_tons': round(meta_total, 1),
                        'pct_de_meta': (round(tons_sel / meta_total * 100, 2)
                                        if meta_total else None),
                        'tons_lost_12m': round(sum(s['tons_lost'] for s in serie), 1),
                        'sacks_lost_12m': int(sum(s['tons_lost'] for s in serie) * 1000 / SACK_KG),
                        'serie': serie,
                        'por_area': sorted([
                            {'area': area_names.get(aid, f'Area {aid}'),
                             'tons_lost': round(t, 1),
                             'sacks_lost': int(t * 1000 / SACK_KG)}
                            for aid, t in tons_area_sel.items()], key=lambda x: -x['tons_lost']),
                        'top_equipos': [
                            {'equipo': (f"[{eq_map[eid].tag}] {eq_map[eid].name}"
                                        if eid in eq_map and eq_map[eid].tag
                                        else (eq_map[eid].name if eid in eq_map else f'Eq {eid}')),
                             'equipment_id': eid,
                             'tons_lost': round(t, 1),
                             'sacks_lost': int(t * 1000 / SACK_KG)}
                            for eid, t in top_eq],
                        'metas': metas,
                        'sack_kg': SACK_KG,
                    }
            except Exception as _pe:
                logger.warning(f"produccion impacto skipped: {_pe}")

            # ── Programacion: resto del mes en curso + mes siguiente ─────
            tecnicos = Technician.query.filter_by(is_active=True).count()

            def _ot_row(o):
                e = eq_map.get(o.equipment_id)
                return {
                    'code': o.code or f'OT-{o.id}',
                    'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                    'tipo': o.maintenance_type or '-',
                    'fecha': o.scheduled_date,
                    'horas': float(o.estimated_duration or 0),
                    'descripcion': (o.description or '')[:110],
                    'status': o.status,
                }

            def build_programa(ym, desde_dia=1):
                """Programa del mes ym, desde el dia `desde_dia` (para el mes
                en curso: solo lo que queda)."""
                dias_m = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
                d_ini = f"{ym}-{desde_dia:02d}"
                d_fin = f"{ym}-{dias_m:02d}"

                ots_win = [o for o in open_ots
                           if o.scheduled_date and d_ini <= str(o.scheduled_date)[:10] <= d_fin]

                def due(points, attr):
                    out = []
                    for p in points:
                        d = getattr(p, attr, None)
                        if d and d_ini <= str(d)[:10] <= d_fin:
                            out.append(str(d)[:10])
                    # Vencidos arrastrados: si estamos en el mes en curso,
                    # lo vencido ANTES de hoy tambien es carga pendiente
                    if desde_dia > 1:
                        for p in points:
                            d = getattr(p, attr, None)
                            if d and str(d)[:10] < d_ini:
                                out.append(d_ini)  # se cuenta en la 1ra semana restante
                    return out

                lub_due = due(lub_pts, 'next_due_date')
                insp_due = due(insp_pts, 'next_due_date')
                mon_due = due(mon_pts, 'next_due_date')
                meg_due = due(electricos, 'next_megado_due')

                def por_semana(fechas):
                    sem = [0, 0, 0, 0, 0]
                    for f in fechas:
                        dia = int(f[8:10])
                        sem[min((dia - 1) // 7, 4)] += 1
                    return sem

                habiles = sum(1 for d in range(desde_dia, dias_m + 1)
                              if dt.date(int(ym[:4]), int(ym[5:7]), d).weekday() < 6)
                capacidad_h = tecnicos * 8 * habiles
                carga_h = sum(float(o.estimated_duration or 0) for o in ots_win)

                return {
                    'month': ym,
                    'label': _month_label(ym),
                    'parcial': desde_dia > 1,
                    'desde': d_ini,
                    'ots_programadas': [_ot_row(o) for o in
                                        sorted(ots_win, key=lambda x: x.scheduled_date or '')][:120],
                    'rutinas_semana': {
                        'semanas': ['Sem 1 (1-7)', 'Sem 2 (8-14)', 'Sem 3 (15-21)',
                                    'Sem 4 (22-28)', 'Sem 5 (29+)'],
                        'lubricacion': por_semana(lub_due),
                        'inspeccion': por_semana(insp_due),
                        'monitoreo': por_semana(mon_due),
                        'megado': por_semana(meg_due),
                    },
                    'totales_rutinas': {
                        'lubricacion': len(lub_due), 'inspeccion': len(insp_due),
                        'monitoreo': len(mon_due), 'megado': len(meg_due),
                    },
                    'capacidad': {
                        'tecnicos': tecnicos, 'dias_habiles': habiles,
                        'horas_disponibles': capacidad_h,
                        'horas_programadas': round(carga_h, 1),
                        'utilizacion_pct': (round(carga_h / capacidad_h * 100, 1)
                                            if capacidad_h else None),
                    },
                }

            # Resto del mes seleccionado (solo aplica si es el mes en curso)
            programa_actual = (build_programa(month, desde_dia=hoy.day)
                               if month == mes_actual else None)
            programa = build_programa(nxt)
            programa['ots_sin_fecha'] = len([o for o in open_ots if not o.scheduled_date])

            paradas_prox = []
            try:
                for s in Shutdown.query.all():
                    if s.shutdown_date and str(s.shutdown_date)[:10] >= hoy.isoformat():
                        paradas_prox.append({
                            'code': getattr(s, 'code', None), 'name': s.name,
                            'fecha': str(s.shutdown_date)[:10],
                            'planificada': bool(getattr(s, 'is_planned', True)),
                        })
                paradas_prox.sort(key=lambda x: x['fecha'])
            except Exception:
                pass
            programa['paradas_proximas'] = paradas_prox[:10]

            return {
                'meta': {
                    'month': month, 'label': _month_label(month),
                    'prev_label': _month_label(prev),
                    'en_curso': month == mes_actual,
                    'dia_hoy': hoy.day,
                    'generated_at': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                },
                'kpis_mes': kpis_mes,
                'kpis_prev': kpis_prev,
                'semanas': semanas,
                'pareto_mes': pareto_mes,
                'pareto_6m': pareto_6m,
                'top_equipos': top_equipos,
                'trend': trend,
                'backlog': backlog,
                'rutinas': rutinas,
                'predictivo': predictivo,
                'almacen': almacen,
                'informes': informes,
                'produccion': produccion,
                'programa_actual': programa_actual,
                'programa': programa,
            }
        except Exception:
            logger.exception('diagnostico build error')
            raise

    @app.route('/api/diagnostico/data', methods=['GET'])
    def diagnostico_data():
        try:
            return jsonify(_build_diagnostico(request.args.get('month')))
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Evolucion mensual por alcance (planta / area / equipo) ────────────

    @app.route('/api/diagnostico/evolucion', methods=['GET'])
    def diagnostico_evolucion():
        """Indicadores mes a mes para el alcance elegido (drill-down):
        sin filtro = planta; ?area_id=N = un area; ?equipment_id=N = un
        equipo. Incluye TM no producidas si el area tiene meta de produccion.
        """
        try:
            hoy = dt.date.today()
            mes_actual = hoy.strftime('%Y-%m')
            month = (request.args.get('month') or mes_actual)[:7]
            n = min(request.args.get('months', default=12, type=int), 24)
            area_id = request.args.get('area_id', type=int)
            equipment_id = request.args.get('equipment_id', type=int)

            resolver_area, eq_map = _area_resolver()
            goals_map = _goals_por_area()

            closed = [o for o in WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all()]

            def en_alcance(o):
                if equipment_id:
                    return o.equipment_id == equipment_id
                if area_id:
                    return resolver_area(o) == area_id
                return True

            serie = []
            for ym in _months_back(month, n):
                mes = [o for o in closed if _ot_close_month(o) == ym and en_alcance(o)]
                corr = [o for o in mes if _mtype(o) == 'correctivo']
                dt_total = sum(_downtime(o) for o in mes)

                dias_m = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
                dias_ef = hoy.day if ym == mes_actual else dias_m
                horas = max(dias_ef * 24, 1)
                uptime = max(horas - dt_total, 0)
                n_f = len(corr)

                tons = 0.0
                for o in mes:
                    dtx = _downtime(o)
                    if dtx <= 0:
                        continue
                    aid = resolver_area(o)
                    if aid and aid in goals_map:
                        g = _goal_para(goals_map[aid], ym)
                        if g:
                            tons += dtx * _tons_per_hour(g)

                serie.append({
                    'month': ym,
                    'en_curso': ym == mes_actual,
                    'fallas': n_f,
                    'ots_cerradas': len(mes),
                    'downtime_h': round(dt_total, 1),
                    'disponibilidad_pct': round(uptime / horas * 100, 2),
                    'mtbf_h': round(uptime / n_f, 1) if n_f else None,
                    'mttr_h': round(dt_total / n_f, 1) if n_f and dt_total else None,
                    'tons_lost': round(tons, 1),
                })

            etiqueta = 'Planta completa'
            if equipment_id and equipment_id in eq_map:
                e = eq_map[equipment_id]
                etiqueta = f"[{e.tag}] {e.name}" if e.tag else e.name
            elif area_id:
                from models import Area as _Area
                a = _Area.query.get(area_id)
                etiqueta = a.name if a else f'Area {area_id}'

            return jsonify({'alcance': etiqueta, 'serie': serie})
        except Exception as e:
            logger.exception('diagnostico_evolucion error')
            return jsonify({'error': str(e)}), 500

    # ── Drill-down: OTs detras de un valor del grafico ────────────────────

    @app.route('/api/diagnostico/ots-detail', methods=['GET'])
    def diagnostico_ots_detail():
        """OTs que explican cualquier punto de los graficos del diagnostico
        (filtro dinamico de los drill-down).

        Query:
          month=YYYY-MM, window=mes|6m         ventana por mes de cierre
          desde=YYYY-MM-DD & hasta=YYYY-MM-DD  rango exacto (barras semanales)
          tipo=correctivo|proactivo|preventivo|predictivo|mejora|todas
               (default: correctivo, para Pareto y equipos criticos)
          failure_mode=..., equipment_id=N, sin_equipo=1
          con_downtime=1   solo OTs que causaron horas de parada
          programadas=1    OTs PROGRAMADAS en el rango, cualquier estado
                           (drill-down de cumplimiento)
          tons=1           agrega TM y sacos de harina no producidos por OT
        """
        try:
            hoy = dt.date.today()
            month = (request.args.get('month') or hoy.strftime('%Y-%m'))[:7]
            window = (request.args.get('window') or '6m').lower()
            fm = (request.args.get('failure_mode') or '').strip().upper()
            eq_id = request.args.get('equipment_id', type=int)
            sin_equipo = request.args.get('sin_equipo') == '1'
            tipo = (request.args.get('tipo') or 'correctivo').strip().lower()
            desde = (request.args.get('desde') or '')[:10]
            hasta = (request.args.get('hasta') or '')[:10]
            con_downtime = request.args.get('con_downtime') == '1'
            programadas = request.args.get('programadas') == '1'
            con_tons = request.args.get('tons') == '1'

            months = {month} if window == 'mes' else set(_months_back(month, 6))
            eq_map = {e.id: e for e in Equipment.query.all()}
            if con_tons:
                goals_map = _goals_por_area()
                resolver_area, _em = _area_resolver()

            def tipo_ok(o):
                if tipo == 'todas':
                    return True
                mt = _mtype(o)
                if tipo == 'proactivo':
                    return mt in ('preventivo', 'predictivo')
                return mt == tipo

            rows = []
            for o in WorkOrder.query.all():
                if programadas:
                    f = str(o.scheduled_date)[:10] if o.scheduled_date else ''
                    if not f:
                        continue
                    if desde and hasta:
                        if not (desde <= f <= hasta):
                            continue
                    elif f[:7] not in months:
                        continue
                    # En modo programadas el default (correctivo) no filtra:
                    # el cumplimiento se mide sobre TODO lo programado
                    if tipo != 'correctivo' and not tipo_ok(o):
                        continue
                else:
                    if not tipo_ok(o):
                        continue
                    if desde and hasta:
                        # Rango exacto: misma fecha que usan las barras
                        # semanales (solo OTs cerradas)
                        if o.status != 'Cerrada':
                            continue
                        d = o.real_end_date or o.real_start_date or o.scheduled_date
                        if not d or not (desde <= str(d)[:10] <= hasta):
                            continue
                    elif _ot_close_month(o) not in months:
                        continue
                if fm and (o.failure_mode or 'SIN MODO').strip().upper() != fm:
                    continue
                if eq_id and o.equipment_id != eq_id:
                    continue
                if sin_equipo and o.equipment_id:
                    continue
                dt_h = _downtime(o)
                if con_downtime and dt_h <= 0:
                    continue
                e = eq_map.get(o.equipment_id)
                row = {
                    'code': o.code or f'OT-{o.id}',
                    'fecha': str(o.scheduled_date if programadas else
                                 (o.real_end_date or o.scheduled_date or '-'))[:10],
                    'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                    'tipo': o.maintenance_type or '-',
                    'modo': (o.failure_mode or '-'),
                    'status': o.status,
                    'downtime_h': round(dt_h, 1),
                    'duracion_h': float(o.real_duration or 0),
                    'descripcion': (o.description or '')[:130],
                    'ejecucion': (o.execution_comments or '')[:130],
                }
                if con_tons:
                    tons = 0.0
                    if dt_h > 0:
                        aid = resolver_area(o)
                        if aid and aid in goals_map:
                            g = _goal_para(goals_map[aid], _ot_close_month(o) or month)
                            if g:
                                tons = dt_h * _tons_per_hour(g)
                    row['tons_lost'] = round(tons, 1)
                    row['sacks_lost'] = int(tons * 1000 / SACK_KG)
                rows.append(row)

            if con_tons:
                rows.sort(key=lambda r: (-r.get('tons_lost', 0), -r['downtime_h']))
            elif programadas:
                rows.sort(key=lambda r: r['fecha'])
            else:
                rows.sort(key=lambda r: (-r['downtime_h'], r['fecha']))
            return jsonify({'total': len(rows), 'rows': rows[:80]})
        except Exception as e:
            logger.exception('diagnostico_ots_detail error')
            return jsonify({'error': str(e)}), 500

    # ── Narrativa ejecutiva con DeepSeek (asincrona) ──────────────────────
    # DeepSeek puede tardar 30-90s y los proxies (Render/gunicorn) cortan la
    # request devolviendo una pagina HTML -> "Unexpected token '<'" en el
    # navegador. Por eso el POST lanza un hilo y responde al instante con un
    # job_id; el frontend consulta GET /narrativa/<job_id> hasta tener el texto.
    _narrativa_jobs = {}

    def _limpiar_jobs():
        import time as _t
        ahora = _t.time()
        viejos = [k for k, v in _narrativa_jobs.items() if ahora - v.get('ts', 0) > 1800]
        for k in viejos:
            _narrativa_jobs.pop(k, None)

    @app.route('/api/diagnostico/narrativa/<job_id>', methods=['GET'])
    def diagnostico_narrativa_status(job_id):
        job = _narrativa_jobs.get(job_id)
        if not job:
            return jsonify({'error': 'Trabajo no encontrado (expiro o el servidor se reinicio). Vuelve a generar.'}), 404
        return jsonify({k: v for k, v in job.items() if k != 'ts'})

    @app.route('/api/diagnostico/narrativa', methods=['POST'])
    def diagnostico_narrativa():
        try:
            data = request.get_json(force=True) or {}
            k = data.get('kpis_mes', {})
            kp = data.get('kpis_prev', {})
            en_curso = data.get('meta', {}).get('en_curso')
            resumen = [
                f"MES ANALIZADO: {data.get('meta', {}).get('label', '?')}"
                + (f" (EN CURSO: dia {data.get('meta', {}).get('dia_hoy')} de "
                   f"{k.get('dias_mes')}, KPIs parciales)" if en_curso else ""),
                f"OTs cerradas: {k.get('closed_total')} (correctivas {k.get('correctivas')}, "
                f"proactivas {k.get('proactivas')}, mejoras {k.get('mejoras')})",
                f"% proactivo: {k.get('proactive_pct')}% (mes anterior: {kp.get('proactive_pct')}%) — meta SMRP >75%",
                f"MTTR: {k.get('mttr_h')} h (ant: {kp.get('mttr_h')}) | MTBF: {k.get('mtbf_h')} h "
                f"(ant: {kp.get('mtbf_h')}) | Disponibilidad: {k.get('disponibilidad_pct')}% "
                f"(ant: {kp.get('disponibilidad_pct')}%) | Confiabilidad semanal: {k.get('confiabilidad_pct')}%",
                f"Downtime: {k.get('downtime_h')} h (anterior: {kp.get('downtime_h')} h)",
                f"Cumplimiento de programa: {k.get('cumplimiento_pct')}% de {k.get('programadas')} programadas — meta >90%",
                f"Respuesta aviso a cierre: {k.get('respuesta_dias')} dias",
            ]
            par = data.get('pareto_mes', {})
            if par.get('items'):
                resumen.append("PARETO DEL MES (modo: fallas / horas parada): " + "; ".join(
                    f"{i['label']}: {i['count']}/{i['downtime_h']}h" for i in par['items'][:6]))
            teq = data.get('top_equipos') or []
            if teq:
                resumen.append("TOP EQUIPOS 6 MESES (downtime): " + "; ".join(
                    f"{t['equipo']}: {t['fallas']} fallas/{t['downtime_h']}h" for t in teq[:5]))
            tr = data.get('trend') or []
            if tr:
                resumen.append("TENDENCIA (mes: %proactivo/disp%/downtime h): " + "; ".join(
                    f"{t['month']}: {t['proactive_pct']}%/{t['disponibilidad_pct']}%/{t['downtime_h']}h"
                    for t in tr[-6:]))
            sem = data.get('semanas') or []
            if sem:
                resumen.append("SEMANAS DEL MES (cerradas/correctivas/downtime h/cumplimiento): " + "; ".join(
                    f"{s.get('semana')} [{s.get('rango')}]: {s.get('closed_total')}/"
                    f"{s.get('correctivas')}/{s.get('downtime_h')}h/{s.get('cumplimiento_pct')}%"
                    + (" FUTURA" if s.get('futura') else "")
                    for s in sem))
            bl = data.get('backlog', {})
            resumen.append(f"BACKLOG: {bl.get('total')} OTs abiertas, {bl.get('con_tecnico')} con tecnico, "
                           f"{bl.get('programadas')} programadas, aging {bl.get('aging')}")
            pred = data.get('predictivo', {})
            resumen.append(f"PREDICTIVO: {pred.get('electricos')} motores electricos, megado hecho "
                           f"{pred.get('megado_hecho')}, pendiente {pred.get('megado_pendiente')}")
            alm = data.get('almacen', {})
            resumen.append(f"ALMACEN: {alm.get('bajo_minimo')}/{alm.get('items')} bajo minimo, "
                           f"{alm.get('quiebres')} quiebres")
            inf = data.get('informes', {})
            resumen.append(f"INFORMES PROVEEDOR: {inf.get('pendientes')}/{inf.get('requeridos')} pendientes")
            prod = data.get('produccion') or {}
            if prod.get('disponible'):
                resumen.append(
                    f"IMPACTO EN PRODUCCION: el downtime del mes dejo de producir "
                    f"{prod.get('tons_lost_mes')} TM de harina ({prod.get('sacks_lost_mes')} sacos de 50kg)"
                    + (f", equivalente al {prod.get('pct_de_meta')}% de la meta mensual "
                       f"({prod.get('meta_mes_tons')} TM)" if prod.get('pct_de_meta') is not None else "")
                    + f". Mes anterior: {prod.get('tons_lost_prev')} TM. "
                    f"Acumulado 12 meses: {prod.get('tons_lost_12m')} TM "
                    f"({prod.get('sacks_lost_12m')} sacos). Top equipos por TM perdidas: "
                    + "; ".join(f"{t['equipo']}: {t['tons_lost']} TM"
                                for t in (prod.get('top_equipos') or [])[:3]))
                if prod.get('por_area'):
                    resumen.append("TM PERDIDAS POR AREA: " + "; ".join(
                        f"{a['area']}: {a['tons_lost']} TM ({a['sacks_lost']} sacos)"
                        for a in prod['por_area'][:6]))
                if prod.get('metas'):
                    resumen.append("METAS/RENDIMIENTOS VIGENTES POR AREA (meta TM / rendimiento TM / TM por hora): "
                                   + "; ".join(
                        f"{m['area']}: {m['meta_tons']}/{m['rendimiento_tons']}/{m['tons_por_hora']}"
                        for m in prod['metas'][:6]))

            pa = data.get('programa_actual')
            if pa:
                capa = pa.get('capacidad', {})
                resumen.append(f"RESTO DEL MES EN CURSO (desde {pa.get('desde')}): "
                               f"{len(pa.get('ots_programadas', []))} OTs programadas, rutinas "
                               f"{pa.get('totales_rutinas')}, capacidad restante {capa.get('horas_disponibles')}h, "
                               f"carga {capa.get('horas_programadas')}h")
            prog = data.get('programa', {})
            cap = prog.get('capacidad', {})
            resumen.append(f"PROXIMO MES ({prog.get('label')}): {len(prog.get('ots_programadas', []))} OTs "
                           f"programadas, {prog.get('ots_sin_fecha')} sin fecha, rutinas "
                           f"{prog.get('totales_rutinas')}, capacidad {cap.get('horas_disponibles')}h "
                           f"({cap.get('tecnicos')} tecnicos), carga {cap.get('horas_programadas')}h")

            system_prompt = (
                "Eres el jefe de confiabilidad de una planta industrial de procesamiento. "
                "Con los datos entregados genera un DIAGNOSTICO EJECUTIVO en espanol para "
                "presentar a gerencia y jefaturas de mantenimiento y produccion. Usa SOLO los "
                "datos proporcionados, no inventes cifras. Si el mes esta EN CURSO, indica que "
                "los KPIs son parciales y proyecta con cautela. Referencia benchmarks SMRP "
                "donde aplique (cumplimiento >90%, proactivo >75%, backlog 2-4 semanas). "
                "El analisis debe ser COMPLETO y detallado (apunta a 700-1000 palabras). "
                "El impacto en produccion se expresa SOLO en toneladas (TM) y sacos de "
                "50 kg de harina, NUNCA en dinero. "
                "Estructura EXACTA (usa estos titulos en mayusculas):\n"
                "RESUMEN EJECUTIVO\n(5-7 lineas, lo mas importante primero)\n"
                "HALLAZGOS DEL MES\n(6-9 vinetas: dato -> interpretacion -> accion concreta)\n"
                "IMPACTO EN PRODUCCION\n(si hay datos: TM y sacos no producidos, % de la meta, "
                "areas y equipos responsables, comparacion con el mes anterior)\n"
                "TENDENCIA Y COMPARACION\n(4-6 lineas sobre la evolucion de los indicadores: "
                "MTBF, MTTR, disponibilidad, % proactivo, y el comportamiento semana a semana)\n"
                "PLAN RESTO DEL MES Y PROXIMO MES\n(prioridades de la programacion y que pedir a "
                "produccion: ventanas de parada, coordinaciones)\n"
                "RIESGOS SI NO SE ACTUA\n(3-4 vinetas)\n"
                "Tono directo y gerencial. Sin markdown de codigo, sin tablas."
            )

            from bot.llm import _get_deepseek_config
            key, url = _get_deepseek_config()
            if not key:
                return jsonify({'error': 'DEEPSEEK_API_KEY no configurada en el servidor'}), 501

            import threading
            import time as _t
            import uuid
            _limpiar_jobs()
            job_id = uuid.uuid4().hex[:12]
            _narrativa_jobs[job_id] = {'status': 'PENDIENTE', 'ts': _t.time()}
            prompt_usuario = "\n".join(resumen)

            def _worker():
                import requests as _rq
                try:
                    r = _rq.post(url, headers={
                        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                    }, json={
                        'model': 'deepseek-chat',
                        'messages': [
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': prompt_usuario},
                        ],
                        'max_tokens': 3000, 'temperature': 0.3,
                    }, timeout=360)
                    if r.status_code != 200:
                        _narrativa_jobs[job_id] = {
                            'status': 'ERROR', 'ts': _t.time(),
                            'error': f'DeepSeek HTTP {r.status_code}: {r.text[:200]}'}
                        return
                    texto = r.json()['choices'][0]['message']['content']
                    _narrativa_jobs[job_id] = {'status': 'OK', 'narrativa': texto, 'ts': _t.time()}
                except Exception as e:
                    _narrativa_jobs[job_id] = {'status': 'ERROR', 'error': str(e)[:300], 'ts': _t.time()}

            threading.Thread(target=_worker, daemon=True).start()
            return jsonify({'job_id': job_id, 'status': 'PENDIENTE'})
        except Exception as e:
            logger.exception('diagnostico_narrativa error')
            return jsonify({'error': str(e)}), 500

    # ── Informe HTML descargable (plantilla ejecutiva autocontenida) ──────

    @app.route('/api/diagnostico/informe', methods=['GET'])
    def diagnostico_informe():
        """Documento HTML autocontenido del diagnostico: se descarga, se
        abre sin conexion en cualquier lugar y se imprime a PDF desde el
        navegador. Siempre la misma plantilla, datos en vivo del mes pedido.

        Query: month=YYYY-MM (periodo elegido por el usuario),
               download=1 fuerza la descarga como archivo,
               narrativa_job=<id> incrusta la narrativa IA ya generada.
        """
        try:
            d = _build_diagnostico(request.args.get('month'))
            narrativa = ''
            job = _narrativa_jobs.get((request.args.get('narrativa_job') or '').strip())
            if job and job.get('status') == 'OK':
                narrativa = job.get('narrativa') or ''
            html = render_template('informe_diagnostico.html', d=d, narrativa=narrativa)
            resp = app.make_response(html)
            resp.headers['Content-Type'] = 'text/html; charset=utf-8'
            if request.args.get('download') == '1':
                fname = ("Diagnostico_Gestion_Mantenimiento_"
                         + d['meta']['label'].replace(' ', '_') + ".html")
                resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
            return resp
        except Exception as e:
            logger.exception('diagnostico_informe error')
            return jsonify({'error': str(e)}), 500
