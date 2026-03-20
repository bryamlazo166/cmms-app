from collections import defaultdict
import datetime as dt

from flask import jsonify, request


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
    OTMaterial,
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
            
            # Helper to get all OTs for a hierarchy node
            def get_ots_for_node(node, level):
                # Traverse down to find IDs
                equip_ids = []
                
                if level == 'equipment':
                    equip_ids = [node.id]
                elif level == 'line':
                    equip_ids = [e.id for e in Equipment.query.filter_by(line_id=node.id).all()]
                elif level == 'area':
                    lines = Line.query.filter_by(area_id=node.id).all()
                    for l in lines:
                        equip_ids.extend([e.id for e in Equipment.query.filter_by(line_id=l.id).all()])
                
                if not equip_ids: return []

                # Find OTs linked to these equipments (or their components/systems)
                # Simplest approach: Query OTs directly linked to Equipment OR System OR Component that belongs to these equipments
                # But DB model links OT directly to Equipment/System/Component.
                # We need to aggregating.
                
                # Let's trust the OT's direct links for now. 
                # Ideally, we should join tables. But iterative python filtering is safer for now if dataset is small.
                
                # Optimized: Query OTs where equipment_id IN list OR system.equipment_id IN list OR component.system.equipment_id IN list
                # This is complex in ORM without joins.
                # Let's fetch all closed OTs and filter in python (Performance caveat: Bad for large DB, okay for prototype)
                
                all_ots = WorkOrder.query.filter_by(status='Cerrada').all()
                relevant_ots = []
                
                for ot in all_ots:
                    # Check date range
                    if start_date and ot.real_end_date and ot.real_end_date < start_date: continue
                    if end_date and ot.real_end_date and ot.real_end_date > end_date: continue
                    
                    # Check hierarchy
                    e_id = -1
                    if ot.equipment_id: e_id = ot.equipment_id
                    elif ot.system_id: 
                        s = System.query.get(ot.system_id)
                        if s: e_id = s.equipment_id
                    elif ot.component_id:
                        c = Component.query.get(ot.component_id)
                        if c: 
                            s = System.query.get(c.system_id)
                            if s: e_id = s.equipment_id
                    
                    if e_id in equip_ids:
                        relevant_ots.append(ot)
                        
                return relevant_ots

            for g in groups:
                ots = get_ots_for_node(g['object'], level)
                
                # 1. Cost Calculation
                total_cost = 0
                for ot in ots:
                    for m in ot.assigned_materials:
                        if m.item_type == 'warehouse':
                            item = WarehouseItem.query.get(m.item_id)
                            cost = (item.unit_cost or 0) * m.quantity
                            total_cost += cost
                
                # 2. Reliability Calculation
                failures = [ot for ot in ots if ot.maintenance_type == 'Correctivo']
                n_failures = len(failures)
                t_down = sum([(ot.real_duration or 0) for ot in failures])
                
                # Total Time window (hours)
                # Approximate if dates not set: 30 days
                t_total = 720 
                if start_date and end_date:
                    try:
                        d1 = datetime.datetime.fromisoformat(start_date)
                        d2 = datetime.datetime.fromisoformat(end_date)
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
            warehouse_items = WarehouseItem.query.all()

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
                        name = Area.query.get(area_ref).name if area_ref else "Sin area"
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


