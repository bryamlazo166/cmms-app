"""Insights automáticos del CMMS con narrativa IA.

Genera resúmenes ejecutivos consultando el estado del CMMS y pidiéndole
a DeepSeek que los narre en lenguaje para gerencia.

Endpoints:
  - GET  /api/insights/weekly-summary  → JSON con métricas + narrativa IA
  - GET  /insights                     → página con el resumen
"""
import os
import datetime as dt

import requests
from flask import jsonify, request, render_template
from sqlalchemy import func, text


DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'


def register_insights_routes(
    app, db, logger,
    WorkOrder, MaintenanceNotice, Area, Line, Equipment,
    LubricationPoint, InspectionRoute, MonitoringPoint,
    Shutdown,
    LubricationExecution=None, InspectionExecution=None, MonitoringReading=None,
):

    @app.route('/insights', methods=['GET'])
    def insights_page():
        return render_template('insights.html')

    @app.route('/optimizacion-preventivos', methods=['GET'])
    def prev_optimization_page():
        return render_template('optimizacion_preventivos.html')

    # ── Optimización del plan preventivo ────────────────────────────────

    @app.route('/api/insights/preventive-optimization', methods=['GET'])
    def preventive_optimization():
        """Analiza puntos preventivos y detecta sobre/sub-mantenimiento."""
        try:
            from utils.preventive_optimization import analyze_preventive_plan
            window_days = int(request.args.get('window_days', 90))
            min_over = int(request.args.get('min_executions_over', 3))
            min_under = int(request.args.get('min_failures_under', 2))

            data = analyze_preventive_plan(
                LubricationPoint, LubricationExecution,
                InspectionRoute, InspectionExecution,
                MonitoringPoint, MonitoringReading,
                WorkOrder,
                window_days=window_days,
                min_executions_over=min_over,
                min_failures_under=min_under,
            )

            # Enriquecer con nombres de equipo/área para UI
            equip_ids = {r['equipment_id'] for r in data['recommendations'] if r.get('equipment_id')}
            area_ids = {r['area_id'] for r in data['recommendations'] if r.get('area_id')}
            equip_map = ({e.id: e for e in Equipment.query.filter(Equipment.id.in_(equip_ids)).all()}
                         if equip_ids else {})
            # Si área no viene explícita, resolver vía equipo→línea→área
            line_ids = {e.line_id for e in equip_map.values() if e.line_id}
            line_map = ({l.id: l for l in Line.query.filter(Line.id.in_(line_ids)).all()}
                        if line_ids else {})
            area_ids |= {l.area_id for l in line_map.values() if l.area_id}
            area_map = ({a.id: a.name for a in Area.query.filter(Area.id.in_(area_ids)).all()}
                        if area_ids else {})

            for r in data['recommendations']:
                eq = equip_map.get(r.get('equipment_id'))
                r['equipment_tag'] = eq.tag if eq else '-'
                r['equipment_name'] = eq.name if eq else '-'
                aid = r.get('area_id')
                if not aid and eq and eq.line_id and eq.line_id in line_map:
                    aid = line_map[eq.line_id].area_id
                r['area_name'] = area_map.get(aid, '-') if aid else '-'

            return jsonify(data)
        except Exception as e:
            logger.error(f"preventive_optimization error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/insights/preventive-optimization/apply', methods=['POST'])
    def apply_optimization():
        """Aplica una recomendación — cambia la frecuencia del punto."""
        try:
            from utils.preventive_optimization import apply_recommendation
            data = request.get_json() or {}
            source_type = data.get('source_type')
            source_id = int(data.get('source_id') or 0)
            new_freq = int(data.get('new_frequency_days') or 0)
            if not source_type or not source_id or new_freq <= 0:
                return jsonify({"error": "source_type, source_id y new_frequency_days requeridos"}), 400
            result = apply_recommendation(
                source_type, source_id, new_freq,
                LubricationPoint=LubricationPoint,
                InspectionRoute=InspectionRoute,
                MonitoringPoint=MonitoringPoint,
                db=db,
            )
            return jsonify(result)
        except Exception as e:
            db.session.rollback()
            logger.error(f"apply_optimization error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Cumplimiento de preventivos (frecuencia REAL vs planificada) ─────
    @app.route('/cumplimiento-preventivos', methods=['GET'])
    def preventive_compliance_page():
        return render_template('cumplimiento_preventivos.html')

    _COMPLIANCE_SOURCES = {
        'lubrication': dict(point_table='lubrication_points', exec_table='lubrication_executions',
                            exec_fk='point_id', exec_date='execution_date',
                            has_lubricant=True, has_sys_comp=True, label='Lubricación'),
        'inspection':  dict(point_table='inspection_routes', exec_table='inspection_executions',
                            exec_fk='route_id', exec_date='execution_date',
                            has_lubricant=False, has_sys_comp=False, label='Inspección'),
        'monitoring':  dict(point_table='monitoring_points', exec_table='monitoring_readings',
                            exec_fk='point_id', exec_date='reading_date',
                            has_lubricant=False, has_sys_comp=True, label='Monitoreo'),
    }

    def _compliance_rows(source, window_days):
        """Calcula, por cada punto del tipo dado, la frecuencia real (intervalo
        promedio entre ejecuciones en la ventana) vs la planificada."""
        cfg = _COMPLIANCE_SOURCES[source]
        today = dt.date.today()
        cutoff = (today - dt.timedelta(days=window_days)).isoformat()
        lub_col = "p.lubricant_name" if cfg['has_lubricant'] else "NULL"
        if cfg['has_sys_comp']:
            sys_join = "LEFT JOIN systems s ON p.system_id = s.id"
            comp_join = "LEFT JOIN components c ON p.component_id = c.id"
            sys_col, comp_col = "s.name", "c.name"
        else:
            sys_join, comp_join = "", ""
            sys_col, comp_col = "NULL", "NULL"

        points = db.session.execute(text(f"""
            SELECT p.id, p.code, p.name, p.frequency_days, {lub_col},
                   e.tag, e.name, {comp_col}, {sys_col}, a.name, l.name
            FROM {cfg['point_table']} p
            LEFT JOIN equipments e ON p.equipment_id = e.id
            {comp_join}
            {sys_join}
            LEFT JOIN areas a ON p.area_id = a.id
            LEFT JOIN lines l ON p.line_id = l.id
            WHERE p.is_active = true
        """)).fetchall()

        execs = db.session.execute(text(f"""
            SELECT {cfg['exec_fk']} AS fk, {cfg['exec_date']} AS d
            FROM {cfg['exec_table']}
            WHERE substr({cfg['exec_date']}, 1, 10) >= :cutoff
            ORDER BY {cfg['exec_fk']}, {cfg['exec_date']}
        """), {"cutoff": cutoff}).fetchall()

        from collections import defaultdict
        by_point = defaultdict(list)
        for r in execs:
            ds = str(r[1])[:10] if r[1] else None
            if ds:
                try:
                    by_point[r[0]].append(dt.date.fromisoformat(ds))
                except Exception:
                    pass

        out = []
        for p in points:
            pid, code, name, plan, lubricant, etag, ename, cname, sname, aname, lname = p
            plan = plan or 0
            dates = sorted(by_point.get(pid, []))
            n = len(dates)
            real_freq = None
            if n >= 2:
                intervals = [(dates[i] - dates[i - 1]).days for i in range(1, n)]
                intervals = [iv for iv in intervals if iv > 0]
                if intervals:
                    real_freq = round(sum(intervals) / len(intervals), 1)
            last = dates[-1].isoformat() if dates else None
            days_since = (today - dates[-1]).days if dates else None
            if real_freq is None:
                estado, cumpl = 'SIN_DATOS', None
            else:
                cumpl = round(plan / real_freq * 100) if (plan and real_freq) else None
                if plan and real_freq > plan * 1.2:
                    estado = 'TARDE'
                elif plan and real_freq < plan * 0.8:
                    estado = 'SEGUIDO'
                else:
                    estado = 'AL_DIA'
            atrasado = bool(plan and days_since is not None and days_since > plan * 1.5)
            out.append({
                'source_type': source,
                'source_label': cfg['label'],
                'code': code or f'{source[:3].upper()}-{pid}',
                'name': name or '',
                'lubricant': lubricant or '',
                'equipment_tag': etag or '',
                'equipment_name': ename or '',
                'component_name': cname or '',
                'system_name': sname or '',
                'area_name': aname or '',
                'line_name': lname or '',
                'planned_frequency_days': plan,
                'real_frequency_days': real_freq,
                'executions': n,
                'last_execution': last,
                'days_since_last': days_since,
                'compliance_pct': cumpl,
                'estado': estado,
                'atrasado': atrasado,
            })
        return out

    @app.route('/api/insights/preventive-compliance', methods=['GET'])
    def preventive_compliance():
        """Frecuencia REAL vs planificada para lubricacion, inspeccion y monitoreo."""
        try:
            window_days = int(request.args.get('window_days') or 365)
        except Exception:
            window_days = 365
        source = (request.args.get('source') or 'all').lower()
        srcs = ['lubrication', 'inspection', 'monitoring'] if source == 'all' else [source]
        srcs = [s for s in srcs if s in _COMPLIANCE_SOURCES]
        if not srcs:
            return jsonify({"error": "source invalido"}), 400
        try:
            rows = []
            for s in srcs:
                rows.extend(_compliance_rows(s, window_days))
            keymap = {'AL_DIA': 'al_dia', 'TARDE': 'tarde', 'SEGUIDO': 'seguido', 'SIN_DATOS': 'sin_datos'}
            summary = {'al_dia': 0, 'tarde': 0, 'seguido': 0, 'sin_datos': 0}
            for r in rows:
                summary[keymap[r['estado']]] += 1
            estado_rank = {'TARDE': 0, 'SEGUIDO': 1, 'AL_DIA': 2, 'SIN_DATOS': 3}
            rows.sort(key=lambda r: (estado_rank.get(r['estado'], 9), -(r['days_since_last'] or 0)))
            return jsonify({'rows': rows, 'summary': summary, 'window_days': window_days, 'total': len(rows)})
        except Exception as e:
            logger.exception(f"preventive_compliance error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/insights/weekly-summary', methods=['GET'])
    def weekly_summary():
        """Resumen de la semana anterior o las últimas N semanas.

        Devuelve SOLO métricas (sin narrativa IA) para ser rápido.
        La narrativa se pide aparte desde /api/insights/narrative
        para no superar timeouts de gateway (60s).
        """
        try:
            weeks_back = int(request.args.get('weeks', 1))
            end_date = dt.date.today()
            start_date = end_date - dt.timedelta(days=7 * weeks_back)
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()
            period_label = f"últimos {7 * weeks_back} días ({start_iso} → {end_iso})"

            # Query directa: sólo OTs que potencialmente estén en ventana
            ots_in_window = WorkOrder.query.filter(
                ((WorkOrder.real_end_date >= start_iso) & (WorkOrder.real_end_date <= end_iso))
                | ((WorkOrder.real_end_date.is_(None)) &
                   (WorkOrder.scheduled_date >= start_iso) &
                   (WorkOrder.scheduled_date <= end_iso))
            ).all()

            closed = [ot for ot in ots_in_window if ot.status == 'Cerrada']
            preventive = sum(1 for ot in closed if (ot.maintenance_type or '').lower().startswith('prev'))
            corrective = sum(1 for ot in closed if (ot.maintenance_type or '').lower().startswith('corr'))

            # Downtime acumulado
            total_downtime = 0.0
            for ot in closed:
                if not ot.caused_downtime:
                    continue
                try:
                    dh = float(ot.downtime_hours or ot.real_duration or 0)
                    total_downtime += dh
                except (TypeError, ValueError):
                    pass

            # Avisos abiertos globales (no solo del periodo)
            open_notices = MaintenanceNotice.query.filter(
                MaintenanceNotice.status.in_(['Pendiente', 'En Tratamiento', 'En Progreso'])
            ).count()

            # Top 5 equipos + área crítica — sólo resolver los IDs que aparecen
            equip_ids = {ot.equipment_id for ot in closed if ot.equipment_id}
            line_ids_from_ots = {ot.line_id for ot in closed if ot.line_id}
            area_ids_from_ots = {ot.area_id for ot in closed if ot.area_id}
            equip_map = ({e.id: e for e in Equipment.query.filter(Equipment.id.in_(equip_ids)).all()}
                         if equip_ids else {})
            line_ids_total = set(line_ids_from_ots) | {e.line_id for e in equip_map.values() if e.line_id}
            line_map = ({l.id: l for l in Line.query.filter(Line.id.in_(line_ids_total)).all()}
                        if line_ids_total else {})
            area_ids_total = set(area_ids_from_ots) | {l.area_id for l in line_map.values() if l.area_id}
            area_map = ({a.id: a.name for a in Area.query.filter(Area.id.in_(area_ids_total)).all()}
                        if area_ids_total else {})

            from collections import Counter
            equip_counter = Counter()
            area_downtime = Counter()
            for ot in closed:
                if not ot.caused_downtime:
                    continue
                if ot.equipment_id:
                    equip_counter[ot.equipment_id] += 1
                try:
                    dh = float(ot.downtime_hours or ot.real_duration or 0)
                except (TypeError, ValueError):
                    dh = 0
                aid = ot.area_id
                if not aid and ot.line_id and ot.line_id in line_map:
                    aid = line_map[ot.line_id].area_id
                if not aid and ot.equipment_id and ot.equipment_id in equip_map:
                    eq = equip_map[ot.equipment_id]
                    if eq.line_id and eq.line_id in line_map:
                        aid = line_map[eq.line_id].area_id
                if aid:
                    area_downtime[area_map.get(aid, f'Area {aid}')] += dh

            top_equips = []
            for eid, cnt in equip_counter.most_common(5):
                eq = equip_map.get(eid)
                if not eq:
                    continue
                ln = line_map.get(eq.line_id)
                aname = area_map.get(ln.area_id, '-') if ln else '-'
                top_equips.append({
                    'tag': eq.tag, 'name': eq.name,
                    'area': aname, 'failures': cnt,
                })

            critical_area = None
            critical_hours = 0
            if area_downtime:
                critical_area, critical_hours = area_downtime.most_common(1)[0]
                critical_hours = round(critical_hours, 2)

            # Preventivos vencidos
            overdue_lub = LubricationPoint.query.filter_by(is_active=True, semaphore_status='ROJO').count()
            overdue_insp = InspectionRoute.query.filter_by(is_active=True, semaphore_status='ROJO').count()
            overdue_mon = MonitoringPoint.query.filter_by(is_active=True, semaphore_status='ROJO').count()
            overdue_total = overdue_lub + overdue_insp + overdue_mon

            # Paradas en el periodo
            shutdowns_in_period = Shutdown.query.filter(
                Shutdown.shutdown_date >= start_iso,
                Shutdown.shutdown_date <= end_iso,
            ).all()
            unplanned = [s for s in shutdowns_in_period if (s.status or '').upper() != 'PLANIFICADA']

            metrics = {
                'period': period_label,
                'weeks_back': weeks_back,
                'ots_total': len(ots_in_window),
                'ots_closed': len(closed),
                'ots_preventive': preventive,
                'ots_corrective': corrective,
                'downtime_hours': round(total_downtime, 2),
                'open_notices': open_notices,
                'top_equipments': top_equips,
                'critical_area': critical_area,
                'critical_area_hours': critical_hours,
                'overdue_preventive': {
                    'lubrication': overdue_lub,
                    'inspection': overdue_insp,
                    'monitoring': overdue_mon,
                    'total': overdue_total,
                },
                'shutdowns_count': len(shutdowns_in_period),
                'unplanned_shutdowns': len(unplanned),
            }

            return jsonify({
                'metrics': metrics,
                'generated_at': dt.datetime.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"weekly_summary error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/insights/narrative', methods=['POST'])
    def insights_narrative():
        """Genera narrativa IA a partir de métricas ya calculadas.

        Separado del endpoint de métricas para evitar timeouts: el
        frontend primero llama a /weekly-summary (rápido) y luego
        dispara /narrative en background.
        """
        try:
            metrics = (request.get_json() or {}).get('metrics')
            if not metrics:
                return jsonify({"error": "metrics requerido"}), 400
            narrative = _generate_narrative(metrics)
            return jsonify({
                'narrative': narrative.get('text'),
                'narrative_source': narrative.get('source'),
            })
        except Exception as e:
            logger.error(f"insights_narrative error: {e}")
            return jsonify({"error": str(e)}), 500

    def _generate_narrative(m):
        """Genera la narrativa ejecutiva. Usa DeepSeek si hay API key, sino fallback."""
        if not DEEPSEEK_API_KEY:
            return {'text': _fallback_narrative(m), 'source': 'internal'}

        try:
            prompt = _build_narrative_prompt(m)
            headers = {
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json',
            }
            payload = {
                'model': 'deepseek-chat',
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            "Eres analista CMRP de planta. Escribe resumen ejecutivo "
                            "MUY BREVE (máx 5 líneas) en español, con bullets •, "
                            "terminando en 2 recomendaciones accionables."
                        ),
                    },
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.3,
                'max_tokens': 350,  # respuesta corta → menor latencia
            }
            # Timeout agresivo (15s) para no superar el gateway timeout de Render
            r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=15)
            r.raise_for_status()
            j = r.json()
            return {'text': j['choices'][0]['message']['content'].strip(), 'source': 'ai'}
        except requests.Timeout:
            logger.warning("IA narrative timeout (15s) — using fallback")
            return {'text': _fallback_narrative(m) + "\n\n(DeepSeek tardó demasiado — se usó análisis interno)", 'source': 'fallback'}
        except Exception as e:
            logger.warning(f"IA narrative fallback: {e}")
            return {'text': _fallback_narrative(m), 'source': 'fallback'}

    def _build_narrative_prompt(m):
        """Prompt compacto (menos tokens → menos latencia)."""
        top = ", ".join(f"{e['tag']}({e['failures']})" for e in m['top_equipments'][:3]) or "ninguno"
        critical = f"{m['critical_area']} con {m['critical_area_hours']}h" if m['critical_area'] else "sin área dominante"
        return (
            f"Periodo {m['period']}. "
            f"OTs cerradas {m['ots_closed']} ({m['ots_preventive']} prev / {m['ots_corrective']} corr). "
            f"Downtime {m['downtime_hours']}h. "
            f"Avisos abiertos {m['open_notices']}. "
            f"Paradas {m['shutdowns_count']} ({m['unplanned_shutdowns']} no planif). "
            f"Preventivos vencidos {m['overdue_preventive']['total']}. "
            f"Área crítica: {critical}. "
            f"Top fallas: {top}. "
            f"Redacta resumen ejecutivo breve con estado, riesgos y 2 recomendaciones."
        )

    def _fallback_narrative(m):
        parts = [
            f"📊 Resumen {m['period']}",
            f"Se cerraron {m['ots_closed']} OTs ({m['ots_preventive']} preventivas, {m['ots_corrective']} correctivas). "
            f"Downtime acumulado: {m['downtime_hours']}h.",
        ]
        if m['critical_area']:
            parts.append(
                f"⚠ Área crítica: {m['critical_area']} concentra {m['critical_area_hours']}h de parada."
            )
        if m['overdue_preventive']['total'] > 0:
            parts.append(
                f"⚠ {m['overdue_preventive']['total']} preventivos vencidos sin ejecutar."
            )
        if m['top_equipments']:
            top = m['top_equipments'][0]
            parts.append(
                f"🔧 Equipo más problemático: {top['tag']} ({top['name']}) con {top['failures']} fallas."
            )
        parts.append(
            "\nRecomendaciones: (1) Priorizar preventivos vencidos. "
            "(2) Analizar causas recurrentes en equipo top. "
            "(3) Revisar avisos abiertos antes del cierre de periodo."
        )
        return "\n\n".join(parts)
