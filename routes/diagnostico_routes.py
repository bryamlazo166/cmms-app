"""Diagnostico mensual de gestion de mantenimiento.

Pagina /diagnostico: informe ejecutivo con datos calculados EN VIVO desde la
BD (mismo formato siempre), narrativa generada con DeepSeek, modo presentacion
para gerencia y programacion propuesta del mes siguiente para coordinar con
produccion.
"""
import calendar
import datetime as dt
from collections import defaultdict

from flask import jsonify, render_template, request


def register_diagnostico_routes(app, db, logger):
    from models import (
        WorkOrder, MaintenanceNotice, Equipment,
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

    # ── Datos del diagnostico ─────────────────────────────────────────────

    @app.route('/diagnostico')
    def diagnostico_page():
        return render_template('diagnostico.html')

    @app.route('/api/diagnostico/data', methods=['GET'])
    def diagnostico_data():
        try:
            month = (request.args.get('month') or dt.date.today().strftime('%Y-%m'))[:7]
            prev = _prev_month(month)
            nxt = _next_month(month)

            ots = WorkOrder.query.all()
            closed = [o for o in ots if o.status == 'Cerrada']
            open_ots = [o for o in ots if (o.status or '') not in ('Cerrada', 'No Ejecutada')]

            # ── KPIs del mes vs mes anterior ─────────────────────────────
            def month_stats(ym):
                mes = [o for o in closed if _ot_close_month(o) == ym]
                corr = [o for o in mes if _mtype(o) == 'correctivo']
                proa = [o for o in mes if _mtype(o) in ('preventivo', 'predictivo')]
                mejora = [o for o in mes if _mtype(o) == 'mejora']
                mix_base = len(corr) + len(proa)
                mttr_vals = [float(o.real_duration) for o in corr if o.real_duration]
                return {
                    'month': ym,
                    'label': _month_label(ym),
                    'closed_total': len(mes),
                    'correctivas': len(corr),
                    'proactivas': len(proa),
                    'mejoras': len(mejora),
                    'proactive_pct': round(len(proa) / mix_base * 100, 1) if mix_base else 0.0,
                    'reactive_pct': round(len(corr) / mix_base * 100, 1) if mix_base else 0.0,
                    'mttr_h': round(sum(mttr_vals) / len(mttr_vals), 1) if mttr_vals else None,
                    'downtime_h': round(sum(_downtime(o) for o in mes), 1),
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

            m6 = set()
            ym = month
            for _ in range(6):
                m6.add(ym)
                ym = _prev_month(ym)

            pareto_mes = pareto({month})
            pareto_6m = pareto(m6)

            # ── Top equipos por downtime (6 meses) ───────────────────────
            eq_map = {e.id: e for e in Equipment.query.all()}
            eq_buckets = {}
            for o in ots:
                if _mtype(o) != 'correctivo' or _ot_close_month(o) not in m6:
                    continue
                if o.equipment_id and o.equipment_id in eq_map:
                    e = eq_map[o.equipment_id]
                    key = f"[{e.tag}] {e.name}" if e.tag else e.name
                else:
                    key = '(sin equipo)'
                b = eq_buckets.setdefault(key, {'equipo': key, 'fallas': 0, 'downtime_h': 0.0})
                b['fallas'] += 1
                b['downtime_h'] += _downtime(o)
            top_equipos = sorted(eq_buckets.values(),
                                 key=lambda x: (-x['downtime_h'], -x['fallas']))[:8]
            for t in top_equipos:
                t['downtime_h'] = round(t['downtime_h'], 1)

            # ── Tendencia 6 meses ────────────────────────────────────────
            trend = []
            ym = month
            for _ in range(6):
                trend.append(month_stats(ym))
                ym = _prev_month(ym)
            trend.reverse()

            # ── Backlog (foto actual) ────────────────────────────────────
            hoy = dt.date.today()
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
            def sem_counts(query):
                c = defaultdict(int)
                for p in query:
                    c[(p.semaphore_status or 'PENDIENTE').upper()] += 1
                return dict(c)

            rutinas = {
                'lubricacion': sem_counts(LubricationPoint.query.filter_by(is_active=True).all()),
                'inspeccion': sem_counts(InspectionRoute.query.filter_by(is_active=True).all()),
                'monitoreo': sem_counts(MonitoringPoint.query.filter_by(is_active=True).all()),
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

            # ── Almacen / logistica / proveedores ───────────────────────
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

            # ── Programacion propuesta del mes siguiente ─────────────────
            nxt_start = f"{nxt}-01"
            nxt_days = calendar.monthrange(int(nxt[:4]), int(nxt[5:7]))[1]
            nxt_end = f"{nxt}-{nxt_days:02d}"

            # OTs ya programadas o abiertas candidatas
            ots_nxt = [o for o in open_ots if (o.scheduled_date or '')[:7] == nxt]
            sin_fecha = [o for o in open_ots if not o.scheduled_date]

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

            # Rutinas que vencen el mes siguiente, por semana del mes
            def due_next(points, date_attr):
                out = []
                for p in points:
                    d = getattr(p, date_attr, None)
                    if d and nxt_start <= str(d)[:10] <= nxt_end:
                        out.append(str(d)[:10])
                return out

            lub_due = due_next(LubricationPoint.query.filter_by(is_active=True).all(), 'next_due_date')
            insp_due = due_next(InspectionRoute.query.filter_by(is_active=True).all(), 'next_due_date')
            mon_due = due_next(MonitoringPoint.query.filter_by(is_active=True).all(), 'next_due_date')
            meg_due = due_next(electricos, 'next_megado_due')

            def por_semana(fechas):
                sem = [0, 0, 0, 0, 0]
                for f in fechas:
                    dia = int(f[8:10])
                    sem[min((dia - 1) // 7, 4)] += 1
                return sem

            # Capacidad: tecnicos activos x 8h x dias habiles (lun-sab)
            tecnicos = Technician.query.filter_by(is_active=True).count()
            habiles = sum(1 for d in range(1, nxt_days + 1)
                          if dt.date(int(nxt[:4]), int(nxt[5:7]), d).weekday() < 6)
            capacidad_h = tecnicos * 8 * habiles
            carga_h = sum(float(o.estimated_duration or 0) for o in ots_nxt)

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

            programa = {
                'month': nxt,
                'label': _month_label(nxt),
                'ots_programadas': [_ot_row(o) for o in
                                    sorted(ots_nxt, key=lambda x: x.scheduled_date or '')][:120],
                'ots_sin_fecha': len(sin_fecha),
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
                    'utilizacion_pct': round(carga_h / capacidad_h * 100, 1) if capacidad_h else None,
                },
                'paradas_proximas': paradas_prox[:10],
            }

            return jsonify({
                'meta': {
                    'month': month, 'label': _month_label(month),
                    'prev_label': _month_label(prev),
                    'generated_at': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                },
                'kpis_mes': kpis_mes,
                'kpis_prev': kpis_prev,
                'pareto_mes': pareto_mes,
                'pareto_6m': pareto_6m,
                'top_equipos': top_equipos,
                'trend': trend,
                'backlog': backlog,
                'rutinas': rutinas,
                'predictivo': predictivo,
                'almacen': almacen,
                'informes': informes,
                'programa': programa,
            })
        except Exception as e:
            logger.exception('diagnostico_data error')
            return jsonify({'error': str(e)}), 500

    # ── Narrativa ejecutiva con DeepSeek ──────────────────────────────────

    @app.route('/api/diagnostico/narrativa', methods=['POST'])
    def diagnostico_narrativa():
        try:
            data = request.get_json(force=True) or {}
            k = data.get('kpis_mes', {})
            kp = data.get('kpis_prev', {})
            resumen = [
                f"MES ANALIZADO: {data.get('meta', {}).get('label', '?')}",
                f"OTs cerradas: {k.get('closed_total')} (correctivas {k.get('correctivas')}, "
                f"proactivas {k.get('proactivas')}, mejoras {k.get('mejoras')})",
                f"% proactivo: {k.get('proactive_pct')}% (mes anterior: {kp.get('proactive_pct')}%) — meta SMRP >75%",
                f"MTTR correctivo: {k.get('mttr_h')} h (anterior: {kp.get('mttr_h')} h)",
                f"Downtime del mes: {k.get('downtime_h')} h (anterior: {kp.get('downtime_h')} h)",
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
                "datos proporcionados, no inventes cifras. Referencia benchmarks SMRP donde "
                "aplique (cumplimiento >90%, proactivo >75%, backlog 2-4 semanas). "
                "Estructura EXACTA (usa estos titulos en mayusculas):\n"
                "RESUMEN EJECUTIVO\n(4-6 lineas, lo mas importante primero)\n"
                "HALLAZGOS DEL MES\n(5-7 vinetas: dato -> interpretacion -> accion concreta)\n"
                "COMPARACION CON EL MES ANTERIOR\n(3-4 lineas: que mejoro, que empeoro)\n"
                "PROPUESTA PARA EL PROXIMO MES\n(prioridades de la programacion y que pedir a produccion: "
                "ventanas de parada, coordinaciones)\n"
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
