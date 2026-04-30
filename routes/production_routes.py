"""Módulo de Confiabilidad de Producción e Impacto en Toneladas.

Calcula, a partir de las OTs cerradas con paro de planta y de la meta/rendimiento
mensual que entrega producción:
  - Toneladas y sacos perdidos por downtime
  - Disponibilidad requerida para cumplir la meta
  - Factor de Seguridad dinámico (variabilidad del MTTR)
  - Pareto de equipos con mayor impacto
  - Diagnóstico ejecutivo IA (DeepSeek) cuando la meta está en riesgo
"""
import os
import datetime as dt
import math
import statistics
from io import BytesIO

import requests
from flask import jsonify, request, render_template, send_file


SACK_KG = 50  # 1 saco de harina procesada = 50 kg
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'


def register_production_routes(app, db, logger, ProductionGoal, WorkOrder, Area, Line, Equipment):

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _parse_date(raw):
        if not raw:
            return None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return dt.datetime.strptime(str(raw), fmt).date()
            except Exception:
                pass
        return None

    def _period_to_dates(period):
        """'YYYY-MM' → (start_date, end_date, days_in_month)."""
        try:
            year, month = period.split('-')
            year, month = int(year), int(month)
            start = dt.date(year, month, 1)
            if month == 12:
                end = dt.date(year, 12, 31)
            else:
                end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
            return start, end, (end - start).days + 1
        except Exception:
            today = dt.date.today()
            start = today.replace(day=1)
            return start, today, (today - start).days + 1

    def _current_period():
        return dt.date.today().strftime('%Y-%m')

    def _ot_in_window(ot, start, end):
        d = ot.scheduled_date or ot.real_end_date or ot.real_start_date
        if not d:
            return False
        try:
            od = dt.date.fromisoformat(d[:10])
            return start <= od <= end
        except Exception:
            return False

    def _resolve_area_id(ot, line_map, equip_map):
        if ot.area_id:
            return ot.area_id
        if ot.line_id and ot.line_id in line_map:
            return line_map[ot.line_id].area_id
        if ot.equipment_id and ot.equipment_id in equip_map:
            eq = equip_map[ot.equipment_id]
            if eq.line_id and eq.line_id in line_map:
                return line_map[eq.line_id].area_id
        return None

    def _downtime_hours(ot):
        """Calcula downtime efectivo del OT."""
        if ot.caused_downtime and ot.downtime_hours:
            return float(ot.downtime_hours)
        if ot.caused_downtime and ot.real_duration:
            return float(ot.real_duration)
        return 0.0

    def _safety_factor(mttr_list):
        """Factor de seguridad dinámico basado en variabilidad del MTTR.

        FS = 1 + (σ_MTTR / μ_MTTR). A mayor variabilidad del MTTR, más buffer
        necesario sobre la disponibilidad requerida teórica.
        """
        if not mttr_list or len(mttr_list) < 2:
            return 1.0
        try:
            mu = statistics.mean(mttr_list)
            if mu <= 0:
                return 1.0
            sigma = statistics.stdev(mttr_list)
            return round(1.0 + (sigma / mu), 3)
        except Exception:
            return 1.0

    def _metrics_for_period(period, area_filter=None):
        """Calcula todas las métricas del módulo para un periodo dado.

        Returns dict con:
          period, areas[], totals{}, top_equipments[], gap_pp, at_risk
        """
        start, end, days_in_period = _period_to_dates(period)

        goals = ProductionGoal.query.filter_by(goal_period=period).all()
        if area_filter:
            goals = [g for g in goals if g.area_id == area_filter]

        areas_all = Area.query.all()
        lines = Line.query.all()
        equips = Equipment.query.all()
        line_map = {l.id: l for l in lines}
        equip_map = {e.id: e for e in equips}
        area_map = {a.id: a for a in areas_all}

        all_ots = WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all()

        area_results = []
        total_tons_lost = 0.0
        total_sacks_lost = 0.0
        total_target = 0.0
        total_yield = 0.0
        weighted_avail_num = 0.0
        weighted_avail_den = 0.0
        weighted_req_num = 0.0
        equipment_impact = {}  # equip_id → tons_lost

        for goal in goals:
            area = area_map.get(goal.area_id)
            if not area:
                continue
            # Excluir areas marcadas include_in_kpi=False (ej: BAJA, UTILITIES,
            # RMP). Aunque tengan Goal historico, no entran en el calculo.
            if not getattr(area, 'include_in_kpi', True):
                continue

            operating_hours = goal.operating_hours_month or 720.0
            tons_per_hour = (goal.monthly_avg_yield_tons / operating_hours) if operating_hours > 0 else 0

            # OTs del área en el periodo
            area_ots = []
            for ot in all_ots:
                if not _ot_in_window(ot, start, end):
                    continue
                aid = _resolve_area_id(ot, line_map, equip_map)
                if aid == area.id:
                    area_ots.append(ot)

            # Downtime total + MTTR individuales
            downtime_events = []
            for ot in area_ots:
                dh = _downtime_hours(ot)
                if dh > 0:
                    downtime_events.append({'ot': ot, 'hours': dh})

            total_downtime = sum(e['hours'] for e in downtime_events)
            mttr_list = [e['hours'] for e in downtime_events]

            # Período analizado ya transcurrido (hasta hoy si el mes está en curso)
            today = dt.date.today()
            effective_end = min(end, today)
            hours_in_period = max(1, (effective_end - start).days + 1) * 24
            # Cap hours a operating_hours si estamos dentro del mes
            analyzed_hours = min(hours_in_period, operating_hours)

            uptime = max(0, analyzed_hours - total_downtime)
            availability = round((uptime / analyzed_hours) * 100, 2) if analyzed_hours > 0 else 100.0

            # Toneladas perdidas
            tons_lost = round(total_downtime * tons_per_hour, 2)
            sacks_lost = round((tons_lost * 1000) / SACK_KG, 0)

            # Disponibilidad requerida
            if tons_per_hour > 0:
                required_uptime = goal.monthly_target_tons / tons_per_hour
                required_availability = round((required_uptime / operating_hours) * 100, 2)
            else:
                required_availability = 0.0

            # Factor de Seguridad dinámico
            safety_factor = _safety_factor(mttr_list)
            required_with_sf = round(min(99.9, required_availability * safety_factor), 2)

            # Brecha
            gap_pp = round(availability - required_with_sf, 2)
            at_risk = gap_pp < 0

            # Producción teórica actual (si se mantuviera el ritmo)
            tons_produced_theoretical = round(tons_per_hour * uptime, 2)

            # Proyección fin de mes (ritmo actual extrapolado)
            if start <= today <= end:
                days_elapsed = (today - start).days + 1
                projected_tons = round((tons_produced_theoretical / max(1, days_elapsed)) * days_in_period, 2)
            else:
                projected_tons = tons_produced_theoretical

            compliance_pct = round((projected_tons / goal.monthly_target_tons) * 100, 2) if goal.monthly_target_tons > 0 else 0

            # Impacto por equipo dentro del área
            for ev in downtime_events:
                ot = ev['ot']
                eq_id = ot.equipment_id
                if not eq_id:
                    continue
                eq = equip_map.get(eq_id)
                # Excluir equipos marcados como fuera de KPI (ej: hidrolavadora 4)
                if eq and not getattr(eq, 'include_in_kpi', True):
                    continue
                tons = ev['hours'] * tons_per_hour
                if eq_id not in equipment_impact:
                    equipment_impact[eq_id] = {
                        'equipment_id': eq_id,
                        'equipment_name': eq.name if eq else '-',
                        'equipment_tag': eq.tag if eq else '-',
                        'area_name': area.name,
                        'tons_lost': 0,
                        'sacks_lost': 0,
                        'downtime_hours': 0,
                        'failure_count': 0,
                    }
                equipment_impact[eq_id]['tons_lost'] += tons
                equipment_impact[eq_id]['downtime_hours'] += ev['hours']
                equipment_impact[eq_id]['failure_count'] += 1

            area_results.append({
                'area_id': area.id,
                'area_name': area.name,
                'goal_id': goal.id,
                'monthly_avg_yield_tons': goal.monthly_avg_yield_tons,
                'monthly_target_tons': goal.monthly_target_tons,
                'operating_hours_month': operating_hours,
                'tons_per_hour': round(tons_per_hour, 3),
                'availability_actual': availability,
                'required_availability': required_availability,
                'safety_factor': safety_factor,
                'required_with_sf': required_with_sf,
                'gap_pp': gap_pp,
                'at_risk': at_risk,
                'total_downtime_hours': round(total_downtime, 2),
                'failure_count': len(downtime_events),
                'tons_lost': tons_lost,
                'sacks_lost': int(sacks_lost),
                'tons_produced_theoretical': tons_produced_theoretical,
                'projected_tons_month': projected_tons,
                'compliance_pct': compliance_pct,
            })

            # Totales acumulados
            total_tons_lost += tons_lost
            total_sacks_lost += sacks_lost
            total_target += goal.monthly_target_tons
            total_yield += goal.monthly_avg_yield_tons
            # Disponibilidad ponderada por capacidad (yield) de cada área
            weighted_avail_num += availability * goal.monthly_avg_yield_tons
            weighted_avail_den += goal.monthly_avg_yield_tons
            weighted_req_num += required_with_sf * goal.monthly_avg_yield_tons

        # Top 5 equipos por impacto en TM
        top_equips = sorted(
            equipment_impact.values(),
            key=lambda x: x['tons_lost'],
            reverse=True
        )[:5]
        for e in top_equips:
            e['tons_lost'] = round(e['tons_lost'], 2)
            e['sacks_lost'] = int((e['tons_lost'] * 1000) / SACK_KG)
            e['downtime_hours'] = round(e['downtime_hours'], 2)

        # Totales
        avg_availability = round(weighted_avail_num / weighted_avail_den, 2) if weighted_avail_den > 0 else 0
        avg_required = round(weighted_req_num / weighted_avail_den, 2) if weighted_avail_den > 0 else 0
        global_gap = round(avg_availability - avg_required, 2)

        totals = {
            'total_target_tons': round(total_target, 2),
            'total_yield_tons': round(total_yield, 2),
            'total_tons_lost': round(total_tons_lost, 2),
            'total_sacks_lost': int(total_sacks_lost),
            'avg_availability': avg_availability,
            'avg_required_availability': avg_required,
            'global_gap_pp': global_gap,
            'global_at_risk': global_gap < 0,
            'areas_count': len(area_results),
        }

        return {
            'period': period,
            'period_start': start.isoformat(),
            'period_end': end.isoformat(),
            'days_in_period': days_in_period,
            'areas': area_results,
            'top_equipments': top_equips,
            'totals': totals,
        }

    # ── Page route ───────────────────────────────────────────────────────────

    @app.route('/produccion', methods=['GET'])
    def produccion_page():
        return render_template('produccion.html')

    # ── CRUD de metas de producción ──────────────────────────────────────────

    @app.route('/api/production/goals', methods=['GET'])
    def list_production_goals():
        try:
            period = request.args.get('period')
            q = ProductionGoal.query
            if period:
                q = q.filter_by(goal_period=period)
            goals = q.order_by(ProductionGoal.goal_period.desc(), ProductionGoal.area_id).all()
            return jsonify([g.to_dict() for g in goals])
        except Exception as e:
            logger.error(f"list_production_goals error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/production/goals', methods=['POST'])
    def create_production_goal():
        try:
            data = request.get_json() or {}
            period = (data.get('goal_period') or '').strip()
            area_id = data.get('area_id')
            yield_tons = float(data.get('monthly_avg_yield_tons') or 0)
            target_tons = float(data.get('monthly_target_tons') or 0)

            if not period or not area_id or yield_tons <= 0 or target_tons <= 0:
                return jsonify({"error": "Datos incompletos o inválidos."}), 400

            # Upsert: si ya existe para ese periodo+área, actualizar
            existing = ProductionGoal.query.filter_by(
                goal_period=period, area_id=int(area_id)
            ).first()

            if existing:
                existing.monthly_avg_yield_tons = yield_tons
                existing.monthly_target_tons = target_tons
                existing.operating_hours_month = float(data.get('operating_hours_month') or 720)
                existing.notes = data.get('notes')
                existing.updated_at = dt.datetime.utcnow()
                db.session.commit()
                return jsonify(existing.to_dict())

            goal = ProductionGoal(
                goal_period=period,
                area_id=int(area_id),
                monthly_avg_yield_tons=yield_tons,
                monthly_target_tons=target_tons,
                operating_hours_month=float(data.get('operating_hours_month') or 720),
                notes=data.get('notes'),
                created_by=data.get('created_by'),
            )
            db.session.add(goal)
            db.session.commit()
            return jsonify(goal.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"create_production_goal error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/production/goals/<int:goal_id>', methods=['PUT'])
    def update_production_goal(goal_id):
        try:
            goal = ProductionGoal.query.get_or_404(goal_id)
            data = request.get_json() or {}
            for field in ('goal_period', 'notes'):
                if field in data:
                    setattr(goal, field, data[field])
            if 'area_id' in data and data['area_id']:
                goal.area_id = int(data['area_id'])
            if 'monthly_avg_yield_tons' in data:
                goal.monthly_avg_yield_tons = float(data['monthly_avg_yield_tons'])
            if 'monthly_target_tons' in data:
                goal.monthly_target_tons = float(data['monthly_target_tons'])
            if 'operating_hours_month' in data:
                goal.operating_hours_month = float(data['operating_hours_month'])
            goal.updated_at = dt.datetime.utcnow()
            db.session.commit()
            return jsonify(goal.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.error(f"update_production_goal error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/production/goals/<int:goal_id>', methods=['DELETE'])
    def delete_production_goal(goal_id):
        try:
            goal = ProductionGoal.query.get_or_404(goal_id)
            db.session.delete(goal)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.error(f"delete_production_goal error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Métricas principales del módulo ──────────────────────────────────────

    @app.route('/api/production/metrics', methods=['GET'])
    def get_production_metrics():
        """Métricas del módulo para el periodo solicitado (default: mes actual)."""
        try:
            period = request.args.get('period') or _current_period()
            area_filter = request.args.get('area_id')
            area_filter = int(area_filter) if area_filter else None
            data = _metrics_for_period(period, area_filter=area_filter)
            return jsonify(data)
        except Exception as e:
            logger.error(f"get_production_metrics error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/production/trend', methods=['GET'])
    def get_production_trend():
        """Serie histórica de los últimos N meses (default 6)."""
        try:
            months = int(request.args.get('months') or 6)
            today = dt.date.today()
            series = []
            for i in range(months - 1, -1, -1):
                y = today.year
                m = today.month - i
                while m <= 0:
                    m += 12
                    y -= 1
                period = f"{y:04d}-{m:02d}"
                data = _metrics_for_period(period)
                t = data['totals']
                series.append({
                    'period': period,
                    'availability': t['avg_availability'],
                    'required': t['avg_required_availability'],
                    'tons_lost': t['total_tons_lost'],
                    'sacks_lost': t['total_sacks_lost'],
                    'target': t['total_target_tons'],
                    'yield': t['total_yield_tons'],
                    'gap': t['global_gap_pp'],
                })
            return jsonify({'months': months, 'series': series})
        except Exception as e:
            logger.error(f"get_production_trend error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Diagnóstico IA (DeepSeek) ────────────────────────────────────────────

    @app.route('/api/production/ai-diagnosis', methods=['POST'])
    def production_ai_diagnosis():
        """Genera diagnóstico ejecutivo con DeepSeek sobre el estado actual."""
        try:
            data = request.get_json() or {}
            period = data.get('period') or _current_period()
            metrics = _metrics_for_period(period)

            if not DEEPSEEK_API_KEY:
                return jsonify({
                    "diagnosis": _fallback_diagnosis(metrics),
                    "source": "internal",
                })

            prompt = _build_ai_prompt(metrics)

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
                            "Eres un experto en confiabilidad industrial (CMRP) y análisis "
                            "de producción. Redactas diagnósticos ejecutivos BREVES (máx 6 "
                            "líneas) para gerencia general de una planta procesadora de "
                            "harina. Usas lenguaje directo, datos concretos y accionables. "
                            "Siempre terminas con 2-3 recomendaciones priorizadas."
                        ),
                    },
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.3,
                'max_tokens': 500,
            }

            r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            j = r.json()
            answer = j['choices'][0]['message']['content'].strip()

            return jsonify({
                "diagnosis": answer,
                "source": "ai",
                "metrics_snapshot": metrics['totals'],
            })
        except Exception as e:
            logger.error(f"production_ai_diagnosis error: {e}")
            try:
                return jsonify({
                    "diagnosis": _fallback_diagnosis(metrics),
                    "source": "fallback",
                    "error": str(e),
                })
            except Exception:
                return jsonify({"error": str(e)}), 500

    def _build_ai_prompt(m):
        t = m['totals']
        lines = [
            f"Periodo analizado: {m['period']} ({m['period_start']} a {m['period_end']})",
            f"",
            f"INDICADORES GLOBALES:",
            f"- Disponibilidad actual ponderada: {t['avg_availability']}%",
            f"- Disponibilidad requerida (con FS): {t['avg_required_availability']}%",
            f"- Brecha: {t['global_gap_pp']} puntos porcentuales ({'EN RIESGO' if t['global_at_risk'] else 'OK'})",
            f"- Meta total de producción: {t['total_target_tons']} TM",
            f"- Rendimiento promedio esperado: {t['total_yield_tons']} TM",
            f"- Toneladas perdidas por paros: {t['total_tons_lost']} TM",
            f"- Sacos perdidos (50 kg c/u): {t['total_sacks_lost']} sacos",
            f"",
            f"DETALLE POR ÁREA:",
        ]
        for a in m['areas']:
            lines.append(
                f"- {a['area_name']}: Disp {a['availability_actual']}% vs Req {a['required_with_sf']}% "
                f"(FS={a['safety_factor']}), perdió {a['tons_lost']} TM / {a['sacks_lost']} sacos. "
                f"Proyección mes: {a['compliance_pct']}% de meta."
            )
        if m['top_equipments']:
            lines.append("")
            lines.append("TOP EQUIPOS DE MAYOR IMPACTO:")
            for e in m['top_equipments']:
                lines.append(
                    f"- {e['equipment_tag']} ({e['equipment_name']}, área {e['area_name']}): "
                    f"{e['failure_count']} fallas, {e['downtime_hours']}h paro, "
                    f"{e['tons_lost']} TM / {e['sacks_lost']} sacos perdidos."
                )
        lines.append("")
        lines.append(
            "Redacta un diagnóstico ejecutivo para gerencia general: estado actual, "
            "áreas críticas, equipos que requieren intervención y 2-3 recomendaciones "
            "priorizadas para no incumplir la meta mensual."
        )
        return "\n".join(lines)

    def _fallback_diagnosis(m):
        t = m['totals']
        if t['areas_count'] == 0:
            return (
                "Sin metas de producción cargadas para este periodo. "
                "Registra la meta y rendimiento mensual desde el botón 'Capturar meta' "
                "para activar el análisis automático."
            )
        status = "EN RIESGO" if t['global_at_risk'] else "OK"
        lines = [
            f"📊 Estado: {status}. Disponibilidad actual {t['avg_availability']}% "
            f"vs requerida {t['avg_required_availability']}% (brecha {t['global_gap_pp']}pp).",
            f"📉 Impacto acumulado: {t['total_tons_lost']} TM / {t['total_sacks_lost']} sacos perdidos.",
        ]
        if m['top_equipments']:
            e = m['top_equipments'][0]
            lines.append(
                f"🔧 Principal impactador: {e['equipment_tag']} ({e['area_name']}) "
                f"con {e['failure_count']} fallas y {e['tons_lost']} TM perdidas."
            )
        if t['global_at_risk']:
            lines.append(
                "⚠️ Recomendaciones: (1) Priorizar OTs pendientes de los equipos top. "
                "(2) Revisar modos de falla recurrentes. (3) Evaluar ajuste de meta "
                "si la brecha supera 5pp de forma sostenida."
            )
        return "\n".join(lines)

    # ── Export a Excel ───────────────────────────────────────────────────────

    @app.route('/api/production/export', methods=['GET'])
    def export_production_report():
        try:
            import pandas as pd
            period = request.args.get('period') or _current_period()
            m = _metrics_for_period(period)

            bio = BytesIO()
            with pd.ExcelWriter(bio, engine='openpyxl') as writer:
                # Resumen
                totals = m['totals']
                pd.DataFrame([{
                    'Periodo': m['period'],
                    'Disp. Actual %': totals['avg_availability'],
                    'Disp. Requerida %': totals['avg_required_availability'],
                    'Brecha pp': totals['global_gap_pp'],
                    'Meta TM': totals['total_target_tons'],
                    'Rendimiento TM': totals['total_yield_tons'],
                    'TM Perdidas': totals['total_tons_lost'],
                    'Sacos Perdidos': totals['total_sacks_lost'],
                    'Estado': 'EN RIESGO' if totals['global_at_risk'] else 'OK',
                }]).to_excel(writer, sheet_name='Resumen', index=False)

                # Por área
                pd.DataFrame(m['areas']).to_excel(writer, sheet_name='Por Área', index=False)

                # Top equipos
                if m['top_equipments']:
                    pd.DataFrame(m['top_equipments']).to_excel(
                        writer, sheet_name='Top Equipos', index=False
                    )

            bio.seek(0)
            filename = f"produccion_{period}.xlsx"
            return send_file(
                bio,
                as_attachment=True,
                download_name=filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            logger.error(f"export_production_report error: {e}")
            return jsonify({"error": str(e)}), 500

    # ════════════════════════════════════════════════════════════════════════
    # PRODUCCION POR EQUIPO (vista detallada — Opcion C)
    # ════════════════════════════════════════════════════════════════════════
    # Calcula produccion teorica por equipo considerando jornada operativa
    # (shift_hours_per_day, work_days_per_week) y paradas planificadas
    # (Shutdowns con status COMPLETADA en el periodo).
    # Comparado con el endpoint global /api/production/metrics, este desglosa
    # cada equipo individualmente sin requerir una Goal por area.

    def _calendar_hours_for_equipment(eq, start, end):
        """Calcula horas operativas teoricas considerando jornada y dias laborables."""
        shift_h = float(getattr(eq, 'shift_hours_per_day', None) or 24.0)
        work_days = int(getattr(eq, 'work_days_per_week', None) or 7)
        # Cuenta dias del periodo respetando dias laborables. Lunes=0..Domingo=6.
        # Si work_days < 7, asumimos que descansa empezando por domingo (6) y
        # va restando: 6 dias=quita domingo, 5 dias=quita sab+dom, etc.
        rest_days = set()
        if work_days < 7:
            order = [6, 5, 0, 1, 2, 3, 4]  # dom, sab, lun, mar... (orden tipico de descanso)
            for i in range(7 - work_days):
                rest_days.add(order[i])
        days_count = 0
        d = start
        while d <= end:
            if d.weekday() not in rest_days:
                days_count += 1
            d += dt.timedelta(days=1)
        return days_count * shift_h

    def _planned_downtime_for_equipment(eq, start, end, area_id):
        """Suma horas de paradas planificadas (Shutdowns COMPLETADAS en
        rango y que afectan al area del equipo).
        Para parada TOTAL: cuenta todas. Para PARCIAL: cuenta solo si el
        area del equipo esta en ShutdownArea.
        """
        try:
            from models import Shutdown, ShutdownArea
            sh_q = Shutdown.query.filter(
                Shutdown.shutdown_date >= start.isoformat(),
                Shutdown.shutdown_date <= end.isoformat(),
                Shutdown.status.in_(['COMPLETADA', 'EN_CURSO', 'PLANIFICADA']),
            )
            total_h = 0.0
            for sh in sh_q.all():
                # Validar area si es PARCIAL
                if (sh.shutdown_type or '').upper() == 'PARCIAL':
                    sh_areas = [sa.area_id for sa in (sh.areas or [])]
                    if area_id not in sh_areas:
                        continue
                # Calcular horas de la parada
                try:
                    sh, eh = sh.start_time or '00:00', sh.end_time or '00:00'
                    sh_h, sh_m = [int(x) for x in (sh or '00:00').split(':')]
                    eh_h, eh_m = [int(x) for x in (eh or '00:00').split(':')]
                    hours = max(0, (eh_h * 60 + eh_m - sh_h * 60 - sh_m) / 60.0)
                    total_h += hours
                except Exception:
                    total_h += 12.0  # default si formato raro
            return total_h
        except Exception:
            return 0.0

    def _compute_eq_production(eq, start, end, area, all_ots, line_map):
        """Devuelve dict con metricas de un equipo."""
        cap_tm = float(getattr(eq, 'capacity_tm', None) or 0)
        # Si no hay capacidad seteada en BD, fallback al dict legacy
        if cap_tm == 0:
            try:
                from routes.indicators_routes import EQUIPMENT_CAPACITY
                cap_tm = float(EQUIPMENT_CAPACITY.get(eq.tag or '', 0) or 0)
            except Exception:
                cap_tm = 0.0

        cal_hours = _calendar_hours_for_equipment(eq, start, end)
        planned_dt = _planned_downtime_for_equipment(eq, start, end, area.id if area else None)
        usable_hours = max(0.0, cal_hours - planned_dt)

        # Downtime real (OTs cerradas con caused_downtime en el periodo del equipo)
        eq_dt = 0.0
        eq_dt_events = 0
        for ot in all_ots:
            if ot.equipment_id != eq.id:
                continue
            if not _ot_in_window(ot, start, end):
                continue
            dh = _downtime_hours(ot)
            if dh > 0:
                eq_dt += dh
                eq_dt_events += 1
        eq_dt = min(eq_dt, usable_hours)
        uptime_real = max(0.0, usable_hours - eq_dt)

        # Disponibilidad respecto a las horas USABLES (calendario - planificadas)
        availability = round((uptime_real / usable_hours) * 100, 2) if usable_hours > 0 else 100.0

        # TM de materia prima procesada (input). cap_tm es capacidad de proceso a 24/7.
        # Para producto final se aplica yield_factor (ej: digestor 12000 cap pero
        # rendimiento 30% → 3600 TM/mes de harina). Asi tenemos 2 metricas:
        #   - input_tons_*  : materia prima
        #   - output_tons_* : producto final (lo que realmente sale)
        yield_factor = float(getattr(eq, 'yield_factor', None) or 1.0)
        input_tph = (cap_tm / 720.0) if cap_tm > 0 else 0.0
        output_tph = input_tph * yield_factor

        input_tons_theoretical = round(usable_hours * input_tph, 2)
        input_tons_realized = round(uptime_real * input_tph, 2)
        input_tons_lost = round(eq_dt * input_tph, 2)

        output_tons_theoretical = round(usable_hours * output_tph, 2)
        output_tons_realized = round(uptime_real * output_tph, 2)
        output_tons_lost = round(eq_dt * output_tph, 2)

        eff_pct = round((uptime_real / usable_hours) * 100, 2) if usable_hours > 0 else 0.0

        ln = line_map.get(eq.line_id) if eq.line_id else None
        return {
            'equipment_id': eq.id,
            'equipment_tag': eq.tag,
            'equipment_name': eq.name,
            'line_id': eq.line_id,
            'line_name': ln.name if ln else None,
            'area_id': area.id if area else None,
            'area_name': area.name if area else None,
            'capacity_tm': cap_tm,
            'yield_factor': yield_factor,
            'shift_hours_per_day': float(getattr(eq, 'shift_hours_per_day', None) or 24.0),
            'work_days_per_week': int(getattr(eq, 'work_days_per_week', None) or 7),
            'calendar_hours': round(cal_hours, 2),
            'planned_downtime_hours': round(planned_dt, 2),
            'usable_hours': round(usable_hours, 2),
            'downtime_hours': round(eq_dt, 2),
            'uptime_hours': round(uptime_real, 2),
            'availability_pct': availability,
            # Metricas de INPUT (materia prima)
            'input_tons_per_hour': round(input_tph, 4),
            'input_tons_theoretical': input_tons_theoretical,
            'input_tons_realized': input_tons_realized,
            'input_tons_lost': input_tons_lost,
            # Metricas de OUTPUT (producto final)
            'output_tons_per_hour': round(output_tph, 4),
            'output_tons_theoretical': output_tons_theoretical,
            'output_tons_realized': output_tons_realized,
            'output_tons_lost': output_tons_lost,
            # Backward-compat (TM = output, lo que sale a la venta)
            'tons_per_hour': round(output_tph, 4),
            'tons_theoretical': output_tons_theoretical,
            'tons_realized_potential': output_tons_realized,
            'tons_lost': output_tons_lost,
            'efficiency_pct': eff_pct,
            'failure_count': eq_dt_events,
        }

    @app.route('/api/production/by-equipment', methods=['GET'])
    def production_by_equipment():
        """Detalle por equipo: TM teoricas vs perdidas + roll-up por area."""
        try:
            period = request.args.get('period') or _current_period()
            start, end, days_in_period = _period_to_dates(period)
            today = dt.date.today()
            effective_end = min(end, today)

            # Solo equipos y areas in_kpi
            areas = Area.query.filter_by(include_in_kpi=True).all()
            area_map = {a.id: a for a in areas}
            lines = Line.query.all()
            line_map = {l.id: l for l in lines}
            line_to_area = {l.id: l.area_id for l in lines}
            equips = Equipment.query.filter_by(include_in_kpi=True).all()
            equips = [e for e in equips if line_to_area.get(e.line_id) in area_map]

            all_ots = WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all()

            equipos = []
            for eq in equips:
                area = area_map.get(line_to_area.get(eq.line_id))
                metrics = _compute_eq_production(eq, start, effective_end, area, all_ots, line_map)
                equipos.append(metrics)

            # Roll-up por area (con input vs output)
            by_area = {}
            sum_keys = (
                'capacity_tm', 'usable_hours', 'downtime_hours',
                'input_tons_theoretical', 'input_tons_realized', 'input_tons_lost',
                'output_tons_theoretical', 'output_tons_realized', 'output_tons_lost',
                'tons_theoretical', 'tons_realized_potential', 'tons_lost',
            )
            for m in equipos:
                aid = m['area_id']
                if aid not in by_area:
                    acc = {'area_id': aid, 'area_name': m['area_name'],
                           'failure_count': 0, 'equipment_count': 0}
                    for k in sum_keys: acc[k] = 0.0
                    by_area[aid] = acc
                acc = by_area[aid]
                for k in sum_keys:
                    acc[k] += m.get(k, 0) or 0
                acc['failure_count'] += m['failure_count']
                acc['equipment_count'] += 1
            for acc in by_area.values():
                acc['efficiency_pct'] = round(
                    (acc['output_tons_realized'] / acc['output_tons_theoretical']) * 100, 2
                ) if acc['output_tons_theoretical'] > 0 else 100.0
                acc['availability_pct'] = round(
                    ((acc['usable_hours'] - acc['downtime_hours']) / acc['usable_hours']) * 100, 2
                ) if acc['usable_hours'] > 0 else 100.0
                for k in sum_keys: acc[k] = round(acc[k], 2)

            # Total general
            total = {'failure_count': sum(a['failure_count'] for a in by_area.values())}
            for k in sum_keys:
                total[k] = round(sum(a[k] for a in by_area.values()), 2)
            total['efficiency_pct'] = round(
                (total['output_tons_realized'] / total['output_tons_theoretical']) * 100, 2
            ) if total['output_tons_theoretical'] > 0 else 100.0

            equipos.sort(key=lambda x: (x['area_name'] or '', -(x['tons_lost'] or 0)))
            return jsonify({
                'period': period,
                'period_start': start.isoformat(),
                'period_end': end.isoformat(),
                'effective_end': effective_end.isoformat(),
                'days_in_period': days_in_period,
                'equipos': equipos,
                'by_area': sorted(by_area.values(), key=lambda x: x['area_name'] or ''),
                'total': total,
            })
        except Exception as e:
            logger.exception('production_by_equipment error')
            return jsonify({"error": str(e)}), 500
