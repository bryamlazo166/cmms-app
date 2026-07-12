"""Ingenieria de Confiabilidad — analisis P-F.

Pagina /analisis-pf (NO forma parte de la presentacion gerencial):
correlaciona toda la informacion del CMMS por equipo — mediciones
predictivas (monitoreo, tests electricos), anomalias de lubricacion,
hallazgos de inspeccion y fallas correctivas — sobre una linea de
tiempo (curva P-F con datos reales) y calcula, para cada falla, si
hubo SENAL PREVIA y con cuanta anticipacion (intervalo P-F observado).
"""
import datetime as dt

from flask import jsonify, render_template, request


def register_pf_analysis_routes(app, db, logger):
    from models import (
        WorkOrder, Equipment,
        MonitoringPoint, MonitoringReading,
        LubricationPoint, LubricationExecution,
        InspectionRoute, InspectionExecution,
        MotorElectricalTest, RotativeAsset,
    )

    def _d(s):
        try:
            return dt.date.fromisoformat(str(s)[:10])
        except Exception:
            return None

    def _falla_fecha(o):
        return _d(o.real_end_date) or _d(o.real_start_date) or _d(o.scheduled_date)

    @app.route('/analisis-pf')
    def pf_page():
        return render_template('analisis_pf.html')

    # ── Selector: equipos con datos ───────────────────────────────────────
    @app.route('/api/pf/equipos', methods=['GET'])
    def pf_equipos():
        try:
            eqs = Equipment.query.all()
            fallas, reads, tests, lubs, insps = {}, {}, {}, {}, {}

            for o in WorkOrder.query.filter(WorkOrder.maintenance_type == 'Correctivo').all():
                if o.equipment_id:
                    fallas[o.equipment_id] = fallas.get(o.equipment_id, 0) + 1
            mp = {p.id: p.equipment_id for p in MonitoringPoint.query.all()}
            for r in MonitoringReading.query.all():
                eid = mp.get(r.point_id)
                if eid:
                    reads[eid] = reads.get(eid, 0) + 1
            for t in MotorElectricalTest.query.all():
                if t.equipment_id:
                    tests[t.equipment_id] = tests.get(t.equipment_id, 0) + 1
            lp = {p.id: p.equipment_id for p in LubricationPoint.query.all()}
            for e in LubricationExecution.query.all():
                eid = lp.get(e.point_id)
                if eid:
                    lubs[eid] = lubs.get(eid, 0) + 1
            ir = {r.id: r.equipment_id for r in InspectionRoute.query.all()}
            for e in InspectionExecution.query.all():
                eid = ir.get(e.route_id)
                if eid:
                    insps[eid] = insps.get(eid, 0) + 1

            rows = []
            for e in eqs:
                f = fallas.get(e.id, 0)
                datos = reads.get(e.id, 0) + tests.get(e.id, 0) + lubs.get(e.id, 0) + insps.get(e.id, 0)
                if f == 0 and datos == 0:
                    continue
                rows.append({
                    'id': e.id, 'tag': e.tag, 'name': e.name,
                    'fallas': f,
                    'lecturas_monitoreo': reads.get(e.id, 0),
                    'tests_electricos': tests.get(e.id, 0),
                    'lubricaciones': lubs.get(e.id, 0),
                    'inspecciones': insps.get(e.id, 0),
                })
            rows.sort(key=lambda x: -x['fallas'])
            return jsonify(rows)
        except Exception as e:
            logger.exception('pf_equipos error')
            return jsonify({'error': str(e)}), 500

    # ── Linea de tiempo P-F de un equipo ──────────────────────────────────
    @app.route('/api/pf/timeline', methods=['GET'])
    def pf_timeline():
        try:
            eq_id = request.args.get('equipment_id', type=int)
            months = request.args.get('months', default=12, type=int)
            if not eq_id:
                return jsonify({'error': 'equipment_id requerido'}), 400
            desde = (dt.date.today() - dt.timedelta(days=months * 31)).isoformat()

            eq = Equipment.query.get_or_404(eq_id)

            # Series de monitoreo (una por punto) con limites
            series = []
            pts = MonitoringPoint.query.filter_by(equipment_id=eq_id).all()
            for p in pts:
                lecturas = [{'date': str(r.reading_date)[:10], 'value': r.value}
                            for r in p.readings if str(r.reading_date)[:10] >= desde]
                lecturas.sort(key=lambda x: x['date'])
                series.append({
                    'point_id': p.id, 'code': p.code, 'name': p.name,
                    'tipo': (p.measurement_type or 'MONITOREO').upper(),
                    'unit': p.unit,
                    'normal_max': p.normal_max, 'alarm_max': p.alarm_max,
                    'normal_min': p.normal_min, 'alarm_min': p.alarm_min,
                    'readings': lecturas,
                })

            # Tests electricos (por activo instalado en el equipo o directos)
            elec = {'MEGADO': [], 'CORRIENTE': [], 'TEMPERATURA': []}
            for t in MotorElectricalTest.query.filter_by(equipment_id=eq_id).all():
                f = str(t.test_date)[:10]
                if f < desde:
                    continue
                tt = (t.test_type or '').upper()
                if tt == 'MEGADO' and t.insulation_mohm is not None:
                    elec['MEGADO'].append({'date': f, 'value': t.insulation_mohm})
                elif tt == 'CORRIENTE':
                    vals = [v for v in (t.current_r, t.current_s, t.current_t) if v is not None]
                    if vals:
                        elec['CORRIENTE'].append({'date': f, 'value': max(vals)})
                elif tt == 'TEMPERATURA' and t.temperature_c is not None:
                    elec['TEMPERATURA'].append({'date': f, 'value': t.temperature_c})
            for k in elec:
                elec[k].sort(key=lambda x: x['date'])

            # Eventos: fallas, anomalias de lubricacion, hallazgos de inspeccion
            fallas = []
            for o in WorkOrder.query.filter(WorkOrder.equipment_id == eq_id,
                                            WorkOrder.maintenance_type == 'Correctivo').all():
                f = _falla_fecha(o)
                if not f or f.isoformat() < desde:
                    continue
                dtx = 0.0
                if getattr(o, 'caused_downtime', None):
                    dtx = float(o.downtime_hours or o.real_duration or 0)
                fallas.append({
                    'date': f.isoformat(), 'code': o.code or f'OT-{o.id}',
                    'modo': o.failure_mode or '-', 'downtime_h': round(dtx, 1),
                    'descripcion': (o.description or '')[:120],
                    'status': o.status,
                })
            fallas.sort(key=lambda x: x['date'])

            lub_events = []
            lp_ids = {p.id: p for p in LubricationPoint.query.filter_by(equipment_id=eq_id).all()}
            if lp_ids:
                for e in LubricationExecution.query.filter(
                        LubricationExecution.point_id.in_(list(lp_ids))).all():
                    f = str(e.execution_date)[:10]
                    if f < desde or not (e.leak_detected or e.anomaly_detected):
                        continue
                    p = lp_ids.get(e.point_id)
                    lub_events.append({
                        'date': f,
                        'tipo': 'FUGA' if e.leak_detected else 'ANOMALIA',
                        'punto': p.code if p else '-',
                        'comentario': (e.comments or '')[:100],
                    })
            lub_events.sort(key=lambda x: x['date'])

            insp_events = []
            ir_ids = {r.id: r for r in InspectionRoute.query.filter_by(equipment_id=eq_id).all()}
            if ir_ids:
                for e in InspectionExecution.query.filter(
                        InspectionExecution.route_id.in_(list(ir_ids))).all():
                    f = str(e.execution_date)[:10]
                    if f < desde or e.overall_result != 'CON_HALLAZGOS':
                        continue
                    r = ir_ids.get(e.route_id)
                    insp_events.append({
                        'date': f, 'ruta': r.code if r else '-',
                        'hallazgos': int(e.findings_count or 0),
                        'comentario': (e.comments or '')[:100],
                    })
            insp_events.sort(key=lambda x: x['date'])

            return jsonify({
                'equipment': {'id': eq.id, 'tag': eq.tag, 'name': eq.name},
                'desde': desde,
                'monitoring_series': series,
                'electrical': elec,
                'fallas': fallas,
                'lubricacion_anomalias': lub_events,
                'inspeccion_hallazgos': insp_events,
            })
        except Exception as e:
            logger.exception('pf_timeline error')
            return jsonify({'error': str(e)}), 500

    # ── Precursores: cuanta anticipacion tuvimos antes de cada falla ─────
    @app.route('/api/pf/precursores', methods=['GET'])
    def pf_precursores():
        """Para cada falla correctiva con equipo: busca senales previas en
        una ventana (default 45 dias): lectura de monitoreo fuera de rango,
        anomalia/fuga en lubricacion o inspeccion con hallazgos del mismo
        equipo. Devuelve el intervalo P-F observado (dias de anticipacion).
        """
        try:
            months = request.args.get('months', default=12, type=int)
            ventana = request.args.get('ventana_dias', default=45, type=int)
            desde = dt.date.today() - dt.timedelta(days=months * 31)

            eq_map = {e.id: e for e in Equipment.query.all()}

            # Indexar senales por equipo
            senales = {}  # eq_id -> list[(fecha, tipo, detalle)]

            mp = {p.id: p for p in MonitoringPoint.query.all()}
            for r in MonitoringReading.query.all():
                p = mp.get(r.point_id)
                if not p or not p.equipment_id:
                    continue
                f = _d(r.reading_date)
                if not f:
                    continue
                fuera = ((p.alarm_max is not None and r.value >= p.alarm_max)
                         or (p.alarm_min is not None and r.value <= p.alarm_min)
                         or (p.normal_max is not None and r.value > p.normal_max)
                         or (p.normal_min is not None and r.value < p.normal_min))
                if fuera:
                    senales.setdefault(p.equipment_id, []).append(
                        (f, 'MONITOREO', f"{p.code or p.name}: {r.value} {p.unit or ''}"))

            lp = {p.id: p for p in LubricationPoint.query.all()}
            for e in LubricationExecution.query.all():
                p = lp.get(e.point_id)
                if not p or not p.equipment_id or not (e.leak_detected or e.anomaly_detected):
                    continue
                f = _d(e.execution_date)
                if f:
                    senales.setdefault(p.equipment_id, []).append(
                        (f, 'LUBRICACION', 'Fuga' if e.leak_detected else 'Anomalia'))

            ir = {r.id: r for r in InspectionRoute.query.all()}
            for e in InspectionExecution.query.all():
                r = ir.get(e.route_id)
                if not r or not r.equipment_id or e.overall_result != 'CON_HALLAZGOS':
                    continue
                f = _d(e.execution_date)
                if f:
                    senales.setdefault(r.equipment_id, []).append(
                        (f, 'INSPECCION', f"{e.findings_count or 0} hallazgos"))

            for t in MotorElectricalTest.query.all():
                if not t.equipment_id or (t.status or '') not in ('AMARILLO', 'ROJO'):
                    continue
                f = _d(t.test_date)
                if f:
                    senales.setdefault(t.equipment_id, []).append(
                        (f, 'ELECTRICO', f"{t.test_type} {t.status}"))

            # Analizar fallas
            rows = []
            con_senal = 0
            anticipaciones = []
            equipos_monitoreados = set(p.equipment_id for p in mp.values() if p.equipment_id)
            for o in WorkOrder.query.filter(WorkOrder.maintenance_type == 'Correctivo',
                                            WorkOrder.status == 'Cerrada').all():
                f = _falla_fecha(o)
                if not f or f < desde or not o.equipment_id:
                    continue
                prev = [(sf, tipo, det) for (sf, tipo, det)
                        in senales.get(o.equipment_id, [])
                        if 0 <= (f - sf).days <= ventana]
                e = eq_map.get(o.equipment_id)
                mejor = max(prev, key=lambda x: (f - x[0]).days) if prev else None
                if prev:
                    con_senal += 1
                    anticipaciones.append((f - mejor[0]).days)
                rows.append({
                    'code': o.code or f'OT-{o.id}',
                    'fecha': f.isoformat(),
                    'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                    'equipment_id': o.equipment_id,
                    'modo': o.failure_mode or '-',
                    'downtime_h': round(float(o.downtime_hours or 0)
                                        if getattr(o, 'caused_downtime', None) else 0, 1),
                    'senal_previa': bool(prev),
                    'senales': [{'fecha': sf.isoformat(), 'tipo': tipo, 'detalle': det}
                                for (sf, tipo, det) in sorted(prev, key=lambda x: x[0])][:5],
                    'anticipacion_dias': (f - mejor[0]).days if mejor else None,
                    'tenia_monitoreo': o.equipment_id in equipos_monitoreados,
                })
            rows.sort(key=lambda r: r['fecha'], reverse=True)

            total = len(rows)
            resumen = {
                'fallas_analizadas': total,
                'con_senal_previa': con_senal,
                'pct_con_senal': round(con_senal / total * 100, 1) if total else 0,
                'sin_monitoreo': len([r for r in rows if not r['tenia_monitoreo']]),
                'intervalo_pf_promedio_dias': (round(sum(anticipaciones) / len(anticipaciones), 1)
                                               if anticipaciones else None),
                'ventana_dias': ventana,
            }
            return jsonify({'resumen': resumen, 'fallas': rows[:150]})
        except Exception as e:
            logger.exception('pf_precursores error')
            return jsonify({'error': str(e)}), 500
