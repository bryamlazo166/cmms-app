from collections import defaultdict
import datetime as dt

from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file


def register_reports_routes(
    app,
    db,
    logger,
    Area,
    Line,
    Equipment,
    System,
    Component,
    WarehouseItem,
    WorkOrder,
    MaintenanceNotice,
    OTPersonnel,
    OTMaterial,
    Technician,
    Provider,
    LubricationPoint,
    LubricationExecution,
    MonitoringPoint,
    MonitoringReading,
    InspectionRoute,
    InspectionItem,
    InspectionExecution,
    InspectionResult,
    Activity,
    Milestone,
    _parse_date_flexible,
    _is_in_window,
    _normalize_maintenance_type,
    _safe_duration_hours,
):
    @app.route('/api/reports/kpis', methods=['GET'])
    def get_kpi_reports():
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            area_id = request.args.get('area_id')
            line_id = request.args.get('line_id')
            
            # Determine Level and Groups
            level = "area"
            groups = [] # {id, name, children_ids}
            
            if line_id:
                level = "equipment"
                parent = Line.query.get(line_id)
                if not parent: return jsonify({"error": "Line not found"}), 404
                
                equips = Equipment.query.filter_by(line_id=line_id).all()
                for e in equips:
                    groups.append({"id": e.id, "name": e.name, "object": e})
                    
            elif area_id:
                level = "line"
                parent = Area.query.get(area_id)
                if not parent: return jsonify({"error": "Area not found"}), 404
                
                lines = Line.query.filter_by(area_id=area_id).all()
                for l in lines:
                    groups.append({"id": l.id, "name": l.name, "object": l})
                    
            else:
                level = "area"
                areas = Area.query.all()
                for a in areas:
                    groups.append({"id": a.id, "name": a.name, "object": a})

            # Calculate KPIs for each group
            results = []

            # Pre-load once — shared across all group iterations
            _all_closed_ots = WorkOrder.query.filter_by(status='Cerrada').all()
            _systems_map    = {s.id: s for s in System.query.all()}
            _components_map = {c.id: c for c in Component.query.all()}

            # Pre-build OT equipment_id for fast lookup
            def _resolve_ot_equip_id(ot):
                if ot.equipment_id:
                    return ot.equipment_id
                if ot.system_id:
                    s = _systems_map.get(ot.system_id)
                    if s:
                        return s.equipment_id
                if ot.component_id:
                    c = _components_map.get(ot.component_id)
                    if c:
                        s = _systems_map.get(c.system_id)
                        if s:
                            return s.equipment_id
                return None

            _ot_equip_cache = {ot.id: _resolve_ot_equip_id(ot) for ot in _all_closed_ots}

            # Helper to get all OTs for a hierarchy node
            def get_ots_for_node(node, level):
                equip_ids = set()

                if level == 'equipment':
                    equip_ids = {node.id}
                elif level == 'line':
                    equip_ids = {e.id for e in Equipment.query.filter_by(line_id=node.id).all()}
                elif level == 'area':
                    lines = Line.query.filter_by(area_id=node.id).all()
                    for l in lines:
                        for e in Equipment.query.filter_by(line_id=l.id).all():
                            equip_ids.add(e.id)

                if not equip_ids:
                    return []

                relevant_ots = []
                for ot in _all_closed_ots:
                    if start_date and ot.real_end_date and ot.real_end_date < start_date:
                        continue
                    if end_date and ot.real_end_date and ot.real_end_date > end_date:
                        continue
                    if _ot_equip_cache.get(ot.id) in equip_ids:
                        relevant_ots.append(ot)

                return relevant_ots

            # Pre-load warehouse unit costs for fast lookup
            _wh_cost_map = {w.id: float(w.unit_cost or 0) for w in WarehouseItem.query.with_entities(
                WarehouseItem.id, WarehouseItem.unit_cost).all()}

            for g in groups:
                ots = get_ots_for_node(g['object'], level)

                # 1. Cost Calculation — batch load materials for all OTs in this group
                total_cost = 0
                if ots:
                    _ot_ids = [ot.id for ot in ots]
                    _mats = OTMaterial.query.filter(
                        OTMaterial.work_order_id.in_(_ot_ids),
                        OTMaterial.item_type == 'warehouse'
                    ).all()
                    for m in _mats:
                        total_cost += _wh_cost_map.get(m.item_id, 0) * (m.quantity or 0)
                
                # 2. Reliability Calculation
                failures = [ot for ot in ots if ot.maintenance_type == 'Correctivo']
                n_failures = len(failures)
                t_down = sum([(ot.real_duration or 0) for ot in failures])
                
                # Total Time window (hours)
                # Approximate if dates not set: 30 days
                t_total = 720 
                if start_date and end_date:
                    try:
                        d1 = dt.datetime.fromisoformat(start_date)
                        d2 = dt.datetime.fromisoformat(end_date)
                        t_total = (d2 - d1).total_seconds() / 3600
                    except: pass
                
                t_up = t_total - t_down
                if t_up < 0: t_up = 0 # Edge case
                
                mtbf = t_up / n_failures if n_failures > 0 else t_up # If 0 failures, MTBF is full period
                mttr = t_down / n_failures if n_failures > 0 else 0
                availability = (mtbf / (mtbf + mttr)) * 100 if (mtbf + mttr) > 0 else 100
                
                results.append({
                    "id": g['id'],
                    "name": g['name'],
                    "cost": round(total_cost, 2),
                    "failures": n_failures,
                    "mtbf": round(mtbf, 1),
                    "mttr": round(mttr, 1),
                    "availability": round(availability, 2),
                    "ot_count": len(ots)
                })
                
            return jsonify({
                "level": level,
                "groups": results
            })
            
        except Exception as e:
            logger.error(f"KPI Report Error: {e}")
            # traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/reports/recurrent-failures', methods=['GET'])
    def recurrent_failures_report():
        try:
            days = int(request.args.get('days', 60))
            threshold = int(request.args.get('threshold', 3))
            failure_mode_filter = (request.args.get('failure_mode') or '').strip().lower()
            only_alerts = request.args.get('only_alerts', 'true').lower() == 'true'

            start_window = dt.date.today() - dt.timedelta(days=days)

            systems_map = {s.id: s for s in System.query.all()}
            components_map = {c.id: c for c in Component.query.all()}
            equipments_map = {e.id: e for e in Equipment.query.all()}

            ots = WorkOrder.query.filter(
                WorkOrder.status == 'Cerrada',
                WorkOrder.maintenance_type == 'Correctivo',
                WorkOrder.failure_mode != None,
                WorkOrder.failure_mode != ''
            ).all()

            grouped = {}
            for ot in ots:
                end_date = _parse_date_flexible(ot.real_end_date)
                if not end_date or end_date < start_window:
                    continue

                failure_mode = (ot.failure_mode or '').strip()
                normalized_mode = failure_mode.lower()
                if failure_mode_filter and failure_mode_filter not in normalized_mode:
                    continue

                equipment_id = ot.equipment_id
                if not equipment_id and ot.system_id:
                    sys = systems_map.get(ot.system_id)
                    if sys:
                        equipment_id = sys.equipment_id
                if not equipment_id and ot.component_id:
                    comp = components_map.get(ot.component_id)
                    if comp:
                        sys = systems_map.get(comp.system_id)
                        if sys:
                            equipment_id = sys.equipment_id

                eq = equipments_map.get(equipment_id) if equipment_id else None
                asset_label = f"{eq.tag} - {eq.name}" if eq else "Sin Activo"
                asset_key = f"EQUIPMENT:{equipment_id}" if equipment_id else "SIN_ASSET"
                group_key = f"{asset_key}|{normalized_mode}"

                if group_key not in grouped:
                    grouped[group_key] = {
                        "asset_label": asset_label,
                        "asset_key": asset_key,
                        "failure_mode": failure_mode,
                        "count": 0,
                        "ot_codes": [],
                        "last_date": None,
                        "latest_comment": None,
                        "latest_root_cause": None
                    }

                grouped[group_key]["count"] += 1
                grouped[group_key]["ot_codes"].append(ot.code or f"OT-{ot.id}")
                if ot.execution_comments:
                    grouped[group_key]["latest_comment"] = ot.execution_comments
                if not grouped[group_key]["last_date"] or end_date > grouped[group_key]["last_date"]:
                    grouped[group_key]["last_date"] = end_date

            rows = list(grouped.values())
            for row in rows:
                row["is_alert"] = row["count"] >= threshold
                row["last_date"] = row["last_date"].isoformat() if row["last_date"] else None
                row["message"] = (
                    f"El activo {row['asset_label']} tuvo {row['count']} eventos "
                    f"de '{row['failure_mode']}' en los ultimos {days} dias."
                )

            if only_alerts:
                rows = [r for r in rows if r["is_alert"]]

            rows.sort(key=lambda r: (r["count"], r["last_date"] or ""), reverse=True)

            return jsonify({
                "days": days,
                "threshold": threshold,
                "window_start": start_window.isoformat(),
                "window_end": dt.date.today().isoformat(),
                "total_groups": len(grouped),
                "alerts": len([r for r in rows if r["is_alert"]]),
                "items": rows
            })
        except Exception as e:
            logger.error(f"Recurrent Failures Report Error: {e}")
            return jsonify({"error": str(e)}), 500


    @app.route('/api/reports/executive', methods=['GET'])
    def get_executive_reports():
        try:
            start_date = _parse_date_flexible(request.args.get('start_date')) or (dt.date.today() - dt.timedelta(days=29))
            end_date = _parse_date_flexible(request.args.get('end_date')) or dt.date.today()
            if start_date > end_date:
                start_date, end_date = end_date, start_date

            area_id = request.args.get('area_id', type=int)
            line_id = request.args.get('line_id', type=int)
            equipment_id = request.args.get('equipment_id', type=int)

            lines = Line.query.all()
            systems = System.query.all()
            components = Component.query.all()
            equipments = Equipment.query.all()
            areas = Area.query.all()
            warehouse_items = WarehouseItem.query.with_entities(WarehouseItem.id, WarehouseItem.unit_cost).all()

            area_map = {a.id: a for a in areas}
            line_map = {l.id: l for l in lines}
            system_map = {s.id: s for s in systems}
            component_map = {c.id: c for c in components}
            equipment_map = {e.id: e for e in equipments}
            warehouse_cost = {w.id: float(w.unit_cost or 0) for w in warehouse_items}

            def resolve_equipment(ot):
                eq_id = ot.equipment_id
                if not eq_id and ot.system_id and ot.system_id in system_map:
                    eq_id = system_map[ot.system_id].equipment_id
                if not eq_id and ot.component_id and ot.component_id in component_map:
                    comp = component_map[ot.component_id]
                    sys = system_map.get(comp.system_id)
                    if sys:
                        eq_id = sys.equipment_id
                return eq_id

            def ot_matches_filters(ot):
                eq_id = resolve_equipment(ot)
                if equipment_id and eq_id != equipment_id:
                    return False
                ot_line_id = ot.line_id
                if not ot_line_id and eq_id and eq_id in equipment_map:
                    ot_line_id = equipment_map[eq_id].line_id
                if line_id and ot_line_id != line_id:
                    return False
                ot_area_id = ot.area_id
                if not ot_area_id and ot_line_id and ot_line_id in line_map:
                    ot_area_id = line_map[ot_line_id].area_id
                if area_id and ot_area_id != area_id:
                    return False
                return True

            all_ots = WorkOrder.query.all()
            window_ots = []
            planned_ots = []

            event_date_map = {}
            scheduled_date_map = {}
            eq_line_area_cache = {}
            for ot in all_ots:
                if not ot_matches_filters(ot):
                    continue

                eq_id = resolve_equipment(ot)
                line_ref = ot.line_id or (equipment_map[eq_id].line_id if eq_id and eq_id in equipment_map else None)
                area_ref = ot.area_id or (line_map[line_ref].area_id if line_ref and line_ref in line_map else None)
                eq_line_area_cache[ot.id] = (eq_id, line_ref, area_ref)

                scheduled = _parse_date_flexible(ot.scheduled_date)
                event_date = _parse_date_flexible(ot.real_end_date) or _parse_date_flexible(ot.real_start_date) or scheduled
                scheduled_date_map[ot.id] = scheduled
                event_date_map[ot.id] = event_date

                if _is_in_window(scheduled, start_date, end_date):
                    planned_ots.append(ot)
                if _is_in_window(event_date, start_date, end_date):
                    window_ots.append(ot)

            ot_ids = [ot.id for ot in window_ots]
            ot_costs = defaultdict(float)
            if ot_ids:
                materials = OTMaterial.query.filter(OTMaterial.work_order_id.in_(ot_ids), OTMaterial.item_type == 'warehouse').all()
                for mat in materials:
                    ot_costs[mat.work_order_id] += float(mat.quantity or 0) * warehouse_cost.get(mat.item_id, 0)

            planned_total = len(planned_ots)
            planned_closed = len([ot for ot in planned_ots if (ot.status or '').strip().lower() == 'cerrada'])
            preventive_count = len([ot for ot in window_ots if _normalize_maintenance_type(ot.maintenance_type) == 'preventivo'])
            corrective_ots = [ot for ot in window_ots if _normalize_maintenance_type(ot.maintenance_type) == 'correctivo']
            corrective_count = len(corrective_ots)

            downtime_hours = sum([_safe_duration_hours(ot) for ot in corrective_ots])
            failures = len([ot for ot in corrective_ots if _safe_duration_hours(ot) > 0])
            total_cost = round(sum([ot_costs.get(ot.id, 0) for ot in window_ots]), 2)

            filtered_equipment_ids = set([eq for eq, _, _ in eq_line_area_cache.values() if eq])
            equipment_base = max(1, len(filtered_equipment_ids))
            window_days = max((end_date - start_date).days + 1, 1)
            total_hours = equipment_base * window_days * 24
            uptime = max(total_hours - downtime_hours, 0)
            availability = (uptime / total_hours * 100) if total_hours > 0 else 100
            mtbf = (uptime / failures) if failures else uptime
            mttr = (downtime_hours / failures) if failures else 0
            compliance = (planned_closed / planned_total * 100) if planned_total else 100

            def breakdown(level):
                rows = {}
                for ot in window_ots:
                    eq_id, line_ref, area_ref = eq_line_area_cache.get(ot.id, (None, None, None))
                    if level == "areas":
                        key = area_ref or "NA"
                        name = area_map[area_ref].name if area_ref and area_ref in area_map else "Sin area"
                    elif level == "lines":
                        key = line_ref or "NA"
                        name = line_map[line_ref].name if line_ref and line_ref in line_map else "Sin linea"
                    else:
                        key = eq_id or "NA"
                        if eq_id and eq_id in equipment_map:
                            eq = equipment_map[eq_id]
                            name = f"{eq.tag} - {eq.name}"
                        else:
                            name = "Sin equipo"

                    if key not in rows:
                        rows[key] = {
                            "id": key,
                            "name": name,
                            "planned_total": 0,
                            "planned_closed": 0,
                            "total_ots": 0,
                            "preventive_count": 0,
                            "corrective_count": 0,
                            "downtime_hours": 0.0,
                            "availability": 100.0,
                            "mtbf": 0.0,
                            "mttr": 0.0,
                            "cost": 0.0
                        }

                    row = rows[key]
                    row["total_ots"] += 1
                    if _normalize_maintenance_type(ot.maintenance_type) == "preventivo":
                        row["preventive_count"] += 1
                    if _normalize_maintenance_type(ot.maintenance_type) == "correctivo":
                        row["corrective_count"] += 1
                        row["downtime_hours"] += _safe_duration_hours(ot)
                    row["cost"] += ot_costs.get(ot.id, 0)

                for ot in planned_ots:
                    eq_id, line_ref, area_ref = eq_line_area_cache.get(ot.id, (None, None, None))
                    key = area_ref if level == "areas" else line_ref if level == "lines" else eq_id
                    key = key or "NA"
                    if key not in rows:
                        continue
                    rows[key]["planned_total"] += 1
                    if (ot.status or '').strip().lower() == 'cerrada':
                        rows[key]["planned_closed"] += 1

                result = []
                for _, row in rows.items():
                    row_hours = max(24 * window_days, row["downtime_hours"])
                    row_uptime = max(row_hours - row["downtime_hours"], 0)
                    row_failures = max(1, int(row["corrective_count"])) if row["corrective_count"] > 0 else 0
                    row["availability"] = round((row_uptime / row_hours * 100) if row_hours else 100, 2)
                    row["mtbf"] = round((row_uptime / row_failures) if row_failures else row_uptime, 2)
                    row["mttr"] = round((row["downtime_hours"] / row_failures) if row_failures else 0, 2)
                    row["downtime_hours"] = round(row["downtime_hours"], 2)
                    row["cost"] = round(row["cost"], 2)
                    row["compliance_percent"] = round((row["planned_closed"] / row["planned_total"] * 100), 1) if row["planned_total"] else 100.0
                    result.append(row)

                result.sort(key=lambda x: x["name"])
                return result

            trend = []
            month_cursor = dt.date(start_date.year, start_date.month, 1)
            end_month = dt.date(end_date.year, end_date.month, 1)
            while month_cursor <= end_month:
                month_key = f"{month_cursor.year}-{month_cursor.month:02d}"
                next_month = dt.date(month_cursor.year + (1 if month_cursor.month == 12 else 0), 1 if month_cursor.month == 12 else month_cursor.month + 1, 1)
                month_end = next_month - dt.timedelta(days=1)
                month_start = max(month_cursor, start_date)
                month_finish = min(month_end, end_date)
                mdays = max((month_finish - month_start).days + 1, 1)
                mhours = equipment_base * mdays * 24

                month_planned = [ot for ot in planned_ots if scheduled_date_map.get(ot.id) and month_start <= scheduled_date_map.get(ot.id) <= month_finish]
                month_window = [ot for ot in window_ots if event_date_map.get(ot.id) and month_start <= event_date_map.get(ot.id) <= month_finish]
                month_corr = [ot for ot in month_window if _normalize_maintenance_type(ot.maintenance_type) == "correctivo"]
                month_downtime = sum([_safe_duration_hours(ot) for ot in month_corr])
                month_uptime = max(mhours - month_downtime, 0)
                trend.append({
                    "period": month_key,
                    "planned_total": len(month_planned),
                    "planned_closed": len([ot for ot in month_planned if (ot.status or "").strip().lower() == "cerrada"]),
                    "compliance_percent": round((len([ot for ot in month_planned if (ot.status or '').strip().lower() == 'cerrada']) / len(month_planned) * 100), 1) if month_planned else 100.0,
                    "preventive_count": len([ot for ot in month_window if _normalize_maintenance_type(ot.maintenance_type) == "preventivo"]),
                    "corrective_count": len(month_corr),
                    "downtime_hours": round(month_downtime, 2),
                    "availability": round((month_uptime / mhours * 100) if mhours else 100.0, 2)
                })
                month_cursor = next_month

            causes = defaultdict(lambda: {"cause": "", "count": 0, "downtime_hours": 0.0, "cost": 0.0})
            downtime_events = []
            for ot in corrective_ots:
                duration = _safe_duration_hours(ot)
                if duration <= 0:
                    continue
                key = (ot.failure_mode or "Sin clasificar").strip().lower()
                if not causes[key]["cause"]:
                    causes[key]["cause"] = (ot.failure_mode or "Sin clasificar").strip()
                causes[key]["count"] += 1
                causes[key]["downtime_hours"] += duration
                causes[key]["cost"] += ot_costs.get(ot.id, 0)

                eq_id, line_ref, area_ref = eq_line_area_cache.get(ot.id, (None, None, None))
                area_name = Area.query.get(area_ref).name if area_ref else "Sin area"
                line_name = line_map[line_ref].name if line_ref and line_ref in line_map else "Sin linea"
                if eq_id and eq_id in equipment_map:
                    eq = equipment_map[eq_id]
                    equipment_name = f"{eq.tag} - {eq.name}"
                else:
                    equipment_name = "Sin equipo"
                downtime_events.append({
                    "ot_code": ot.code or f"OT-{ot.id}",
                    "date": (event_date_map.get(ot.id).isoformat() if event_date_map.get(ot.id) else "-"),
                    "area": area_name,
                    "line": line_name,
                    "equipment": equipment_name,
                    "failure_mode": ot.failure_mode or "-",
                    "root_cause": "-",
                    "duration_hours": round(duration, 2),
                    "cost": round(ot_costs.get(ot.id, 0), 2),
                    "description": ot.description or "-"
                })

            downtime_causes = list(causes.values())
            downtime_causes.sort(key=lambda c: c["downtime_hours"], reverse=True)
            for c in downtime_causes:
                c["downtime_hours"] = round(c["downtime_hours"], 2)
                c["cost"] = round(c["cost"], 2)

            downtime_events.sort(key=lambda e: e["duration_hours"], reverse=True)

            return jsonify({
                "meta": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "window_days": window_days,
                    "equipment_base": equipment_base,
                    "filters": {"area_id": area_id, "line_id": line_id, "equipment_id": equipment_id}
                },
                "summary": {
                    "planned_total": planned_total,
                    "planned_closed": planned_closed,
                    "compliance_percent": round(compliance, 1),
                    "total_ots": len(window_ots),
                    "preventive_count": preventive_count,
                    "corrective_count": corrective_count,
                    "downtime_hours": round(downtime_hours, 2),
                    "availability": round(availability, 2),
                    "availability_loss_percent": round(max(0, 100 - availability), 2),
                    "mtbf": round(mtbf, 2),
                    "mttr": round(mttr, 2),
                    "cost": total_cost
                },
                "breakdown": {
                    "areas": breakdown("areas"),
                    "lines": breakdown("lines"),
                    "equipments": breakdown("equipments")
                },
                "trend": trend,
                "downtime_causes": downtime_causes[:12],
                "downtime_events": downtime_events[:100]
            })
        except Exception as e:
            logger.error(f"Executive report error: {e}")
            return jsonify({"error": str(e)}), 500

    def _resolve_weekly_window(window_key, start_raw, end_raw, reference_raw):
        reference_date = _parse_date_flexible(reference_raw) or dt.date.today()
        monday = reference_date - dt.timedelta(days=reference_date.weekday())

        normalized = (window_key or 'current_week').strip().lower()
        start_date = monday
        end_date = monday + dt.timedelta(days=6)

        if normalized == 'next_week':
            start_date = monday + dt.timedelta(days=7)
            end_date = start_date + dt.timedelta(days=6)
        elif normalized == 'weekend':
            start_date = monday + dt.timedelta(days=5)
            end_date = start_date + dt.timedelta(days=1)
            if reference_date > end_date:
                start_date += dt.timedelta(days=7)
                end_date += dt.timedelta(days=7)
        elif normalized == 'custom':
            custom_start = _parse_date_flexible(start_raw)
            custom_end = _parse_date_flexible(end_raw)
            if custom_start and custom_end:
                start_date = min(custom_start, custom_end)
                end_date = max(custom_start, custom_end)
            else:
                normalized = 'current_week'
        else:
            normalized = 'current_week'

        return normalized, start_date, end_date

    def _normalize_specialty_label(raw_value):
        value = (raw_value or '').strip().upper()
        if not value:
            return 'SIN ASIGNAR'
        if 'ELECT' in value:
            return 'ELECTRICO'
        if 'MEC' in value:
            return 'MECANICO'
        if 'MIX' in value:
            return 'MIXTO'
        return value

    def _specialty_for_ot(ot):
        specialties = []
        for assignment in getattr(ot, 'assigned_personnel', []) or []:
            candidate = assignment.specialty
            if not candidate and assignment.technician:
                candidate = assignment.technician.specialty
            normalized = _normalize_specialty_label(candidate)
            if normalized and normalized != 'SIN ASIGNAR':
                specialties.append(normalized)

        if not specialties and getattr(ot, 'provider', None) and ot.provider.specialty:
            provider_specialty = _normalize_specialty_label(ot.provider.specialty)
            if provider_specialty and provider_specialty != 'SIN ASIGNAR':
                specialties.append(provider_specialty)

        unique_specialties = sorted(set(specialties))
        if not unique_specialties:
            return 'SIN ASIGNAR'
        if 'MECANICO' in unique_specialties and 'ELECTRICO' in unique_specialties:
            return 'MIXTO'
        if 'MECANICO' in unique_specialties:
            return 'MECANICO'
        if 'ELECTRICO' in unique_specialties:
            return 'ELECTRICO'
        return unique_specialties[0]

    def _collect_weekly_plan_payload():
        window_key = request.args.get('window', 'current_week')
        normalized_window, start_date, end_date = _resolve_weekly_window(
            window_key=window_key,
            start_raw=request.args.get('start_date'),
            end_raw=request.args.get('end_date'),
            reference_raw=request.args.get('reference_date')
        )

        area_id = request.args.get('area_id', type=int)
        line_id = request.args.get('line_id', type=int)
        equipment_id = request.args.get('equipment_id', type=int)
        wanted_status = (request.args.get('status') or '').strip().lower()
        wanted_specialty = _normalize_specialty_label(request.args.get('specialty') or '')
        if wanted_specialty == 'SIN ASIGNAR' and (request.args.get('specialty') or '').strip().lower() in {'', 'all', 'todas'}:
            wanted_specialty = ''
        raw_mtto = (request.args.get('maintenance_type') or '').strip()
        wanted_mtto = _normalize_maintenance_type(raw_mtto) if raw_mtto else ''

        lines = Line.query.all()
        systems = System.query.all()
        components = Component.query.all()
        equipments = Equipment.query.all()
        areas = Area.query.all()

        line_map = {l.id: l for l in lines}
        system_map = {s.id: s for s in systems}
        component_map = {c.id: c for c in components}
        equipment_map = {e.id: e for e in equipments}
        area_map = {a.id: a for a in areas}
        tech_map = {str(t.id): t.name for t in Technician.query.all()}

        def resolve_equipment_id(ot):
            eq_id = ot.equipment_id
            if not eq_id and ot.system_id and ot.system_id in system_map:
                eq_id = system_map[ot.system_id].equipment_id
            if not eq_id and ot.component_id and ot.component_id in component_map:
                comp = component_map[ot.component_id]
                sys = system_map.get(comp.system_id)
                if sys:
                    eq_id = sys.equipment_id
            return eq_id

        def resolve_line_area(eq_id, ot):
            line_ref = ot.line_id or (equipment_map[eq_id].line_id if eq_id and eq_id in equipment_map else None)
            area_ref = ot.area_id or (line_map[line_ref].area_id if line_ref and line_ref in line_map else None)
            return line_ref, area_ref

        items = []
        ots = WorkOrder.query.all()
        open_request_statuses = {'PENDIENTE', 'APROBADO', 'EN_ORDEN'}

        for ot in ots:
            plan_date = (
                _parse_date_flexible(ot.scheduled_date)
                or _parse_date_flexible(ot.real_start_date)
                or _parse_date_flexible(ot.real_end_date)
            )
            if not plan_date or not _is_in_window(plan_date, start_date, end_date):
                continue

            eq_id = resolve_equipment_id(ot)
            line_ref, area_ref = resolve_line_area(eq_id, ot)

            if equipment_id and eq_id != equipment_id:
                continue
            if line_id and line_ref != line_id:
                continue
            if area_id and area_ref != area_id:
                continue

            mtto_norm = _normalize_maintenance_type(ot.maintenance_type)
            if wanted_mtto and mtto_norm != wanted_mtto:
                continue

            status_value = (ot.status or '').strip()
            if wanted_status and status_value.lower() != wanted_status:
                continue

            specialty_value = _specialty_for_ot(ot)
            if wanted_specialty and specialty_value != wanted_specialty:
                continue

            req_total = 0
            req_pending = 0
            req_codes = []
            po_codes = []
            for req in getattr(ot, 'purchase_requests', []) or []:
                req_total += 1
                req_status = (req.status or 'PENDIENTE').strip().upper()
                if req_status in open_request_statuses:
                    req_pending += 1
                if req.req_code:
                    req_codes.append(req.req_code)
                if req.purchase_order and req.purchase_order.po_code:
                    po_codes.append(req.purchase_order.po_code)

            if req_total == 0:
                logistics = 'Sin solicitud'
            elif req_pending > 0:
                logistics = f'Bloqueada ({req_pending})'
            else:
                logistics = 'Lista'

            equipment = equipment_map.get(eq_id) if eq_id else None
            line_obj = line_map.get(line_ref) if line_ref else None
            area_obj = area_map.get(area_ref) if area_ref else None

            component = component_map.get(ot.component_id) if ot.component_id else None
            criticality = '-'
            if component and component.criticality:
                criticality = component.criticality
            elif equipment and equipment.criticality:
                criticality = equipment.criticality
            elif ot.notice and ot.notice.criticality:
                criticality = ot.notice.criticality

            priority = ot.notice.priority if ot.notice and ot.notice.priority else '-'
            shift = ot.notice.shift if ot.notice and ot.notice.shift else '-'
            reporter_area = ot.notice.reporter_type if ot.notice and ot.notice.reporter_type else '-'
            mtto_label = (mtto_norm or '').capitalize() if mtto_norm else (ot.maintenance_type or '-')

            items.append({
                'id': ot.id,
                'code': ot.code or f'OT-{ot.id}',
                'notice_code': ot.notice.code if ot.notice and ot.notice.code else '-',
                'scheduled_date': plan_date.isoformat(),
                'status': status_value or '-',
                'maintenance_type': mtto_label or '-',
                'specialty': specialty_value,
                'area': area_obj.name if area_obj else '-',
                'line': line_obj.name if line_obj else '-',
                'equipment': equipment.name if equipment else '-',
                'equipment_tag': equipment.tag if equipment and equipment.tag else '-',
                'system': system_map[ot.system_id].name if ot.system_id and ot.system_id in system_map else '-',
                'component': component.name if component else '-',
                'criticality': criticality or '-',
                'priority': priority or '-',
                'description': ot.description or '-',
                'estimated_duration': float(ot.estimated_duration or 0),
                'tech_count': int(ot.tech_count or 0),
                'shift': shift,
                'reporter_area': reporter_area,
                'req_total': req_total,
                'req_pending': req_pending,
                'logistics': logistics,
                'req_codes': sorted(set(req_codes)),
                'po_codes': sorted(set(po_codes)),
                'technician': tech_map.get(str(ot.technician_id), ot.technician_id or '-'),
            })

        items.sort(key=lambda row: (row['scheduled_date'], row['area'], row['line'], row['equipment'], row['code']))

        total = len(items)
        preventive_count = len([i for i in items if (i['maintenance_type'] or '').lower() == 'preventivo'])
        corrective_count = len([i for i in items if (i['maintenance_type'] or '').lower() == 'correctivo'])
        closed_count = len([i for i in items if (i['status'] or '').strip().lower() == 'cerrada'])
        no_ejecutada_count = len([i for i in items if (i['status'] or '').strip().lower() == 'no ejecutada'])
        blocked_count = len([i for i in items if i.get('req_pending', 0) > 0])
        completion_percent = round((closed_count / total * 100), 1) if total else 0.0

        specialty_counts = defaultdict(int)
        status_counts = defaultdict(int)
        day_rows = []
        day_cursor = start_date
        day_seed = {}
        while day_cursor <= end_date:
            key = day_cursor.isoformat()
            day_seed[key] = {
                'date': key,
                'total': 0,
                'preventive': 0,
                'corrective': 0,
                'blocked': 0,
            }
            day_cursor += dt.timedelta(days=1)

        for item in items:
            specialty_counts[item['specialty']] += 1
            status_counts[item['status']] += 1
            day_key = item['scheduled_date']
            if day_key not in day_seed:
                continue
            day_seed[day_key]['total'] += 1
            if (item['maintenance_type'] or '').lower() == 'preventivo':
                day_seed[day_key]['preventive'] += 1
            if (item['maintenance_type'] or '').lower() == 'correctivo':
                day_seed[day_key]['corrective'] += 1
            if item.get('req_pending', 0) > 0:
                day_seed[day_key]['blocked'] += 1

        for key in sorted(day_seed.keys()):
            day_rows.append(day_seed[key])

        return {
            'meta': {
                'window': normalized_window,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'days': max((end_date - start_date).days + 1, 1),
                'filters': {
                    'area_id': area_id,
                    'line_id': line_id,
                    'equipment_id': equipment_id,
                    'status': wanted_status or None,
                    'specialty': wanted_specialty or None,
                    'maintenance_type': wanted_mtto or None,
                }
            },
            'summary': {
                'total': total,
                'preventive': preventive_count,
                'corrective': corrective_count,
                'closed': closed_count,
                'no_ejecutada': no_ejecutada_count,
                'blocked': blocked_count,
                'completion_percent': completion_percent,
                'specialty_counts': dict(specialty_counts),
                'status_counts': dict(status_counts),
            },
            'daily': day_rows,
            'items': items,
        }
    @app.route('/api/reports/weekly-plan', methods=['GET'])
    def get_weekly_plan():
        try:
            return jsonify(_collect_weekly_plan_payload())
        except Exception as e:
            logger.error(f"Weekly plan report error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/reports/weekly-plan/export', methods=['GET'])
    def export_weekly_plan_excel():
        try:
            payload = _collect_weekly_plan_payload()
            rows = payload.get('items', [])
            if rows:
                export_rows = []
                for row in rows:
                    export_rows.append({
                        'Codigo OT': row.get('code'),
                        'Aviso': row.get('notice_code'),
                        'Fecha Plan': row.get('scheduled_date'),
                        'Tecnico Asignado': row.get('technician', '-'),
                        'Cant Tecnicos': row.get('tech_count'),
                        'Especialidad': row.get('specialty'),
                        'Tipo Mtto': row.get('maintenance_type'),
                        'Estado': row.get('status'),
                        'Area': row.get('area'),
                        'Linea': row.get('line'),
                        'Equipo': row.get('equipment'),
                        'TAG': row.get('equipment_tag'),
                        'Sistema': row.get('system'),
                        'Componente': row.get('component'),
                        'Criticidad': row.get('criticality'),
                        'Prioridad': row.get('priority'),
                        'Turno': row.get('shift'),
                        'Horas Est': row.get('estimated_duration'),
                        'Cant Tecnicos': row.get('tech_count'),
                        'Logistica': row.get('logistics'),
                        'Req Pendientes': row.get('req_pending'),
                        'Req Total': row.get('req_total'),
                        'REQ': ', '.join(row.get('req_codes', [])),
                        'OC': ', '.join(row.get('po_codes', [])),
                        'Descripcion': row.get('description'),
                    })
            else:
                export_rows = [{
                    'Codigo OT': '-',
                    'Aviso': '-',
                    'Fecha Plan': payload['meta']['start_date'],
                    'Especialidad': '-',
                    'Tipo Mtto': '-',
                    'Estado': '-',
                    'Area': '-',
                    'Linea': '-',
                    'Equipo': '-',
                    'TAG': '-',
                    'Sistema': '-',
                    'Componente': '-',
                    'Criticidad': '-',
                    'Prioridad': '-',
                    'Turno': '-',
                    'Horas Est': 0,
                    'Cant Tecnicos': 0,
                    'Logistica': 'Sin datos',
                    'Req Pendientes': 0,
                    'Req Total': 0,
                    'REQ': '-',
                    'OC': '-',
                    'Descripcion': 'Sin actividades para el filtro seleccionado',
                }]

            summary = payload.get('summary', {})
            meta = payload.get('meta', {})
            summary_rows = [
                {'Indicador': 'Ventana', 'Valor': f"{meta.get('start_date', '-')} a {meta.get('end_date', '-')}", 'Detalle': meta.get('window', '-')},
                {'Indicador': 'Total actividades', 'Valor': summary.get('total', 0), 'Detalle': ''},
                {'Indicador': 'Preventivos', 'Valor': summary.get('preventive', 0), 'Detalle': ''},
                {'Indicador': 'Correctivos', 'Valor': summary.get('corrective', 0), 'Detalle': ''},
                {'Indicador': 'Cerradas (Ejecutadas)', 'Valor': summary.get('closed', 0), 'Detalle': ''},
                {'Indicador': 'No Ejecutadas', 'Valor': summary.get('no_ejecutada', 0), 'Detalle': 'Marcadas explicitamente como no ejecutadas'},
                {'Indicador': 'Bloqueadas por logistica', 'Valor': summary.get('blocked', 0), 'Detalle': ''},
                {'Indicador': 'Cumplimiento %', 'Valor': summary.get('completion_percent', 0), 'Detalle': 'Cerradas / Total programadas'},
            ]

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                pd.DataFrame(export_rows).to_excel(writer, index=False, sheet_name='Plan Semanal')
                pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name='Indicadores')

            output.seek(0)
            filename = f"Plan_Semanal_{meta.get('start_date', 'inicio')}_a_{meta.get('end_date', 'fin')}.xlsx"
            return send_file(
                output,
                as_attachment=True,
                download_name=filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            logger.error(f"Weekly plan export error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── POWER BI EXPORT — Multi-sheet Excel with raw data ──────────────────

    def _resolve_name(Model, obj_id):
        """Resolve a foreign key ID to its name."""
        if not obj_id:
            return None
        obj = Model.query.get(obj_id)
        return obj.name if obj else None

    def _resolve_equip_tag(obj_id):
        if not obj_id:
            return None
        eq = Equipment.query.get(obj_id)
        return eq.tag if eq else None

    @app.route('/api/reports/powerbi-export', methods=['GET'])
    def export_powerbi_excel():
        try:
            # ── Lookup caches ──────────────────────────────────────────────
            areas_map = {a.id: a.name for a in Area.query.all()}
            lines_map = {l.id: l.name for l in Line.query.all()}
            equips_map = {e.id: e.name for e in Equipment.query.all()}
            equip_tags = {e.id: e.tag for e in Equipment.query.all()}
            systems_map = {s.id: s.name for s in System.query.all()}
            comps_map = {c.id: c.name for c in Component.query.all()}
            techs_map = {t.id: t.name for t in Technician.query.all()}
            provs_map = {p.id: p.name for p in Provider.query.all()}

            def area(i): return areas_map.get(i)
            def line(i): return lines_map.get(i)
            def equip(i): return equips_map.get(i)
            def tag(i): return equip_tags.get(i)
            def syst(i): return systems_map.get(i)
            def comp(i): return comps_map.get(i)
            def tech(i): return techs_map.get(i)
            def prov(i): return provs_map.get(i)

            # ── 1. ORDENES DE TRABAJO ──────────────────────────────────────
            ots = WorkOrder.query.order_by(WorkOrder.id).all()
            ot_rows = []
            for o in ots:
                real_start = _parse_date_flexible(o.real_start_date)
                real_end = _parse_date_flexible(o.real_end_date)
                sched = _parse_date_flexible(o.scheduled_date)
                duration_h = _safe_duration_hours(o.real_duration)

                # Calculate actual hours from personnel if no duration
                if not duration_h and real_start and real_end:
                    delta = real_end - real_start
                    duration_h = round(delta.total_seconds() / 3600, 2)

                # On-time flag
                on_time = None
                if sched and real_end:
                    on_time = 'Si' if real_end <= sched else 'No'
                elif sched and o.status == 'Cerrada' and not real_end:
                    on_time = 'Sin fecha cierre'

                ot_rows.append({
                    'Codigo_OT': o.code,
                    'Aviso': o.notice_id,
                    'Estado': o.status,
                    'Tipo_Mantenimiento': o.maintenance_type,
                    'Modo_Falla': o.failure_mode,
                    'Descripcion': o.description,
                    'Prioridad': getattr(o, 'priority', None),
                    'Area': area(o.area_id),
                    'Linea': line(o.line_id),
                    'Equipo': equip(o.equipment_id),
                    'TAG': tag(o.equipment_id),
                    'Sistema': syst(o.system_id),
                    'Componente': comp(o.component_id),
                    'Tecnico': tech(o.technician_id),
                    'Proveedor': prov(o.provider_id),
                    'Fecha_Programada': o.scheduled_date,
                    'Fecha_Inicio_Real': o.real_start_date,
                    'Fecha_Fin_Real': o.real_end_date,
                    'Duracion_Horas': duration_h,
                    'Duracion_Estimada': o.estimated_duration,
                    'Cant_Tecnicos': o.tech_count,
                    'A_Tiempo': on_time,
                    'Comentarios_Ejecucion': o.execution_comments,
                    'Causo_Parada': 'Si' if getattr(o, 'caused_downtime', False) else 'No',
                    'Horas_Parada': getattr(o, 'downtime_hours', None),
                    'Origen_Tipo': getattr(o, 'source_type', None),
                    'Origen_ID': getattr(o, 'source_id', None),
                })
            df_ots = pd.DataFrame(ot_rows)

            # ── 2. AVISOS ──────────────────────────────────────────────────
            notices = MaintenanceNotice.query.order_by(MaintenanceNotice.id).all()
            notice_rows = []
            for n in notices:
                req = _parse_date_flexible(n.request_date)
                treat = _parse_date_flexible(n.treatment_date)
                response_days = None
                if req and treat:
                    response_days = (treat - req).days

                notice_rows.append({
                    'Codigo_Aviso': n.code,
                    'Estado': n.status,
                    'Tipo_Mantenimiento': n.maintenance_type,
                    'Descripcion': n.description,
                    'Prioridad': n.priority,
                    'Criticidad': n.criticality,
                    'Especialidad': n.specialty,
                    'Turno': n.shift,
                    'Reportado_Por': n.reporter_name,
                    'Tipo_Reportante': n.reporter_type,
                    'Area': area(n.area_id),
                    'Linea': line(n.line_id),
                    'Equipo': equip(n.equipment_id),
                    'TAG': tag(n.equipment_id),
                    'Sistema': syst(n.system_id),
                    'Componente': comp(n.component_id),
                    'Fecha_Solicitud': n.request_date,
                    'Fecha_Tratamiento': n.treatment_date,
                    'Fecha_Planificacion': n.planning_date,
                    'Dias_Respuesta': response_days,
                    'OT_Asociada': n.ot_number,
                    'Motivo_Cancelacion': n.cancellation_reason,
                    'Origen_Tipo': getattr(n, 'source_type', None),
                    'Origen_ID': getattr(n, 'source_id', None),
                })
            df_notices = pd.DataFrame(notice_rows)

            # ── 3. PERSONAL EN OTs ─────────────────────────────────────────
            personnel = OTPersonnel.query.order_by(OTPersonnel.id).all()
            pers_rows = []
            # Build OT code lookup
            ot_code_map = {o.id: o.code for o in ots}
            for p in personnel:
                pers_rows.append({
                    'Codigo_OT': ot_code_map.get(p.work_order_id),
                    'Tecnico': tech(p.technician_id),
                    'Especialidad': p.specialty,
                    'Horas_Asignadas': p.hours_assigned,
                    'Horas_Trabajadas': p.hours_worked,
                })
            df_personnel = pd.DataFrame(pers_rows)

            # ── 4. MATERIALES EN OTs ───────────────────────────────────────
            materials = OTMaterial.query.order_by(OTMaterial.id).all()
            mat_rows = []
            for m in materials:
                item_name = None
                item_code = None
                unit_cost = 0
                if m.item_type == 'warehouse':
                    wi = WarehouseItem.query.get(m.item_id)
                    if wi:
                        item_name = wi.name
                        item_code = wi.code
                        unit_cost = wi.unit_cost or 0

                mat_rows.append({
                    'Codigo_OT': ot_code_map.get(m.work_order_id),
                    'Tipo_Item': m.item_type,
                    'Codigo_Item': item_code,
                    'Nombre_Item': item_name,
                    'Cantidad': m.quantity,
                    'Costo_Unitario': unit_cost,
                    'Costo_Total': round((m.quantity or 0) * unit_cost, 2),
                })
            df_materials = pd.DataFrame(mat_rows)

            # ── 5. LUBRICACIÓN — Puntos ────────────────────────────────────
            lub_points = LubricationPoint.query.order_by(LubricationPoint.id).all()
            lub_rows = []
            for p in lub_points:
                lub_rows.append({
                    'Codigo': p.code,
                    'Nombre': p.name,
                    'Activo': 'Si' if p.is_active else 'No',
                    'Area': area(p.area_id),
                    'Linea': line(p.line_id),
                    'Equipo': equip(p.equipment_id),
                    'TAG': tag(p.equipment_id),
                    'Sistema': syst(p.system_id),
                    'Componente': comp(p.component_id),
                    'Lubricante': p.lubricant_name,
                    'Cantidad_Nominal': p.quantity_nominal,
                    'Unidad': p.quantity_unit,
                    'Frecuencia_Dias': p.frequency_days,
                    'Ultimo_Servicio': p.last_service_date,
                    'Proximo_Vencimiento': p.next_due_date,
                    'Semaforo': p.semaphore_status,
                })
            df_lub_points = pd.DataFrame(lub_rows)

            # ── 6. LUBRICACIÓN — Ejecuciones ──────────────────────────────
            lub_execs = LubricationExecution.query.order_by(LubricationExecution.id).all()
            lub_exec_rows = []
            lub_point_map = {p.id: (p.code, p.name) for p in lub_points}
            for e in lub_execs:
                pcode, pname = lub_point_map.get(e.point_id, (None, None))
                lub_exec_rows.append({
                    'Codigo_Punto': pcode,
                    'Nombre_Punto': pname,
                    'Fecha_Ejecucion': e.execution_date,
                    'Accion': e.action_type,
                    'Cantidad': e.quantity_used,
                    'Unidad': e.quantity_unit,
                    'Ejecutado_Por': e.executed_by,
                    'Fuga_Detectada': 'Si' if e.leak_detected else 'No',
                    'Anomalia': 'Si' if e.anomaly_detected else 'No',
                    'Comentario': e.comments,
                    'Aviso_Generado': e.created_notice_id,
                })
            df_lub_execs = pd.DataFrame(lub_exec_rows)

            # ── 7. MONITOREO — Puntos ─────────────────────────────────────
            mon_points = MonitoringPoint.query.order_by(MonitoringPoint.id).all()
            mon_rows = []
            for p in mon_points:
                mon_rows.append({
                    'Codigo': p.code,
                    'Nombre': p.name,
                    'Activo': 'Si' if p.is_active else 'No',
                    'Tipo_Medicion': p.measurement_type,
                    'Eje': p.axis,
                    'Unidad': p.unit,
                    'Area': area(p.area_id),
                    'Linea': line(p.line_id),
                    'Equipo': equip(p.equipment_id),
                    'TAG': tag(p.equipment_id),
                    'Sistema': syst(p.system_id),
                    'Componente': comp(p.component_id),
                    'Normal_Min': p.normal_min,
                    'Normal_Max': p.normal_max,
                    'Alarma_Min': p.alarm_min,
                    'Alarma_Max': p.alarm_max,
                    'Frecuencia_Dias': p.frequency_days,
                    'Ultima_Medicion': p.last_measurement_date,
                    'Proximo_Vencimiento': p.next_due_date,
                    'Semaforo': p.semaphore_status,
                })
            df_mon_points = pd.DataFrame(mon_rows)

            # ── 8. MONITOREO — Lecturas ───────────────────────────────────
            mon_readings = MonitoringReading.query.order_by(MonitoringReading.id).all()
            mon_read_rows = []
            mon_point_map = {p.id: (p.code, p.name, p.unit) for p in mon_points}
            for r in mon_readings:
                pcode, pname, punit = mon_point_map.get(r.point_id, (None, None, None))
                mon_read_rows.append({
                    'Codigo_Punto': pcode,
                    'Nombre_Punto': pname,
                    'Fecha_Lectura': r.reading_date,
                    'Valor': r.value,
                    'Unidad': punit,
                    'Ejecutado_Por': r.executed_by,
                    'Regularizacion': 'Si' if r.is_regularization else 'No',
                    'Notas': r.notes,
                    'Aviso_Generado': r.created_notice_id,
                })
            df_mon_readings = pd.DataFrame(mon_read_rows)

            # ── 9. EQUIPOS (Jerarquía) ────────────────────────────────────
            equip_rows = []
            for e in Equipment.query.order_by(Equipment.id).all():
                l = Line.query.get(e.line_id) if e.line_id else None
                a = Area.query.get(l.area_id) if l and l.area_id else None
                equip_rows.append({
                    'ID': e.id,
                    'TAG': e.tag,
                    'Nombre': e.name,
                    'Criticidad': e.criticality,
                    'Linea': l.name if l else None,
                    'Area': a.name if a else None,
                })
            df_equipos = pd.DataFrame(equip_rows)

            # ── Build Excel workbook ──────────────────────────────────────
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_ots.to_excel(writer, index=False, sheet_name='OTs')
                df_notices.to_excel(writer, index=False, sheet_name='Avisos')
                df_personnel.to_excel(writer, index=False, sheet_name='Personal_OT')
                df_materials.to_excel(writer, index=False, sheet_name='Materiales_OT')
                df_lub_points.to_excel(writer, index=False, sheet_name='Lub_Puntos')
                df_lub_execs.to_excel(writer, index=False, sheet_name='Lub_Ejecuciones')
                df_mon_points.to_excel(writer, index=False, sheet_name='Mon_Puntos')
                df_mon_readings.to_excel(writer, index=False, sheet_name='Mon_Lecturas')
                df_equipos.to_excel(writer, index=False, sheet_name='Equipos')

                # ── 10. INSPECCIÓN — Rutas ─────────────────────────────────
                insp_routes = InspectionRoute.query.order_by(InspectionRoute.id).all()
                insp_route_rows = []
                for r in insp_routes:
                    insp_route_rows.append({
                        'Codigo': r.code,
                        'Nombre': r.name,
                        'Activo': 'Si' if r.is_active else 'No',
                        'Area': area(r.area_id),
                        'Linea': line(r.line_id),
                        'Equipo': equip(r.equipment_id),
                        'TAG': tag(r.equipment_id),
                        'Frecuencia_Dias': r.frequency_days,
                        'Ultima_Ejecucion': r.last_execution_date,
                        'Proximo_Vencimiento': r.next_due_date,
                        'Semaforo': r.semaphore_status,
                    })
                pd.DataFrame(insp_route_rows).to_excel(writer, index=False, sheet_name='Insp_Rutas')

                # ── 11. INSPECCIÓN — Ejecuciones + Resultados ──────────────
                insp_execs = InspectionExecution.query.order_by(InspectionExecution.id).all()
                insp_route_map = {r.id: (r.code, r.name) for r in insp_routes}
                insp_exec_rows = []
                for e in insp_execs:
                    rcode, rname = insp_route_map.get(e.route_id, (None, None))
                    # Get results for this execution
                    results = InspectionResult.query.filter_by(execution_id=e.id).all()
                    if results:
                        for res in results:
                            insp_exec_rows.append({
                                'Codigo_Ruta': rcode,
                                'Nombre_Ruta': rname,
                                'Fecha_Ejecucion': e.execution_date,
                                'Inspector': e.executed_by,
                                'Resultado_General': e.overall_result,
                                'Hallazgos': e.findings_count,
                                'Item': res.item.description if res.item else None,
                                'Tipo_Item': res.item.item_type if res.item else None,
                                'Resultado_Item': res.result,
                                'Valor': res.value,
                                'Texto': res.text_value,
                                'Observacion': res.observation,
                                'Aviso_Generado': e.created_notice_id,
                                'Comentario': e.comments,
                            })
                    else:
                        insp_exec_rows.append({
                            'Codigo_Ruta': rcode,
                            'Nombre_Ruta': rname,
                            'Fecha_Ejecucion': e.execution_date,
                            'Inspector': e.executed_by,
                            'Resultado_General': e.overall_result,
                            'Hallazgos': e.findings_count,
                            'Item': None,
                            'Tipo_Item': None,
                            'Resultado_Item': None,
                            'Valor': None,
                            'Texto': None,
                            'Observacion': None,
                            'Aviso_Generado': e.created_notice_id,
                            'Comentario': e.comments,
                        })
                pd.DataFrame(insp_exec_rows).to_excel(writer, index=False, sheet_name='Insp_Ejecuciones')

                # ── 12. ACTIVIDADES + HITOS ────────────────────────────────
                acts = Activity.query.order_by(Activity.id.desc()).all()
                act_rows = []
                for a in acts:
                    ms_list = [m for m in (a.milestones or []) if m.is_active]
                    done = sum(1 for m in ms_list if m.status == 'COMPLETADO')
                    total = len(ms_list)
                    if ms_list:
                        for m in ms_list:
                            act_rows.append({
                                'ID_Actividad': a.id,
                                'Titulo': a.title,
                                'Tipo': a.activity_type,
                                'Responsable': a.responsible,
                                'Prioridad': a.priority,
                                'Estado_Actividad': a.status,
                                'Fecha_Inicio': a.start_date,
                                'Fecha_Objetivo': a.target_date,
                                'Fecha_Completado': a.completion_date,
                                'Progreso_%': round((done / total) * 100) if total > 0 else 0,
                                'Hito': m.description,
                                'Hito_Objetivo': m.target_date,
                                'Hito_Completado': m.completion_date,
                                'Hito_Estado': m.status,
                                'Hito_Comentario': m.comment,
                            })
                    else:
                        act_rows.append({
                            'ID_Actividad': a.id,
                            'Titulo': a.title,
                            'Tipo': a.activity_type,
                            'Responsable': a.responsible,
                            'Prioridad': a.priority,
                            'Estado_Actividad': a.status,
                            'Fecha_Inicio': a.start_date,
                            'Fecha_Objetivo': a.target_date,
                            'Fecha_Completado': a.completion_date,
                            'Progreso_%': 0,
                            'Hito': None, 'Hito_Objetivo': None,
                            'Hito_Completado': None, 'Hito_Estado': None,
                            'Hito_Comentario': None,
                        })
                pd.DataFrame(act_rows).to_excel(writer, index=False, sheet_name='Actividades')

                # ── 13. ACTIVOS ROTATIVOS + BOM ────────────────────────────
                try:
                    from models import RotativeAsset as RA, RotativeAssetBOM as RABOM
                    ra_rows = []
                    for a in RA.query.order_by(RA.id).all():
                        bom_items = RABOM.query.filter_by(asset_id=a.id).all() if RABOM else []
                        if bom_items:
                            for b in bom_items:
                                ra_rows.append({
                                    'Codigo_Activo': a.code, 'Nombre_Activo': a.name,
                                    'Categoria': a.category, 'Marca': a.brand, 'Modelo': a.model,
                                    'Serie': a.serial_number, 'Estado': a.status,
                                    'Ubicacion': ' / '.join(filter(None, [
                                        a.area.name if a.area else None,
                                        a.line.name if a.line else None,
                                        a.equipment.name if a.equipment else None,
                                    ])),
                                    'Repuesto_Codigo': b.warehouse_item.code if b.warehouse_item else None,
                                    'Repuesto_Nombre': b.warehouse_item.name if b.warehouse_item else None,
                                    'Repuesto_Cat': b.category, 'Repuesto_Cant': b.quantity,
                                    'Repuesto_Nota': b.notes,
                                })
                        else:
                            ra_rows.append({
                                'Codigo_Activo': a.code, 'Nombre_Activo': a.name,
                                'Categoria': a.category, 'Marca': a.brand, 'Modelo': a.model,
                                'Serie': a.serial_number, 'Estado': a.status,
                                'Ubicacion': ' / '.join(filter(None, [
                                    a.area.name if a.area else None,
                                    a.line.name if a.line else None,
                                    a.equipment.name if a.equipment else None,
                                ])),
                                'Repuesto_Codigo': None, 'Repuesto_Nombre': None,
                                'Repuesto_Cat': None, 'Repuesto_Cant': None, 'Repuesto_Nota': None,
                            })
                    pd.DataFrame(ra_rows).to_excel(writer, index=False, sheet_name='Activos_BOM')
                except Exception:
                    pass

                # ── 14. OT BITACORA (Log Entries) ──────────────────────────
                try:
                    from models import OTLogEntry
                    log_entries = OTLogEntry.query.order_by(OTLogEntry.id.desc()).all()
                    log_rows = []
                    for e in log_entries:
                        wo = WorkOrder.query.get(e.work_order_id)
                        log_rows.append({
                            'Codigo_OT': wo.code if wo else f'OT-{e.work_order_id}',
                            'Fecha': e.log_date,
                            'Tipo': e.log_type,
                            'Autor': e.author,
                            'Comentario': e.comment,
                            'Creado': e.created_at.isoformat() if e.created_at else None,
                        })
                    pd.DataFrame(log_rows).to_excel(writer, index=False, sheet_name='OT_Bitacora')
                except Exception:
                    pass

            output.seek(0)
            today = dt.date.today().isoformat()
            return send_file(
                output,
                as_attachment=True,
                download_name=f"CMMS_PowerBI_{today}.xlsx",
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            logger.exception("Power BI export error")
            return jsonify({"error": str(e)}), 500

    # ── Power BI JSON Endpoints (real-time) ───────────────────────────────

    @app.route('/api/powerbi/work-orders', methods=['GET'])
    def powerbi_work_orders():
        """All work orders with resolved names for Power BI direct query."""
        from sqlalchemy import text
        rows = db.session.execute(text("""
            SELECT w.id, w.code, w.status, w.maintenance_type, w.failure_mode, w.description,
                   w.scheduled_date, w.real_start_date, w.real_end_date, w.real_duration,
                   w.estimated_duration, w.tech_count, w.caused_downtime, w.downtime_hours,
                   w.source_type, w.execution_comments,
                   a.name as area, l.name as linea, e.name as equipo, e.tag,
                   s.name as sistema, c.name as componente,
                   t.name as tecnico, p.name as proveedor, w.notice_id
            FROM work_orders w
            LEFT JOIN areas a ON w.area_id = a.id
            LEFT JOIN lines l ON w.line_id = l.id
            LEFT JOIN equipments e ON w.equipment_id = e.id
            LEFT JOIN systems s ON w.system_id = s.id
            LEFT JOIN components c ON w.component_id = c.id
            LEFT JOIN technicians t ON CAST(w.technician_id AS INTEGER) = t.id
            LEFT JOIN providers p ON w.provider_id = p.id
            ORDER BY w.id
        """)).fetchall()
        cols = ['id','code','status','maintenance_type','failure_mode','description',
                'scheduled_date','real_start_date','real_end_date','real_duration',
                'estimated_duration','tech_count','caused_downtime','downtime_hours',
                'source_type','execution_comments',
                'area','linea','equipo','tag','sistema','componente','tecnico','proveedor','notice_id']
        db.session.remove()
        return jsonify([dict(zip(cols, r)) for r in rows])

    @app.route('/api/powerbi/notices', methods=['GET'])
    def powerbi_notices():
        """All notices with resolved names."""
        from sqlalchemy import text
        rows = db.session.execute(text("""
            SELECT n.id, n.code, n.status, n.description, n.criticality, n.priority,
                   n.maintenance_type, n.request_date, n.treatment_date, n.planning_date,
                   n.reporter_name, n.reporter_type, n.shift, n.ot_number,
                   a.name as area, l.name as linea, e.name as equipo, e.tag,
                   s.name as sistema, c.name as componente
            FROM maintenance_notices n
            LEFT JOIN areas a ON n.area_id = a.id
            LEFT JOIN lines l ON n.line_id = l.id
            LEFT JOIN equipments e ON n.equipment_id = e.id
            LEFT JOIN systems s ON n.system_id = s.id
            LEFT JOIN components c ON n.component_id = c.id
            ORDER BY n.id
        """)).fetchall()
        cols = ['id','code','status','description','criticality','priority',
                'maintenance_type','request_date','treatment_date','planning_date',
                'reporter_name','reporter_type','shift','ot_number',
                'area','linea','equipo','tag','sistema','componente']
        db.session.remove()
        return jsonify([dict(zip(cols, r)) for r in rows])

    @app.route('/api/powerbi/equipment-tree', methods=['GET'])
    def powerbi_equipment_tree():
        """Full equipment hierarchy for Power BI."""
        from sqlalchemy import text
        rows = db.session.execute(text("""
            SELECT a.name as area, l.name as linea, e.name as equipo, e.tag, e.criticality,
                   s.name as sistema, c.name as componente, c.criticality as comp_criticality
            FROM components c
            JOIN systems s ON c.system_id = s.id
            JOIN equipments e ON s.equipment_id = e.id
            JOIN lines l ON e.line_id = l.id
            JOIN areas a ON l.area_id = a.id
            ORDER BY a.name, l.name, e.name, s.name, c.name
        """)).fetchall()
        cols = ['area','linea','equipo','tag','criticality','sistema','componente','comp_criticality']
        db.session.remove()
        return jsonify([dict(zip(cols, r)) for r in rows])

    @app.route('/api/powerbi/kpis', methods=['GET'])
    def powerbi_kpis():
        """Summary KPIs for Power BI dashboard."""
        from sqlalchemy import text
        try:
            total_ot = db.session.execute(text("SELECT count(*) FROM work_orders")).scalar()
            open_ot = db.session.execute(text("SELECT count(*) FROM work_orders WHERE status != 'Cerrada'")).scalar()
            closed_ot = db.session.execute(text("SELECT count(*) FROM work_orders WHERE status = 'Cerrada'")).scalar()
            corrective = db.session.execute(text("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Correctivo'")).scalar()
            preventive = db.session.execute(text("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Preventivo'")).scalar()
            notices_pending = db.session.execute(text("SELECT count(*) FROM maintenance_notices WHERE status = 'Pendiente'")).scalar()

            lub_red = insp_red = mon_red = 0
            try:
                lub_red = db.session.execute(text("SELECT count(*) FROM lubrication_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                insp_red = db.session.execute(text("SELECT count(*) FROM inspection_routes WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
                mon_red = db.session.execute(text("SELECT count(*) FROM monitoring_points WHERE is_active = true AND semaphore_status = 'ROJO'")).scalar() or 0
            except Exception:
                pass

            total_mt = corrective + preventive
            db.session.remove()
            return jsonify({
                "total_ot": total_ot,
                "open_ot": open_ot,
                "closed_ot": closed_ot,
                "corrective": corrective,
                "preventive": preventive,
                "corrective_pct": round(corrective / total_mt * 100, 1) if total_mt > 0 else 0,
                "preventive_pct": round(preventive / total_mt * 100, 1) if total_mt > 0 else 0,
                "notices_pending": notices_pending,
                "lub_overdue": lub_red,
                "insp_overdue": insp_red,
                "mon_overdue": mon_red,
            })
        except Exception as e:
            db.session.remove()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/powerbi/failure-analysis', methods=['GET'])
    def powerbi_failure_analysis():
        """Failure recurrence data for Power BI."""
        from sqlalchemy import text
        rows = db.session.execute(text("""
            SELECT c.name as componente, s.name as sistema, e.name as equipo, e.tag,
                   l.name as linea, a.name as area,
                   w.failure_mode, w.maintenance_type, w.status,
                   w.real_start_date, w.real_end_date, w.caused_downtime, w.downtime_hours
            FROM work_orders w
            JOIN components c ON w.component_id = c.id
            JOIN systems s ON c.system_id = s.id
            JOIN equipments e ON w.equipment_id = e.id
            JOIN lines l ON e.line_id = l.id
            JOIN areas a ON l.area_id = a.id
            WHERE w.maintenance_type = 'Correctivo'
            ORDER BY w.id DESC
        """)).fetchall()
        cols = ['componente','sistema','equipo','tag','linea','area',
                'failure_mode','maintenance_type','status',
                'real_start_date','real_end_date','caused_downtime','downtime_hours']
        db.session.remove()
        return jsonify([dict(zip(cols, r)) for r in rows])

