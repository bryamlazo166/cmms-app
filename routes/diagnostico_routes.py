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
        WorkOrder, Equipment,
        LubricationPoint, InspectionRoute, MonitoringPoint,
        RotativeAsset, WarehouseItem, Technician, Shutdown,
    )

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

    # ── Datos del diagnostico ─────────────────────────────────────────────

    @app.route('/diagnostico')
    def diagnostico_page():
        return render_template('diagnostico.html')

    @app.route('/api/diagnostico/data', methods=['GET'])
    def diagnostico_data():
        try:
            hoy = dt.date.today()
            mes_actual = hoy.strftime('%Y-%m')
            month = (request.args.get('month') or mes_actual)[:7]
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

            return jsonify({
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
                'programa_actual': programa_actual,
                'programa': programa,
            })
        except Exception as e:
            logger.exception('diagnostico_data error')
            return jsonify({'error': str(e)}), 500

    # ── Drill-down: OTs detras de un valor del grafico ────────────────────

    @app.route('/api/diagnostico/ots-detail', methods=['GET'])
    def diagnostico_ots_detail():
        """OTs correctivas que explican un punto del Pareto o de equipos.

        Query: month=YYYY-MM, window=mes|6m, failure_mode=..., equipment_id=N
        """
        try:
            hoy = dt.date.today()
            month = (request.args.get('month') or hoy.strftime('%Y-%m'))[:7]
            window = (request.args.get('window') or '6m').lower()
            fm = (request.args.get('failure_mode') or '').strip().upper()
            eq_id = request.args.get('equipment_id', type=int)
            sin_equipo = request.args.get('sin_equipo') == '1'

            months = {month} if window == 'mes' else set(_months_back(month, 6))
            eq_map = {e.id: e for e in Equipment.query.all()}

            rows = []
            for o in WorkOrder.query.filter(WorkOrder.maintenance_type == 'Correctivo').all():
                if _ot_close_month(o) not in months:
                    continue
                if fm and (o.failure_mode or 'SIN MODO').strip().upper() != fm:
                    continue
                if eq_id and o.equipment_id != eq_id:
                    continue
                if sin_equipo and o.equipment_id:
                    continue
                e = eq_map.get(o.equipment_id)
                rows.append({
                    'code': o.code or f'OT-{o.id}',
                    'fecha': (o.real_end_date or o.scheduled_date or '-')[:10],
                    'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                    'modo': (o.failure_mode or '-'),
                    'status': o.status,
                    'downtime_h': round(_downtime(o), 1),
                    'duracion_h': float(o.real_duration or 0),
                    'descripcion': (o.description or '')[:130],
                    'ejecucion': (o.execution_comments or '')[:130],
                })
            rows.sort(key=lambda r: (-r['downtime_h'], r['fecha']))
            return jsonify({'total': len(rows), 'rows': rows[:80]})
        except Exception as e:
            logger.exception('diagnostico_ots_detail error')
            return jsonify({'error': str(e)}), 500

    # ── Narrativa ejecutiva con DeepSeek ──────────────────────────────────

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
                "Estructura EXACTA (usa estos titulos en mayusculas):\n"
                "RESUMEN EJECUTIVO\n(4-6 lineas, lo mas importante primero)\n"
                "HALLAZGOS DEL MES\n(5-7 vinetas: dato -> interpretacion -> accion concreta)\n"
                "TENDENCIA Y COMPARACION\n(3-5 lineas sobre la evolucion de los indicadores: "
                "MTBF, MTTR, disponibilidad, % proactivo)\n"
                "PLAN RESTO DEL MES Y PROXIMO MES\n(prioridades de la programacion y que pedir a "
                "produccion: ventanas de parada, coordinaciones)\n"
                "RIESGOS SI NO SE ACTUA\n(2-3 vinetas)\n"
                "Tono directo y gerencial. Sin markdown de codigo, sin tablas."
            )

            from bot.llm import _get_deepseek_config
            key, url = _get_deepseek_config()
            if not key:
                return jsonify({'error': 'DEEPSEEK_API_KEY no configurada en el servidor'}), 501

            import requests as _rq
            r = _rq.post(url, headers={
                'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
            }, json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': "\n".join(resumen)},
                ],
                'max_tokens': 1800, 'temperature': 0.3,
            }, timeout=90)
            if r.status_code != 200:
                return jsonify({'error': f'DeepSeek HTTP {r.status_code}: {r.text[:200]}'}), 502
            texto = r.json()['choices'][0]['message']['content']
            return jsonify({'narrativa': texto})
        except Exception as e:
            logger.exception('diagnostico_narrativa error')
            return jsonify({'error': str(e)}), 500
