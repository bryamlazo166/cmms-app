from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file


def register_work_orders_routes(
    app,
    db,
    logger,
    OTPersonnel,
    OTMaterial,
    WarehouseItem,
    WarehouseMovement,
    Tool,
    WorkOrder,
    MaintenanceNotice,
    Area,
    Line,
    Equipment,
    System,
    Component,
    Provider,
    Technician,
    PurchaseRequest,
    delete_entry,
    LubricationPoint=None,
    InspectionRoute=None,
    MonitoringPoint=None,
    OTLogEntry=None,
    _calculate_lubrication_schedule=None,
    _calculate_monitoring_schedule=None,
):

    def _update_source_on_close(source_type, source_id, close_date):
        """Update the source preventive point when its OT is closed."""
        try:
            # Parse close_date to just date string YYYY-MM-DD
            if 'T' in str(close_date):
                close_date = str(close_date).split('T')[0]

            if source_type == 'lubrication' and LubricationPoint:
                point = LubricationPoint.query.get(source_id)
                if point:
                    point.last_service_date = close_date
                    if _calculate_lubrication_schedule:
                        nd, sem = _calculate_lubrication_schedule(
                            close_date, point.frequency_days, point.warning_days)
                        point.next_due_date = nd
                        point.semaphore_status = sem
                    logger.info(f"Source LUB-{source_id} updated: last_service={close_date}")

            elif source_type == 'inspection' and InspectionRoute:
                route = InspectionRoute.query.get(source_id)
                if route:
                    route.last_execution_date = close_date
                    if _calculate_lubrication_schedule:
                        nd, sem = _calculate_lubrication_schedule(
                            close_date, route.frequency_days, route.warning_days)
                        route.next_due_date = nd
                        route.semaphore_status = sem
                    logger.info(f"Source INSP-{source_id} updated: last_execution={close_date}")

            elif source_type == 'monitoring' and MonitoringPoint:
                point = MonitoringPoint.query.get(source_id)
                if point:
                    point.last_measurement_date = close_date
                    if _calculate_monitoring_schedule:
                        nd, sem = _calculate_monitoring_schedule(
                            close_date, point.frequency_days, point.warning_days)
                        point.next_due_date = nd
                        point.semaphore_status = sem
                    logger.info(f"Source MON-{source_id} updated: last_measurement={close_date}")
        except Exception as e:
            logger.error(f"Error updating source {source_type}/{source_id}: {e}")

    # ── Generate Preventive OTs from overdue points ───────────────────────

    @app.route('/api/generate-preventive-ots', methods=['POST'])
    def generate_preventive_ots():
        """Scan all overdue lub/insp/mon points and create preventive OTs."""
        try:
            created = []
            skipped = 0

            sources = []

            # Collect overdue lubrication points
            if LubricationPoint:
                for p in LubricationPoint.query.filter_by(is_active=True).all():
                    if _calculate_lubrication_schedule:
                        _, sem = _calculate_lubrication_schedule(
                            p.last_service_date, p.frequency_days, p.warning_days)
                    else:
                        sem = p.semaphore_status
                    if sem in ('ROJO', 'AMARILLO'):
                        lub_desc = f"[PREVENTIVO - LUBRICACION] {p.code} {p.name}"
                        if p.lubricant_name:
                            lub_desc += f"\nLubricante: {p.lubricant_name}"
                        if p.quantity_nominal:
                            lub_desc += f" | Cantidad: {p.quantity_nominal} {p.quantity_unit or 'L'}"
                        lub_desc += f"\nFrecuencia: cada {p.frequency_days} dias"
                        if p.last_service_date:
                            lub_desc += f" | Ultimo servicio: {p.last_service_date}"
                        sources.append({
                            'source_type': 'lubrication',
                            'source_id': p.id,
                            'source_code': p.code,
                            'source_name': p.name,
                            'semaphore': sem,
                            'equipment_id': p.equipment_id,
                            'area_id': p.area_id,
                            'line_id': p.line_id,
                            'system_id': p.system_id,
                            'component_id': p.component_id,
                            'description': lub_desc,
                        })

            # Collect overdue inspection routes
            if InspectionRoute:
                for r in InspectionRoute.query.filter_by(is_active=True).all():
                    if _calculate_lubrication_schedule:
                        _, sem = _calculate_lubrication_schedule(
                            r.last_execution_date, r.frequency_days, r.warning_days)
                    else:
                        sem = r.semaphore_status
                    if sem in ('ROJO', 'AMARILLO'):
                        # Build item list for description
                        item_list = ""
                        if hasattr(r, 'items') and r.items:
                            active_items = [i for i in r.items if i.is_active]
                            if active_items:
                                item_list = "\nChecklist: " + " | ".join(
                                    f"{i.description}{' ('+i.unit+')' if i.unit else ''}"
                                    for i in active_items[:8]
                                )
                        insp_desc = f"[PREVENTIVO - INSPECCION] {r.code} {r.name}"
                        insp_desc += f"\nFrecuencia: cada {r.frequency_days} dias"
                        if r.last_execution_date:
                            insp_desc += f" | Ultima ejecucion: {r.last_execution_date}"
                        insp_desc += item_list
                        sources.append({
                            'source_type': 'inspection',
                            'source_id': r.id,
                            'source_code': r.code,
                            'source_name': r.name,
                            'semaphore': sem,
                            'equipment_id': r.equipment_id,
                            'area_id': r.area_id,
                            'line_id': r.line_id,
                            'system_id': None,
                            'component_id': None,
                            'description': insp_desc,
                        })

            # Collect overdue monitoring points
            if MonitoringPoint and _calculate_monitoring_schedule:
                for p in MonitoringPoint.query.filter_by(is_active=True).all():
                    _, sem = _calculate_monitoring_schedule(
                        p.last_measurement_date, p.frequency_days, p.warning_days)
                    if sem in ('ROJO', 'AMARILLO'):
                        mon_desc = f"[PREVENTIVO - MONITOREO] {p.code} {p.name}"
                        mon_desc += f"\nTipo: {p.measurement_type or 'VIBRACION'}"
                        if p.axis:
                            mon_desc += f" Eje: {p.axis}"
                        mon_desc += f" | Unidad: {p.unit or 'mm/s'}"
                        if p.normal_min is not None or p.normal_max is not None:
                            mon_desc += f"\nRango normal: {p.normal_min or '-'} a {p.normal_max or '-'} {p.unit or ''}"
                        if p.alarm_min is not None or p.alarm_max is not None:
                            mon_desc += f" | Alarma: {p.alarm_min or '-'} a {p.alarm_max or '-'}"
                        mon_desc += f"\nFrecuencia: cada {p.frequency_days} dias"
                        if p.last_measurement_date:
                            mon_desc += f" | Ultima medicion: {p.last_measurement_date}"
                        sources.append({
                            'source_type': 'monitoring',
                            'source_id': p.id,
                            'source_code': p.code,
                            'source_name': p.name,
                            'semaphore': sem,
                            'equipment_id': p.equipment_id,
                            'area_id': p.area_id,
                            'line_id': p.line_id,
                            'system_id': p.system_id,
                            'component_id': p.component_id,
                            'description': mon_desc,
                        })

            # Create AVISOS (not OTs) for sources that don't already have an open aviso/OT
            for src in sources:
                # Check for existing open aviso with same source
                existing_notice = MaintenanceNotice.query.filter(
                    MaintenanceNotice.source_type == src['source_type'],
                    MaintenanceNotice.source_id == src['source_id'],
                    MaintenanceNotice.status.in_(['Pendiente', 'En Tratamiento', 'En Progreso', 'Programado']),
                ).first()
                if existing_notice:
                    skipped += 1
                    continue

                # Also check for existing open OT with same source
                existing_ot = WorkOrder.query.filter(
                    WorkOrder.source_type == src['source_type'],
                    WorkOrder.source_id == src['source_id'],
                    WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso']),
                ).first()
                if existing_ot:
                    skipped += 1
                    continue

                today = datetime.now().strftime('%Y-%m-%d')

                # Auto-resolve hierarchy from equipment if missing
                eq_id = src['equipment_id']
                ln_id = src['line_id']
                ar_id = src['area_id']
                if eq_id and not ln_id:
                    eq = Equipment.query.get(eq_id)
                    if eq:
                        ln_id = eq.line_id
                if ln_id and not ar_id:
                    ln = Line.query.get(ln_id)
                    if ln:
                        ar_id = ln.area_id

                notice = MaintenanceNotice(
                    reporter_name='Sistema CMMS',
                    reporter_type='MANTENIMIENTO',
                    description=src['description'],
                    maintenance_type='Preventivo',
                    priority='Media',
                    status='Pendiente',
                    request_date=today,
                    area_id=ar_id,
                    line_id=ln_id,
                    equipment_id=eq_id,
                    system_id=src['system_id'],
                    component_id=src['component_id'],
                    source_type=src['source_type'],
                    source_id=src['source_id'],
                )
                db.session.add(notice)
                db.session.flush()
                notice.code = f"AV-{notice.id:04d}"
                created.append({
                    'code': notice.code,
                    'source': f"{src['source_code']} {src['source_name']}",
                    'type': src['source_type'],
                    'semaphore': src['semaphore'],
                })

            db.session.commit()
            return jsonify({
                'created': len(created),
                'skipped': skipped,
                'items': created,
                'message': f'{len(created)} avisos preventivos generados. Revisa el modulo de Avisos para crear OTs.'
            })
        except Exception as e:
            db.session.rollback()
            logger.exception("Generate preventive notices error")
            return jsonify({"error": str(e)}), 500

    # ── OT Activity Log (Bitacora) ───────────────────────────────────────

    @app.route('/api/work_orders/<int:ot_id>/log', methods=['GET', 'POST'])
    def handle_ot_log(ot_id):
        if not OTLogEntry:
            return jsonify([])

        if request.method == 'POST':
            try:
                data = request.json or {}
                comment = (data.get('comment') or '').strip()
                if not comment:
                    return jsonify({"error": "Comentario es obligatorio."}), 400

                from flask_login import current_user
                entry = OTLogEntry(
                    work_order_id=ot_id,
                    log_date=data.get('log_date') or datetime.now().strftime('%Y-%m-%d'),
                    log_type=(data.get('log_type') or 'NOTA').upper(),
                    author=data.get('author') or (current_user.full_name or current_user.username if hasattr(current_user, 'username') else None),
                    comment=comment,
                )
                db.session.add(entry)
                db.session.commit()
                return jsonify(entry.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        entries = OTLogEntry.query.filter_by(work_order_id=ot_id) \
            .order_by(OTLogEntry.log_date.desc(), OTLogEntry.id.desc()).all()
        return jsonify([e.to_dict() for e in entries])

    @app.route('/api/work_orders/<int:ot_id>/log/<int:log_id>', methods=['DELETE'])
    def delete_ot_log(ot_id, log_id):
        if not OTLogEntry:
            return jsonify({"error": "No disponible"}), 500
        entry = OTLogEntry.query.get_or_404(log_id)
        db.session.delete(entry)
        db.session.commit()
        return jsonify({"ok": True})

    # ── OT Report Tracking ─────────────────────────────────────────────────

    @app.route('/api/work_orders/<int:ot_id>/report', methods=['PUT'])
    def update_ot_report(ot_id):
        try:
            wo = WorkOrder.query.get_or_404(ot_id)
            data = request.json or {}
            if 'report_required' in data:
                wo.report_required = bool(data['report_required'])
            if 'report_status' in data:
                wo.report_status = data['report_status']
            if 'report_due_date' in data:
                wo.report_due_date = data['report_due_date'] or None
            if 'report_received_date' in data:
                wo.report_received_date = data['report_received_date'] or None
            db.session.commit()
            return jsonify(wo.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/pending-reports', methods=['GET'])
    def get_pending_reports():
        """List OTs that require a report but haven't received one."""
        try:
            ots = WorkOrder.query.filter(
                WorkOrder.report_required == True,
                db.or_(WorkOrder.report_status == None, WorkOrder.report_status == 'PENDIENTE')
            ).order_by(WorkOrder.id.desc()).all()

            results = []
            for wo in ots:
                eq = Equipment.query.get(wo.equipment_id) if wo.equipment_id else None
                prov = Provider.query.get(wo.provider_id) if wo.provider_id else None
                results.append({
                    'id': wo.id,
                    'code': wo.code,
                    'description': wo.description,
                    'equipment': f"{eq.tag or ''} {eq.name}".strip() if eq else '-',
                    'provider': prov.name if prov else '-',
                    'status': wo.status,
                    'scheduled_date': wo.scheduled_date,
                    'report_due_date': wo.report_due_date,
                    'days_pending': None,
                })
                if wo.report_due_date:
                    try:
                        due = datetime.strptime(wo.report_due_date, '%Y-%m-%d').date()
                        results[-1]['days_pending'] = (datetime.now().date() - due).days
                    except Exception:
                        pass
            return jsonify(results)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- OT PERSONNEL ENDPOINTS ---
    @app.route('/api/work_orders/<int:ot_id>/personnel', methods=['GET', 'POST'])
    def handle_ot_personnel(ot_id):
        if request.method == 'POST':
            try:
                data = request.json

                # Handle array format: { personnel: [{...}, {...}] }
                if 'personnel' in data:
                    personnel_list = data['personnel']
                    logger.info(f"Processing personnel list: {len(personnel_list)} items")

                    # Clear existing personnel for this OT
                    OTPersonnel.query.filter_by(work_order_id=ot_id).delete()

                    # Add new personnel
                    for p in personnel_list:
                        # Ensure technician_id is properly converted to int or None
                        tech_id = p.get('technician_id')
                        try:
                            if tech_id is not None:
                                tech_id = int(tech_id)
                        except (ValueError, TypeError):
                            tech_id = None

                        # Ensure hours is float
                        try:
                            h_val = p.get('hours', p.get('hours_assigned', 8))
                            hours = float(h_val) if h_val is not None else 8.0
                        except Exception:
                            hours = 8.0

                        person = OTPersonnel(
                            work_order_id=ot_id,
                            technician_id=tech_id,
                            specialty=p.get('specialty') or None,
                            hours_assigned=hours,
                        )
                        db.session.add(person)

                    db.session.commit()
                    return jsonify({"message": f"Saved {len(personnel_list)} personnel"}), 201

                # Handle single object format (legacy)
                data['work_order_id'] = ot_id
                if 'hours' in data:
                    data['hours_assigned'] = data.pop('hours')

                # Remove keys that might cause issues if they sneaked in
                data.pop('personnel', None)

                personnel = OTPersonnel(**data)
                db.session.add(personnel)
                db.session.commit()
                return jsonify(personnel.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                import traceback

                error_details = traceback.format_exc()
                logger.error(f"Error saving personnel: {e}\n{error_details}")
                return jsonify({"error": str(e), "details": error_details}), 500

        # GET - return personnel for this OT
        try:
            personnel = OTPersonnel.query.filter_by(work_order_id=ot_id).all()
            return jsonify([p.to_dict() for p in personnel])
        except Exception as e:
            import traceback

            logger.error(f"Error loading personnel for OT {ot_id}: {e}\n{traceback.format_exc()}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/work_orders/<int:ot_id>/personnel/<int:id>', methods=['PUT', 'DELETE'])
    def handle_ot_personnel_id(ot_id, id):
        personnel = OTPersonnel.query.get_or_404(id)

        if request.method == 'PUT':
            data = request.json
            for key, value in data.items():
                if hasattr(personnel, key):
                    setattr(personnel, key, value)
            db.session.commit()
            return jsonify(personnel.to_dict())

        # DELETE
        db.session.delete(personnel)
        db.session.commit()
        return jsonify({"message": "Personnel removed"})

    # --- OT MATERIALS ENDPOINTS ---
    @app.route('/api/work_orders/<int:ot_id>/materials', methods=['GET', 'POST'])
    def handle_ot_materials(ot_id):
        if request.method == 'POST':
            try:
                data = request.json
                item_type = data.get('item_type', 'free')
                subtype   = data.get('subtype', 'repuesto')
                item_id   = data.get('item_id')
                try:
                    qty = int(data.get('quantity', 1))
                    if qty <= 0:
                        raise ValueError
                except Exception:
                    return jsonify({"error": "Quantity must be a positive integer"}), 400

                # Inventory Logic — only for catalog items
                if item_type == 'warehouse' and item_id:
                    item = WarehouseItem.query.get(item_id)
                    if not item:
                        return jsonify({"error": "Item not found"}), 404
                    if item.stock < qty:
                        return jsonify({"error": f"Stock insuficiente. Disponible: {item.stock}"}), 400
                    item.stock -= qty
                    move = WarehouseMovement(
                        item_id=item.id,
                        quantity=-qty,
                        movement_type='OUT',
                        date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        reference_id=ot_id,
                        reason=f"Uso en OT-{ot_id}",
                    )
                    db.session.add(move)
                elif item_type == 'tool' and item_id:
                    item = Tool.query.get(item_id)
                    if not item or not item.is_active:
                        return jsonify({"error": "Herramienta no encontrada o inactiva"}), 404
                elif item_type == 'free':
                    if not data.get('item_name_free', '').strip():
                        return jsonify({"error": "Debe ingresar el nombre del item"}), 400

                material = OTMaterial(
                    work_order_id=ot_id,
                    item_type=item_type,
                    item_id=item_id if item_id else None,
                    quantity=qty,
                    subtype=subtype,
                    item_name_free=data.get('item_name_free'),
                    unit=data.get('unit'),
                    is_installed=data.get('is_installed', True),
                )
                db.session.add(material)
                db.session.commit()
                return jsonify(material.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET - return materials for this OT
        materials = OTMaterial.query.filter_by(work_order_id=ot_id).all()

        # Pre-load catalog items in bulk (skip free-text items)
        tool_ids     = {m.item_id for m in materials if m.item_type == 'tool' and m.item_id}
        wh_ids       = {m.item_id for m in materials if m.item_type == 'warehouse' and m.item_id}
        tools_map    = {t.id: t for t in Tool.query.filter(Tool.id.in_(tool_ids)).all()}          if tool_ids else {}
        wh_items_map = {w.id: w for w in WarehouseItem.query.filter(WarehouseItem.id.in_(wh_ids)).all()} if wh_ids else {}

        result = []
        for m in materials:
            data = m.to_dict()
            if m.item_type == 'free' or not m.item_id:
                data['item_name']     = m.item_name_free or '-'
                data['item_code']     = ''
                data['item_category'] = ''
                data['item_status']   = None
                data['item_stock']    = None
            elif m.item_type == 'tool':
                item = tools_map.get(m.item_id)
                data['item_name']     = item.name     if item else '-'
                data['item_code']     = item.code     if item else ''
                data['item_category'] = item.category if item else ''
                data['item_status']   = item.status   if item else None
                data['item_stock']    = None
            else:
                item = wh_items_map.get(m.item_id)
                data['item_name']     = item.name     if item else '-'
                data['item_code']     = item.code     if item else ''
                data['item_category'] = item.category if item else ''
                data['item_status']   = None
                data['item_stock']    = item.stock    if item else None
            result.append(data)

        return jsonify(result)

    @app.route('/api/work_orders/<int:ot_id>/materials/<int:id>', methods=['PUT', 'DELETE'])
    def handle_ot_material_id(ot_id, id):
        material = OTMaterial.query.get_or_404(id)

        if request.method == 'PUT':
            data = request.json
            for key, value in data.items():
                if hasattr(material, key):
                    setattr(material, key, value)
            db.session.commit()
            return jsonify(material.to_dict())

        # DELETE with Stock Return
        if material.item_type == 'warehouse':
            item = WarehouseItem.query.get(material.item_id)
            if item:
                qty = material.quantity
                item.stock += qty  # Return stock

                # Record Movement
                move = WarehouseMovement(
                    item_id=item.id,
                    quantity=qty,
                    movement_type='RETURN',
                    date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    reference_id=ot_id,
                    reason=f"Devolución de OT-{ot_id}",
                )
                db.session.add(move)

        db.session.delete(material)
        db.session.commit()
        return jsonify({"message": "Material removed"})

    @app.route('/api/work-orders/mine', methods=['GET'])
    def handle_my_work_orders():
        """Retorna IDs de OTs asignadas al usuario logueado (por technician_id o ot_personnel)."""
        try:
            from flask_login import current_user
            if not current_user.is_authenticated:
                return jsonify({"tech_id": None, "ot_ids": []})
            full_name = (current_user.full_name or '').strip()
            # Buscar técnico por user_id o por nombre
            tech = Technician.query.filter_by(user_id=current_user.id).first()
            if not tech and full_name:
                tech = Technician.query.filter(
                    db.func.upper(Technician.name) == full_name.upper()
                ).first()
            if not tech:
                return jsonify({"tech_id": None, "ot_ids": [], "user_name": full_name})
            # OTs donde es técnico principal
            principal_ids = {str(wo.id) for wo in WorkOrder.query.filter(
                WorkOrder.technician_id == str(tech.id)
            ).all()}
            # OTs donde aparece en ot_personnel
            personnel_ids = {str(op.work_order_id) for op in OTPersonnel.query.filter_by(
                technician_id=tech.id
            ).all()}
            all_ids = list(principal_ids | personnel_ids)
            return jsonify({"tech_id": tech.id, "tech_name": tech.name, "ot_ids": all_ids})
        except Exception as e:
            logger.error(f"Error in /mine: {e}")
            return jsonify({"tech_id": None, "ot_ids": []}), 200

    @app.route('/api/work-orders/daily-round', methods=['GET', 'POST'])
    def handle_daily_round():
        """Obtiene o crea la OT de Ronda Diaria del técnico logueado para hoy."""
        try:
            from flask_login import current_user
            from datetime import date as _date
            if not current_user.is_authenticated:
                return jsonify({"error": "No autenticado"}), 401
            full_name = (current_user.full_name or '').strip()
            tech = Technician.query.filter_by(user_id=current_user.id).first()
            if not tech and full_name:
                tech = Technician.query.filter(
                    db.func.upper(Technician.name) == full_name.upper()
                ).first()
            tech_name = tech.name if tech else (full_name or current_user.username)
            tech_id = str(tech.id) if tech else None
            today = _date.today().isoformat()
            # Buscar si ya existe ronda del día
            existing = WorkOrder.query.filter(
                WorkOrder.scheduled_date == today,
                WorkOrder.maintenance_type == 'Ronda Diaria',
                WorkOrder.technician_id == tech_id
            ).first()
            if existing:
                return jsonify(existing.to_dict()), 200
            if request.method == 'GET':
                return jsonify({"exists": False, "today": today}), 200
            # POST: crear nueva ronda
            wo = WorkOrder(
                description=f"Ronda Diaria — {tech_name} — {today}",
                maintenance_type='Ronda Diaria',
                status='En Progreso',
                scheduled_date=today,
                real_start_date=today,
                technician_id=tech_id,
                priority='Media',
                scope='GENERAL',
            )
            db.session.add(wo)
            db.session.flush()
            wo.code = f"OT-{wo.id:04d}"
            # Agregar al técnico en ot_personnel si existe
            if tech:
                person = OTPersonnel(
                    work_order_id=wo.id,
                    technician_id=tech.id,
                    specialty=tech.specialty or 'GENERAL',
                    hours_assigned=8,
                )
                db.session.add(person)
            db.session.commit()
            return jsonify(wo.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in daily-round: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/work-orders', methods=['GET', 'POST'])
    def handle_work_orders():
        if request.method == 'POST':
            try:
                data = request.json

                # SANITIZATION: Only keep fields that exist in Model
                valid_keys = {c.name for c in WorkOrder.__table__.columns}
                clean_data = {k: v for k, v in data.items() if k in valid_keys}

                # Convert empty strings to None
                for k, v in clean_data.items():
                    if isinstance(v, str) and v.strip() == "":
                        clean_data[k] = None

                # Guard required field
                if not clean_data.get('status'):
                    clean_data['status'] = 'Abierta'

                # Create work order — code assigned after flush (uses real DB id)
                wo = WorkOrder(**clean_data)
                db.session.add(wo)
                db.session.flush()
                wo.code = f"OT-{wo.id:04d}"

                # If created from notice, update notice status and propagate source link
                if clean_data.get('notice_id'):
                    notice = MaintenanceNotice.query.get(clean_data['notice_id'])
                    if notice:
                        notice.status = 'En Tratamiento'
                        notice.ot_number = wo.code
                        # Propagate preventive source from notice to OT
                        if notice.source_type and notice.source_id and not wo.source_type:
                            wo.source_type = notice.source_type
                            wo.source_id = notice.source_id

                db.session.commit()
                return jsonify(wo.to_dict()), 201

            except Exception as e:
                db.session.rollback()
                import traceback

                traceback.print_exc()
                logger.error(f"Error creating work order: {e}")
                return jsonify({"error": str(e)}), 500

        # Pagination support: ?page=1&per_page=50 (omit page for all)
        page = request.args.get('page', type=int)
        query = WorkOrder.query.order_by(WorkOrder.id.desc())
        pagination_meta = None
        if page:
            from utils.crud_helpers import paginate_query
            entries, pagination_meta = paginate_query(query)
        else:
            entries = query.all()

        purchase_by_ot = {}
        if entries:
            ot_ids = [wo.id for wo in entries]
            reqs = PurchaseRequest.query.filter(PurchaseRequest.work_order_id.in_(ot_ids)).all()
            for req in reqs:
                purchase_by_ot.setdefault(req.work_order_id, []).append(req)

        # Pre-load taxonomy in bulk (eliminates N*5 queries)
        _area_ids  = {wo.area_id      for wo in entries if wo.area_id}
        _line_ids  = {wo.line_id      for wo in entries if wo.line_id}
        _equip_ids = {wo.equipment_id for wo in entries if wo.equipment_id}
        _sys_ids   = {wo.system_id    for wo in entries if wo.system_id}
        _comp_ids  = {wo.component_id for wo in entries if wo.component_id}
        areas_map  = {a.id: a for a in Area.query.filter(Area.id.in_(_area_ids)).all()}           if _area_ids  else {}
        lines_map  = {l.id: l for l in Line.query.filter(Line.id.in_(_line_ids)).all()}           if _line_ids  else {}
        equips_map = {e.id: e for e in Equipment.query.filter(Equipment.id.in_(_equip_ids)).all()} if _equip_ids else {}
        syss_map   = {s.id: s for s in System.query.filter(System.id.in_(_sys_ids)).all()}        if _sys_ids   else {}
        comps_map  = {c.id: c for c in Component.query.filter(Component.id.in_(_comp_ids)).all()} if _comp_ids  else {}

        # Enrich with hierarchy names
        results = []
        def get_name(obj):
            return obj.name if obj else '-'

        for wo in entries:
            data = wo.to_dict()

            # Resolve relations from pre-loaded maps
            area      = areas_map.get(wo.area_id)       if wo.area_id      else None
            line      = lines_map.get(wo.line_id)       if wo.line_id      else None
            equip     = equips_map.get(wo.equipment_id) if wo.equipment_id else None
            system    = syss_map.get(wo.system_id)      if wo.system_id    else None
            component = comps_map.get(wo.component_id)  if wo.component_id else None

            data['area_name'] = get_name(area)
            data['line_name'] = get_name(line)
            data['equipment_name'] = get_name(equip)
            data['equipment_tag'] = equip.tag if equip else '-'
            data['system_name'] = get_name(system)
            data['component_name'] = get_name(component)

            # Rotative asset name
            ra_id = getattr(wo, 'rotative_asset_id', None)
            if ra_id:
                from models import RotativeAsset
                ra = RotativeAsset.query.get(ra_id)
                data['rotative_asset_name'] = f"{ra.code} {ra.name}" if ra else None
            else:
                data['rotative_asset_name'] = None

            # Determine Criticality
            crit = '-'
            if component and component.criticality:
                crit = component.criticality
            elif equip and equip.criticality:
                crit = equip.criticality
            # Check notice linked criticality if not found in asset
            if crit == '-' and wo.notice and wo.notice.criticality:
                crit = wo.notice.criticality

            data['criticality'] = crit

            reqs_for_ot = purchase_by_ot.get(wo.id, [])
            status_count = {
                'PENDIENTE': 0,
                'APROBADO': 0,
                'EN_ORDEN': 0,
                'RECIBIDO': 0,
                'CANCELADO': 0,
            }
            blocking_count = 0
            req_codes = []
            po_codes = []

            for req in reqs_for_ot:
                req_status = (req.status or 'PENDIENTE').strip().upper()
                if req_status in status_count:
                    status_count[req_status] += 1
                if req_status not in {'RECIBIDO', 'CANCELADO', 'ANULADO'}:
                    blocking_count += 1
                if req.req_code:
                    req_codes.append(req.req_code)
                if req.purchase_order and req.purchase_order.po_code:
                    po_codes.append(req.purchase_order.po_code)

            req_codes = sorted(set(req_codes), reverse=True)
            po_codes = sorted(set(po_codes), reverse=True)
            tracking_parts = []
            if req_codes:
                tracking_parts.append(f"REQ: {', '.join(req_codes[:2])}")
            if po_codes:
                tracking_parts.append(f"OC: {', '.join(po_codes[:2])}")

            data['purchase_requests_total'] = len(reqs_for_ot)
            data['purchase_requests_pending'] = blocking_count
            data['purchase_status_count'] = status_count
            data['has_logistics_block'] = blocking_count > 0
            data['purchase_tracking'] = ' | '.join(tracking_parts) if tracking_parts else ''
            results.append(data)

        if pagination_meta:
            return jsonify({'items': results, 'pagination': pagination_meta})
        return jsonify(results)

    @app.route('/api/export-ots', methods=['GET'])
    def export_work_orders_excel():
        try:
            entries = WorkOrder.query.all()
            data = []

            # Pre-load all taxonomy and related objects in bulk
            _area_ids     = {wo.area_id      for wo in entries if wo.area_id}
            _line_ids     = {wo.line_id      for wo in entries if wo.line_id}
            _equip_ids    = {wo.equipment_id for wo in entries if wo.equipment_id}
            _sys_ids      = {wo.system_id    for wo in entries if wo.system_id}
            _comp_ids     = {wo.component_id for wo in entries if wo.component_id}
            _provider_ids = {wo.provider_id  for wo in entries if wo.provider_id}
            _notice_ids   = {wo.notice_id    for wo in entries if wo.notice_id}
            _areas_m  = {a.id: a for a in Area.query.filter(Area.id.in_(_area_ids)).all()}              if _area_ids     else {}
            _lines_m  = {l.id: l for l in Line.query.filter(Line.id.in_(_line_ids)).all()}              if _line_ids     else {}
            _equips_m = {e.id: e for e in Equipment.query.filter(Equipment.id.in_(_equip_ids)).all()}   if _equip_ids    else {}
            _syss_m   = {s.id: s for s in System.query.filter(System.id.in_(_sys_ids)).all()}           if _sys_ids      else {}
            _comps_m  = {c.id: c for c in Component.query.filter(Component.id.in_(_comp_ids)).all()}    if _comp_ids     else {}
            _provs_m  = {p.id: p for p in Provider.query.filter(Provider.id.in_(_provider_ids)).all()}  if _provider_ids else {}
            _nots_m   = {n.id: n for n in MaintenanceNotice.query.filter(MaintenanceNotice.id.in_(_notice_ids)).all()} if _notice_ids else {}

            def get_name(obj):
                return obj.name if obj else '-'

            for wo in entries:
                area  = _areas_m.get(wo.area_id)       if wo.area_id      else None
                line  = _lines_m.get(wo.line_id)       if wo.line_id      else None
                equip = _equips_m.get(wo.equipment_id) if wo.equipment_id else None
                sys   = _syss_m.get(wo.system_id)      if wo.system_id    else None
                comp  = _comps_m.get(wo.component_id)  if wo.component_id else None

                provider_name = _provs_m[wo.provider_id].name if wo.provider_id and wo.provider_id in _provs_m else '-'
                notice_code   = _nots_m[wo.notice_id].code    if wo.notice_id   and wo.notice_id   in _nots_m  else '-'

                data.append(
                    {
                        'Código': wo.code,
                        'Aviso Relacionado': notice_code,
                        'Área': get_name(area),
                        'Línea': get_name(line),
                        'Equipo': get_name(equip),
                        'TAG Equipo': equip.tag if equip else '-',
                        'Sistema': get_name(sys),
                        'Componente': get_name(comp),
                        'Criticidad': comp.criticality if comp and comp.criticality else (equip.criticality if equip else '-'),
                        'Descripción OT': wo.description,
                        'Modo de Falla': wo.failure_mode,
                        'Tipo Mtto': wo.maintenance_type,
                        'Estado': wo.status,
                        'Técnico Principal': wo.technician_id,
                        'Cant. Técnicos': wo.tech_count,
                        'Proveedor': provider_name,
                        'Fecha Programada': wo.scheduled_date,
                        'Duración Est. (Hr)': wo.estimated_duration,
                        'Fecha Inicio Real': wo.real_start_date,
                        'Fecha Fin Real': wo.real_end_date,
                        'Duración Real (Hr)': wo.real_duration,
                        'Comentarios Ejecución': wo.execution_comments,
                    }
                )

            df = pd.DataFrame(data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='OrdenesTrabajo')

            output.seek(0)

            return send_file(
                output,
                download_name="Reporte_OTs_Completo.xlsx",
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

        except Exception as e:
            logger.error(f"OT Export Error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/work-orders/<int:id>', methods=['PUT', 'DELETE'])
    def handle_wot_id(id):
        try:
            if request.method == 'PUT':
                data = request.json
                logger.info(f"Updating OT {id} with data: {data}")

                # First update the work order
                wo = WorkOrder.query.get(id)
                if not wo:
                    return jsonify({"error": "Work Order not found"}), 404

                # Hard guard for required field before applying updates
                # If status comes null/empty from frontend, ignore incoming value and keep current/default.
                if ('status' in data) and (data.get('status') is None or (isinstance(data.get('status'), str) and data.get('status').strip() == "")):
                    data.pop('status', None)

                for key, value in data.items():
                    if hasattr(wo, key):
                        if isinstance(value, str) and value.strip() == "":
                            value = None
                        # Keep non-null DB constraint safe
                        if key == 'status' and value is None:
                            value = wo.status or 'Abierta'
                        setattr(wo, key, value)

                # Final safeguard: OT status must never be null
                if not wo.status:
                    wo.status = 'Abierta'

                # If WO is being closed, sync to associated notice
                if data.get('status') == 'Cerrada' and wo.notice_id:
                    notice = MaintenanceNotice.query.get(wo.notice_id)
                    if notice:
                        notice.status = 'Cerrado'
                        notice.ot_number = wo.code

                # If closing a preventive OT linked to a source, update the source point
                if data.get('status') == 'Cerrada' and wo.source_type and wo.source_id:
                    close_date = wo.real_end_date or wo.real_start_date or datetime.now().strftime('%Y-%m-%d')
                    _update_source_on_close(wo.source_type, wo.source_id, close_date)

                # AUTO-LEARNING: Update Component's criticality if provided
                criticality_value = data.get('priority') or data.get('criticality')
                if criticality_value and wo.component_id:
                    comp = Component.query.get(wo.component_id)
                    if comp:
                        comp.criticality = criticality_value
                        logger.info(f"Updated Component {comp.id} criticality to '{criticality_value}'")

                db.session.commit()
                return jsonify(wo.to_dict())

            return delete_entry(WorkOrder, id)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating OT {id}: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/work-orders/feedback', methods=['GET'])
    def get_work_order_feedback():
        try:
            equip_id = request.args.get('equipment_id')
            if not equip_id:
                return jsonify([])

            # Get last 5 closed OTs for this equipment with comments
            ots = WorkOrder.query.filter(
                WorkOrder.equipment_id == equip_id,
                WorkOrder.status == 'Cerrada',
                WorkOrder.execution_comments != None,
                WorkOrder.execution_comments != '',
            ).order_by(WorkOrder.real_end_date.desc()).limit(5).all()

            results = []
            for ot in ots:
                tech_name = "Desconocido"
                if ot.technician_id:
                    # heuristic: if numeric, find in DB, else use string
                    if ot.technician_id.isdigit():
                        t = Technician.query.get(int(ot.technician_id))
                        if t:
                            tech_name = t.name

                results.append(
                    {
                        "date": ot.real_end_date or ot.real_start_date or 'N/A',
                        "maintenance_type": ot.maintenance_type,
                        "comments": ot.execution_comments,
                        "tech_name": tech_name,
                        "ot_code": ot.code or f"OT-{ot.id}",
                    }
                )

            return jsonify(results)
        except Exception as e:
            logger.error(f"Error fetching feedback: {e}")
            return jsonify({"error": str(e)}), 500




