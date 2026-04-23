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
from sqlalchemy import func


DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'


def register_insights_routes(
    app, db, logger,
    WorkOrder, MaintenanceNotice, Area, Line, Equipment,
    LubricationPoint, InspectionRoute, MonitoringPoint,
    Shutdown,
):

    @app.route('/insights', methods=['GET'])
    def insights_page():
        return render_template('insights.html')

    @app.route('/api/insights/weekly-summary', methods=['GET'])
    def weekly_summary():
        """Resumen de la semana anterior o las últimas N semanas."""
        try:
            weeks_back = int(request.args.get('weeks', 1))
            end_date = dt.date.today()
            start_date = end_date - dt.timedelta(days=7 * weeks_back)
            period_label = f"últimos {7 * weeks_back} días ({start_date.isoformat()} → {end_date.isoformat()})"

            def _in_window(date_str):
                if not date_str:
                    return False
                try:
                    d = dt.date.fromisoformat(date_str[:10])
                    return start_date <= d <= end_date
                except Exception:
                    return False

            # 1. OTs totales en la ventana
            all_ots = WorkOrder.query.all()
            ots_in_window = [
                ot for ot in all_ots
                if _in_window(ot.real_end_date or ot.scheduled_date)
            ]
            closed = [ot for ot in ots_in_window if ot.status == 'Cerrada']
            preventive = [ot for ot in closed if (ot.maintenance_type or '').lower().startswith('prev')]
            corrective = [ot for ot in closed if (ot.maintenance_type or '').lower().startswith('corr')]

            # 2. Downtime acumulado
            total_downtime = sum(
                float(ot.downtime_hours or ot.real_duration or 0)
                for ot in closed
                if ot.caused_downtime
            )

            # 3. Avisos abiertos al final del periodo
            open_notices = MaintenanceNotice.query.filter(
                MaintenanceNotice.status.in_(['Pendiente', 'En Tratamiento', 'En Progreso'])
            ).count()

            # 4. Top 5 equipos por número de fallas en la ventana
            equip_map = {e.id: e for e in Equipment.query.all()}
            area_map = {a.id: a.name for a in Area.query.all()}
            line_map = {l.id: l for l in Line.query.all()}

            from collections import Counter
            equip_counter = Counter()
            for ot in closed:
                if ot.caused_downtime and ot.equipment_id:
                    equip_counter[ot.equipment_id] += 1
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

            # 5. Área con más downtime
            area_downtime = Counter()
            for ot in closed:
                if not ot.caused_downtime:
                    continue
                dh = float(ot.downtime_hours or ot.real_duration or 0)
                aid = ot.area_id
                if not aid and ot.line_id and ot.line_id in line_map:
                    aid = line_map[ot.line_id].area_id
                if not aid and ot.equipment_id and ot.equipment_id in equip_map:
                    eq = equip_map[ot.equipment_id]
                    if eq.line_id and eq.line_id in line_map:
                        aid = line_map[eq.line_id].area_id
                if aid:
                    area_downtime[area_map.get(aid, f'Area {aid}')] += dh
            critical_area = None
            critical_hours = 0
            if area_downtime:
                critical_area, critical_hours = area_downtime.most_common(1)[0]
                critical_hours = round(critical_hours, 2)

            # 6. Cumplimiento preventivo: puntos vencidos sin ejecutar
            overdue_lub = LubricationPoint.query.filter_by(
                is_active=True, semaphore_status='ROJO'
            ).count()
            overdue_insp = InspectionRoute.query.filter_by(
                is_active=True, semaphore_status='ROJO'
            ).count()
            overdue_mon = MonitoringPoint.query.filter_by(
                is_active=True, semaphore_status='ROJO'
            ).count()
            overdue_total = overdue_lub + overdue_insp + overdue_mon

            # 7. Paradas en el periodo
            shutdowns_in_period = [
                s for s in Shutdown.query.all()
                if _in_window(s.shutdown_date)
            ]
            unplanned = [s for s in shutdowns_in_period if s.shutdown_type != 'PLANIFICADA']

            metrics = {
                'period': period_label,
                'weeks_back': weeks_back,
                'ots_total': len(ots_in_window),
                'ots_closed': len(closed),
                'ots_preventive': len(preventive),
                'ots_corrective': len(corrective),
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

            # 8. Narrativa IA
            narrative = _generate_narrative(metrics)

            return jsonify({
                'metrics': metrics,
                'narrative': narrative.get('text'),
                'narrative_source': narrative.get('source'),
                'generated_at': dt.datetime.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"weekly_summary error: {e}")
            import traceback; traceback.print_exc()
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
                            "Eres un analista senior de confiabilidad industrial (CMRP) "
                            "en una planta procesadora. Redactas resúmenes ejecutivos "
                            "BREVES (máx 8 líneas) para gerencia general. "
                            "Lenguaje directo, 2-3 recomendaciones accionables al final. "
                            "Usa bullets con •"
                        ),
                    },
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.3,
                'max_tokens': 600,
            }
            r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            j = r.json()
            return {'text': j['choices'][0]['message']['content'].strip(), 'source': 'ai'}
        except Exception as e:
            logger.warning(f"IA narrative fallback: {e}")
            return {'text': _fallback_narrative(m), 'source': 'fallback'}

    def _build_narrative_prompt(m):
        lines = [
            f"Periodo: {m['period']}",
            "",
            f"- OTs totales: {m['ots_total']} | Cerradas: {m['ots_closed']}",
            f"- Preventivas cerradas: {m['ots_preventive']} | Correctivas: {m['ots_corrective']}",
            f"- Horas de parada por fallas: {m['downtime_hours']}",
            f"- Avisos abiertos al cierre: {m['open_notices']}",
            f"- Paradas de planta: {m['shutdowns_count']} (de las cuales {m['unplanned_shutdowns']} no planificadas)",
            f"- Preventivos vencidos: Lub {m['overdue_preventive']['lubrication']}, "
            f"Insp {m['overdue_preventive']['inspection']}, "
            f"Mon {m['overdue_preventive']['monitoring']} (total {m['overdue_preventive']['total']})",
        ]
        if m['critical_area']:
            lines.append(f"- Área con más downtime: {m['critical_area']} ({m['critical_area_hours']}h)")
        if m['top_equipments']:
            lines.append("")
            lines.append("Top 5 equipos con más fallas:")
            for e in m['top_equipments']:
                lines.append(f"  • {e['tag']} ({e['name']}) — área {e['area']}: {e['failures']} fallas")
        lines.append("")
        lines.append(
            "Redacta un resumen ejecutivo con: estado general, alertas de riesgo, "
            "equipos críticos, y 2-3 recomendaciones priorizadas."
        )
        return "\n".join(lines)

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
