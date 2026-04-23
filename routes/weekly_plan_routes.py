"""Programa Nocturno Semanal — preventivos ejecutados por proveedor turno noche.

Flujo:
  1. Jefe de mtto crea un plan para una semana (lunes-domingo).
  2. Auto-planner distribuye puntos preventivos vencidos/próximos en las 4
     áreas × 7 noches, llenando la capacidad horaria (default 2 técnicos × 12 h).
  3. Plan se publica → genera token URL-safe para el proveedor.
  4. Proveedor abre /programa-nocturno/publico/<token> desde su móvil,
     marca ítems como ejecutados con observaciones.
  5. Cada ítem ejecutado crea OT con source_type/source_id → el handler
     _update_source_on_close actualiza last_service_date y next_due_date.

Estimaciones de duración por tipo de tarea (si no vienen explícitas):
  - Lubricación: 0.5 h base + 0.1 h por litro nominal
  - Inspección: 1.0 h base + 0.1 h por ítem activo
  - Monitoreo: 0.5 h base
"""
import datetime as dt
import secrets
from io import BytesIO

from flask import jsonify, request, render_template, send_file


# ── Estimación de duración por tarea ─────────────────────────────────────────

def _estimate_hours(source_type, obj, WorkOrder=None):
    """Estima horas de una tarea preventiva.

    Estrategia:
      1. Si hay ≥2 OTs cerradas del mismo source → promedio de las últimas 3
         (rolling average auto-aprendiente)
      2. Si no hay suficiente histórico → heurística por tipo.
    """
    source_id = getattr(obj, 'id', None)
    if WorkOrder is not None and source_type and source_id:
        try:
            recent = WorkOrder.query.filter(
                WorkOrder.source_type == source_type,
                WorkOrder.source_id == source_id,
                WorkOrder.status == 'Cerrada',
                WorkOrder.real_duration.isnot(None),
                WorkOrder.real_duration > 0,
            ).order_by(WorkOrder.id.desc()).limit(3).all()
            if len(recent) >= 2:
                avg = sum(float(w.real_duration) for w in recent) / len(recent)
                # Caps defensivos: no menor a 0.25h ni mayor a 8h
                return round(max(0.25, min(avg, 8.0)), 2)
        except Exception:
            pass

    # Fallback heurístico (primer preventivo sin historial)
    if source_type == 'lubrication':
        base = 0.5
        qty = getattr(obj, 'quantity_nominal', None) or 0
        return round(base + min(qty * 0.1, 2.0), 2)
    if source_type == 'inspection':
        base = 1.0
        items_count = 0
        if hasattr(obj, 'items') and obj.items:
            items_count = len([i for i in obj.items if i.is_active])
        return round(base + min(items_count * 0.08, 1.5), 2)
    if source_type == 'monitoring':
        return 0.5
    return 1.0


# ── Código e ISO week helpers ────────────────────────────────────────────────

def _iso_week_bounds(date_str):
    """Devuelve (lunes, domingo) de la semana que contiene a date_str."""
    d = dt.date.fromisoformat(date_str)
    monday = d - dt.timedelta(days=d.weekday())
    sunday = monday + dt.timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _generate_plan_code(week_start, WeeklyPlan):
    """PN-YYYY-WW (ISO week)."""
    try:
        d = dt.date.fromisoformat(week_start)
        year, week, _ = d.isocalendar()
        return f"PN-{year}-{week:02d}"
    except Exception:
        return f"PN-{dt.date.today().strftime('%Y-%W')}"


def register_weekly_plan_routes(
    app, db, logger,
    WeeklyPlan, WeeklyPlanItem,
    Area, Line, Equipment, WorkOrder, Provider,
    LubricationPoint, InspectionRoute, MonitoringPoint,
    _calculate_lubrication_schedule, _calculate_monitoring_schedule,
):

    # ── Página web (solo dashboard del jefe) ─────────────────────────────

    @app.route('/programa-nocturno', methods=['GET'])
    def wp_page():
        return render_template('programa_nocturno.html')

    @app.route('/api/preventive-sources', methods=['GET'])
    def wp_list_preventive_sources():
        """Endpoint auxiliar para el selector de ítems manuales.
        Filtros: ?source_type=lubrication|inspection|monitoring&area_id=N
        """
        try:
            from utils.preventive_sources import collect_sources
            src_type = request.args.get('source_type')
            area_id = request.args.get('area_id', type=int)
            sources = collect_sources(
                LubricationPoint, InspectionRoute, MonitoringPoint,
                _calc_lub_schedule=_calculate_lubrication_schedule,
                _calc_mon_schedule=_calculate_monitoring_schedule,
                source_types={src_type} if src_type else None,
                area_ids=[area_id] if area_id else None,
                enrich_names=True,
            )
            return jsonify(sources)
        except Exception as e:
            logger.error(f"list_preventive_sources error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── CRUD de planes ───────────────────────────────────────────────────

    @app.route('/api/weekly-plans', methods=['GET'])
    def wp_list():
        try:
            plans = WeeklyPlan.query.order_by(WeeklyPlan.week_start.desc()).limit(20).all()
            out = []
            for p in plans:
                d = p.to_dict()
                d['item_count'] = len(p.items)
                d['executed_count'] = sum(1 for it in p.items if it.status == 'EJECUTADO')
                d['total_hours'] = round(sum(it.estimated_hours for it in p.items), 2)
                out.append(d)
            return jsonify(out)
        except Exception as e:
            logger.error(f"list_weekly_plans error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans', methods=['POST'])
    def wp_create():
        try:
            data = request.get_json() or {}
            ref_date = data.get('week_start') or dt.date.today().isoformat()
            mon, sun = _iso_week_bounds(ref_date)

            # ¿Ya existe plan para esa semana?
            existing = WeeklyPlan.query.filter_by(week_start=mon).first()
            if existing:
                return jsonify({"error": f"Ya existe un plan para la semana del {mon}", "id": existing.id}), 400

            plan = WeeklyPlan(
                week_start=mon,
                week_end=sun,
                provider_id=data.get('provider_id'),
                tech_count=int(data.get('tech_count', 2)),
                hours_per_night=float(data.get('hours_per_night', 12.0)),
                notes=data.get('notes'),
                created_by=data.get('created_by'),
            )
            db.session.add(plan)
            db.session.flush()
            plan.code = _generate_plan_code(mon, WeeklyPlan)
            db.session.commit()
            return jsonify(plan.to_dict(include_items=True)), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"create_weekly_plan error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans/<int:plan_id>', methods=['GET'])
    def wp_detail(plan_id):
        try:
            p = WeeklyPlan.query.get_or_404(plan_id)
            d = p.to_dict(include_items=True)
            # Agrupar ítems por día × área para vista calendario
            grid = {}
            for it in p.items:
                key = (it.day_of_week, it.area_id)
                grid.setdefault(str(key), []).append(it.to_dict())
            # Horas por día (suma por día_of_week)
            hours_per_day = [0.0] * 7
            for it in p.items:
                if 0 <= it.day_of_week <= 6:
                    hours_per_day[it.day_of_week] += it.estimated_hours or 0
            d['grid'] = grid
            d['hours_per_day'] = [round(h, 2) for h in hours_per_day]
            d['capacity_per_day'] = round(p.tech_count * p.hours_per_night, 2)
            d['executed_count'] = sum(1 for it in p.items if it.status == 'EJECUTADO')
            d['total_hours'] = round(sum(it.estimated_hours for it in p.items), 2)
            return jsonify(d)
        except Exception as e:
            logger.error(f"get_weekly_plan error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans/<int:plan_id>', methods=['PUT'])
    def wp_update(plan_id):
        try:
            p = WeeklyPlan.query.get_or_404(plan_id)
            data = request.get_json() or {}
            for field in ('notes', 'status', 'created_by'):
                if field in data:
                    setattr(p, field, data[field])
            if 'provider_id' in data:
                p.provider_id = int(data['provider_id']) if data['provider_id'] else None
            if 'tech_count' in data:
                p.tech_count = int(data['tech_count'])
            if 'hours_per_night' in data:
                p.hours_per_night = float(data['hours_per_night'])
            db.session.commit()
            return jsonify(p.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.error(f"update_weekly_plan error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans/<int:plan_id>', methods=['DELETE'])
    def wp_delete(plan_id):
        try:
            p = WeeklyPlan.query.get_or_404(plan_id)
            db.session.delete(p)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.error(f"delete_weekly_plan error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans/<int:plan_id>/publish', methods=['POST'])
    def wp_publish(plan_id):
        """Cambia estado a PUBLICADO y genera token público para el proveedor."""
        try:
            p = WeeklyPlan.query.get_or_404(plan_id)
            if not p.public_token:
                p.public_token = secrets.token_urlsafe(32)
            p.status = 'PUBLICADO'
            db.session.commit()
            host = request.host_url.rstrip('/')
            public_url = f"{host}/programa-nocturno/publico/{p.public_token}"
            return jsonify({
                "ok": True,
                "public_token": p.public_token,
                "public_url": public_url,
                "plan": p.to_dict(),
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"publish_weekly_plan error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Auto-planner ─────────────────────────────────────────────────────

    @app.route('/api/weekly-plans/<int:plan_id>/auto-plan', methods=['POST'])
    def wp_auto_plan(plan_id):
        """Distribuye puntos preventivos en las 4 áreas × 7 noches llenando la capacidad.

        Algoritmo:
        - Recolecta puntos (todos o filtrados) usando utils.preventive_sources
        - Ordena por prioridad: ROJO → AMARILLO → VERDE, next_due_date asc
        - Para cada punto: elige el (día, área) con menos horas ocupadas dentro del área del punto
        - Llena hasta capacity_per_day por día, máximo
        """
        try:
            from utils.preventive_sources import collect_sources
            p = WeeklyPlan.query.get_or_404(plan_id)
            data = request.get_json() or {}
            clear_existing = bool(data.get('clear_existing', True))

            # Limpiar ítems PLANIFICADO previos si se pide
            if clear_existing:
                for it in list(p.items):
                    if it.status == 'PLANIFICADO':
                        db.session.delete(it)
                db.session.flush()

            capacity_per_day = p.tech_count * p.hours_per_night  # h-h por noche

            # Mapas para enrichment y filtrado
            areas_all = Area.query.all()
            line_map = {l.id: l for l in Line.query.all()}
            equip_map = {e.id: e for e in Equipment.query.all()}
            area_map = {a.id: a for a in areas_all}

            # Puntos ya en otras OTs abiertas o ya incluidos en este plan: no duplicar
            open_ots = WorkOrder.query.filter(
                WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso']),
                WorkOrder.source_type.isnot(None),
            ).all()
            excluded = {(o.source_type, o.source_id) for o in open_ots if o.source_id}
            for it in p.items:
                if it.source_type and it.source_id:
                    excluded.add((it.source_type, it.source_id))

            # Recolectar (todos los activos, no solo vencidos — queremos llenar capacidad)
            sources = collect_sources(
                LubricationPoint, InspectionRoute, MonitoringPoint,
                _calc_lub_schedule=_calculate_lubrication_schedule,
                _calc_mon_schedule=_calculate_monitoring_schedule,
                only_overdue=False,
                exclude=excluded,
                enrich_names=True,
                area_map=area_map, line_map=line_map, equip_map=equip_map,
            )

            # Estado de carga por día y área
            load = {d: {a.id: 0.0 for a in areas_all} for d in range(7)}
            day_totals = [0.0] * 7
            # Pre-cargar ítems EJECUTADO que queden (no se borran)
            for it in p.items:
                if 0 <= it.day_of_week <= 6 and it.area_id in load[it.day_of_week]:
                    load[it.day_of_week][it.area_id] += it.estimated_hours or 0
                    day_totals[it.day_of_week] += it.estimated_hours or 0

            # Helper: resolver objeto origen para calcular horas
            def _get_source_obj(src):
                t, sid = src['source_type'], src['source_id']
                if t == 'lubrication':
                    return LubricationPoint.query.get(sid)
                if t == 'inspection':
                    return InspectionRoute.query.get(sid)
                if t == 'monitoring':
                    return MonitoringPoint.query.get(sid)
                return None

            # Distribuir
            placed = 0
            for src in sources:
                if not src.get('area_id'):
                    continue
                aid = src['area_id']
                # Elegir el día con menos carga dentro del área
                candidate_days = list(range(7))
                # Ordenar por (horas_del_dia_en_el_area, carga_total_del_dia)
                candidate_days.sort(key=lambda d: (load[d].get(aid, 0), day_totals[d]))

                obj = _get_source_obj(src)
                hours = _estimate_hours(src['source_type'], obj, WorkOrder=WorkOrder) if obj else 1.0

                chosen_day = None
                for d in candidate_days:
                    if day_totals[d] + hours <= capacity_per_day:
                        chosen_day = d
                        break
                if chosen_day is None:
                    # Ya no entra ni forzando. Detener.
                    if min(day_totals) >= capacity_per_day:
                        break
                    # Si todavía hay huecos en otros días pero no en el área del punto,
                    # lo colocamos igual en el día de menor carga total (permite pasar del día ideal)
                    chosen_day = candidate_days[0]
                    if day_totals[chosen_day] + hours > capacity_per_day:
                        continue  # ya no hay capacidad real

                # Crear ítem
                order = sum(1 for it in p.items if it.day_of_week == chosen_day and it.area_id == aid)
                item = WeeklyPlanItem(
                    plan_id=p.id,
                    day_of_week=chosen_day,
                    area_id=aid,
                    order_index=order,
                    source_type=src['source_type'],
                    source_id=src['source_id'],
                    source_code=src.get('code', ''),
                    source_name=src.get('name', ''),
                    equipment_tag=src.get('equipment_tag', ''),
                    description=src.get('description', ''),
                    estimated_hours=hours,
                    status='PLANIFICADO',
                )
                db.session.add(item)
                p.items.append(item)
                load[chosen_day][aid] = load[chosen_day].get(aid, 0) + hours
                day_totals[chosen_day] += hours
                placed += 1

                # Si todos los días están llenos, detener
                if all(dt_h >= capacity_per_day for dt_h in day_totals):
                    break

            db.session.commit()
            return jsonify({
                "ok": True,
                "items_placed": placed,
                "hours_per_day": [round(x, 2) for x in day_totals],
                "capacity_per_day": capacity_per_day,
                "fill_pct": [round((x / capacity_per_day * 100) if capacity_per_day else 0, 1) for x in day_totals],
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"auto_plan_week error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── CRUD de ítems ────────────────────────────────────────────────────

    @app.route('/api/weekly-plans/<int:plan_id>/items', methods=['POST'])
    def wp_item_add(plan_id):
        """Agregar ítem manual al plan (sin pasar por auto-planner)."""
        try:
            p = WeeklyPlan.query.get_or_404(plan_id)
            data = request.get_json() or {}
            item = WeeklyPlanItem(
                plan_id=p.id,
                day_of_week=int(data.get('day_of_week', 0)),
                area_id=data.get('area_id'),
                source_type=data.get('source_type'),
                source_id=data.get('source_id'),
                source_code=data.get('source_code'),
                source_name=data.get('source_name'),
                equipment_tag=data.get('equipment_tag'),
                description=data.get('description') or '',
                estimated_hours=float(data.get('estimated_hours', 1.0)),
                order_index=int(data.get('order_index', 99)),
            )
            db.session.add(item)
            db.session.commit()
            return jsonify(item.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"add_plan_item error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans/<int:plan_id>/items/<int:item_id>', methods=['PUT'])
    def wp_item_update(plan_id, item_id):
        """Actualizar ítem (usado para drag & drop y edición manual)."""
        try:
            item = WeeklyPlanItem.query.filter_by(id=item_id, plan_id=plan_id).first_or_404()
            data = request.get_json() or {}
            if 'day_of_week' in data:
                item.day_of_week = int(data['day_of_week'])
            if 'area_id' in data:
                item.area_id = int(data['area_id']) if data['area_id'] else None
            if 'order_index' in data:
                item.order_index = int(data['order_index'])
            if 'estimated_hours' in data:
                item.estimated_hours = float(data['estimated_hours'])
            if 'description' in data:
                item.description = data['description']
            db.session.commit()
            return jsonify(item.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.error(f"update_plan_item error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/weekly-plans/<int:plan_id>/items/<int:item_id>', methods=['DELETE'])
    def wp_item_delete(plan_id, item_id):
        try:
            item = WeeklyPlanItem.query.filter_by(id=item_id, plan_id=plan_id).first_or_404()
            db.session.delete(item)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.error(f"delete_plan_item error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Ejecución: crea OT vinculada + actualiza source ──────────────────

    def _execute_item(item, plan, executed_by=None, notes=None):
        """Marca ítem como EJECUTADO y crea OT cerrada vinculada al source."""
        from models import MaintenanceNotice
        today = dt.datetime.now().strftime('%Y-%m-%d')

        # Resolver jerarquía
        area_id = item.area_id
        line_id = None
        equipment_id = None
        system_id = None
        component_id = None
        if item.source_type == 'lubrication' and item.source_id:
            pt = LubricationPoint.query.get(item.source_id)
            if pt:
                area_id = area_id or pt.area_id
                line_id = pt.line_id
                equipment_id = pt.equipment_id
                system_id = pt.system_id
                component_id = pt.component_id
        elif item.source_type == 'inspection' and item.source_id:
            rt = InspectionRoute.query.get(item.source_id)
            if rt:
                area_id = area_id or rt.area_id
                line_id = rt.line_id
                equipment_id = rt.equipment_id
        elif item.source_type == 'monitoring' and item.source_id:
            pt = MonitoringPoint.query.get(item.source_id)
            if pt:
                area_id = area_id or pt.area_id
                line_id = pt.line_id
                equipment_id = pt.equipment_id
                system_id = pt.system_id
                component_id = pt.component_id

        # Crear OT cerrada directamente (preventivo ejecutado por proveedor)
        wo = WorkOrder(
            description=item.description or item.source_name or '(preventivo)',
            maintenance_type='Preventivo',
            status='Cerrada',
            real_start_date=today,
            real_end_date=today,
            real_duration=item.estimated_hours,
            estimated_duration=item.estimated_hours,
            tech_count=plan.tech_count,
            area_id=area_id,
            line_id=line_id,
            equipment_id=equipment_id,
            system_id=system_id,
            component_id=component_id,
            source_type=item.source_type,
            source_id=item.source_id,
            execution_comments=notes or '',
            provider_id=plan.provider_id,
        )
        db.session.add(wo)
        db.session.flush()
        wo.code = f"OT-{wo.id:04d}"

        # Actualizar source (reutiliza misma lógica que work_orders_routes)
        try:
            if item.source_type == 'lubrication' and item.source_id:
                pt = LubricationPoint.query.get(item.source_id)
                if pt:
                    pt.last_service_date = today
                    if _calculate_lubrication_schedule:
                        nd, sem = _calculate_lubrication_schedule(today, pt.frequency_days, pt.warning_days)
                        pt.next_due_date = nd
                        pt.semaphore_status = sem
            elif item.source_type == 'inspection' and item.source_id:
                rt = InspectionRoute.query.get(item.source_id)
                if rt:
                    rt.last_execution_date = today
                    if _calculate_lubrication_schedule:
                        nd, sem = _calculate_lubrication_schedule(today, rt.frequency_days, rt.warning_days)
                        rt.next_due_date = nd
                        rt.semaphore_status = sem
            elif item.source_type == 'monitoring' and item.source_id:
                pt = MonitoringPoint.query.get(item.source_id)
                if pt:
                    pt.last_measurement_date = today
                    if _calculate_monitoring_schedule:
                        nd, sem = _calculate_monitoring_schedule(today, pt.frequency_days, pt.warning_days)
                        pt.next_due_date = nd
                        pt.semaphore_status = sem
        except Exception as upd_err:
            logger.warning(f"No se pudo actualizar source: {upd_err}")

        # Marcar ítem
        item.status = 'EJECUTADO'
        item.executed_at = today
        item.executed_by = executed_by or 'proveedor'
        item.execution_notes = notes or ''
        item.work_order_id = wo.id
        return wo

    @app.route('/api/weekly-plans/<int:plan_id>/items/<int:item_id>/execute', methods=['POST'])
    def wp_item_execute(plan_id, item_id):
        """Marcar ítem como ejecutado → crea OT y actualiza el punto origen."""
        try:
            item = WeeklyPlanItem.query.filter_by(id=item_id, plan_id=plan_id).first_or_404()
            plan = WeeklyPlan.query.get(plan_id)
            data = request.get_json() or {}
            if item.status == 'EJECUTADO':
                return jsonify({"error": "El ítem ya fue ejecutado", "work_order_id": item.work_order_id}), 400
            wo = _execute_item(item, plan,
                               executed_by=data.get('executed_by'),
                               notes=data.get('notes'))
            db.session.commit()
            return jsonify({
                "ok": True,
                "item": item.to_dict(),
                "work_order_code": wo.code,
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"execute_plan_item error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Vista pública tokenizada (para el proveedor, sin login) ──────────

    @app.route('/programa-nocturno/publico/<token>', methods=['GET'])
    def wp_public_view(token):
        p = WeeklyPlan.query.filter_by(public_token=token).first()
        if not p:
            return "Enlace inválido o plan cerrado.", 404
        return render_template('programa_nocturno_publico.html', token=token)

    @app.route('/api/public/weekly-plans/<token>', methods=['GET'])
    def wp_public_data(token):
        """API pública: datos del plan por token (sin login)."""
        try:
            p = WeeklyPlan.query.filter_by(public_token=token).first()
            if not p:
                return jsonify({"error": "Token inválido"}), 404
            d = p.to_dict(include_items=True)
            grid = {}
            for it in p.items:
                key = str((it.day_of_week, it.area_id))
                grid.setdefault(key, []).append(it.to_dict())
            d['grid'] = grid
            return jsonify(d)
        except Exception as e:
            logger.error(f"public_weekly_plan_data error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/public/weekly-plans/<token>/items/<int:item_id>/execute', methods=['POST'])
    def wp_public_execute(token, item_id):
        """Proveedor marca ítem ejecutado desde el link público."""
        try:
            p = WeeklyPlan.query.filter_by(public_token=token).first()
            if not p:
                return jsonify({"error": "Token inválido"}), 404
            item = WeeklyPlanItem.query.filter_by(id=item_id, plan_id=p.id).first_or_404()
            if item.status == 'EJECUTADO':
                return jsonify({"ok": True, "already_executed": True})
            data = request.get_json() or {}
            wo = _execute_item(item, p,
                               executed_by=data.get('executed_by') or 'proveedor',
                               notes=data.get('notes'))
            db.session.commit()
            return jsonify({
                "ok": True,
                "item": item.to_dict(),
                "work_order_code": wo.code,
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"public_execute_item error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Export PDF ───────────────────────────────────────────────────────

    @app.route('/api/weekly-plans/<int:plan_id>/report/pdf', methods=['GET'])
    def wp_export_pdf(plan_id):
        """PDF con 7 secciones (una por noche), listo para entregar al proveedor."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
            )

            p = WeeklyPlan.query.get_or_404(plan_id)

            bio = BytesIO()
            doc = SimpleDocTemplate(
                bio, pagesize=A4,
                leftMargin=12 * mm, rightMargin=12 * mm,
                topMargin=12 * mm, bottomMargin=12 * mm,
                title=f"Programa Nocturno {p.code or p.id}",
            )
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=16, textColor=colors.HexColor('#0a84ff'), alignment=1)
            subtitle_style = ParagraphStyle('s', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#5a6570'), alignment=1)
            section_style = ParagraphStyle('sec', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#BF5AF2'), spaceBefore=6)
            cell_style = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)
            cell_bold = ParagraphStyle('cellb', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')

            story = []
            story.append(Paragraph("PROGRAMA NOCTURNO SEMANAL", title_style))
            story.append(Paragraph(
                f"<b>{p.code or ''}</b> · Semana {p.week_start} al {p.week_end}"
                f" · Proveedor: {p.provider.name if p.provider else 'Por asignar'}"
                f" · Capacidad: {p.tech_count} técnicos × {p.hours_per_night}h = {p.tech_count * p.hours_per_night}h/noche",
                subtitle_style))
            story.append(Spacer(1, 5 * mm))

            # Una sección por día con ítems agrupados por área
            day_names = ['LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES', 'SÁBADO', 'DOMINGO']
            capacity = p.tech_count * p.hours_per_night

            for d_idx in range(7):
                day_items = [it for it in p.items if it.day_of_week == d_idx]
                if not day_items:
                    continue
                day_hours = sum(it.estimated_hours for it in day_items)
                day_date = dt.date.fromisoformat(p.week_start) + dt.timedelta(days=d_idx)
                story.append(Paragraph(
                    f"🌙 {day_names[d_idx]} — {day_date.isoformat()} · "
                    f"{len(day_items)} tareas · {day_hours:.1f}h / {capacity:.0f}h",
                    section_style))

                # Tabla
                rows = [['#', 'Área', 'Tipo', 'Código', 'Descripción', 'Hrs', 'Check']]
                day_items.sort(key=lambda x: (x.area.name if x.area else '', x.order_index))
                for i, it in enumerate(day_items, 1):
                    rows.append([
                        str(i),
                        Paragraph((it.area.name if it.area else '-'), cell_style),
                        (it.source_type or '').upper(),
                        Paragraph(it.source_code or '-', cell_bold),
                        Paragraph((it.description or it.source_name or '-')[:200], cell_style),
                        f"{it.estimated_hours}h",
                        '[  ]',
                    ])
                tbl = Table(
                    rows,
                    colWidths=[8 * mm, 28 * mm, 22 * mm, 25 * mm, 80 * mm, 14 * mm, 12 * mm],
                    repeatRows=1,
                )
                tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1b1d3a')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8),
                    ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),
                    ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('PADDING', (0, 0), (-1, -1), 3),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f7fa')]),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 4 * mm))

            if p.notes:
                story.append(Paragraph("NOTAS", section_style))
                story.append(Paragraph(p.notes.replace('\n', '<br/>'), cell_style))

            doc.build(story)
            bio.seek(0)
            filename = f"Programa_Nocturno_{p.code or p.id}.pdf"
            return send_file(
                bio, as_attachment=True, download_name=filename,
                mimetype='application/pdf',
            )
        except Exception as e:
            logger.error(f"export_weekly_plan_pdf error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500
