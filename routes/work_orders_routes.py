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
):
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
                data['work_order_id'] = ot_id

                # Safety Checks
                if not data.get('item_id'):
                    return jsonify({"error": "Item ID is required"}), 400

                try:
                    qty = int(data.get('quantity', 1))
                    if qty <= 0:
                        raise ValueError
                except Exception:
                    return jsonify({"error": "Quantity must be a positive integer"}), 400

                # Inventory Logic
                if data['item_type'] == 'warehouse':
                    item = WarehouseItem.query.get(data['item_id'])

                    if not item:
                        return jsonify({"error": "Item not found"}), 404

                    if item.stock < qty:
                        return jsonify({"error": f"Stock insuficiente. Disponible: {item.stock}"}), 400

                    # Deduct Stock
                    item.stock -= qty

                    # Record Movement
                    move = WarehouseMovement(
                        item_id=item.id,
                        quantity=-qty,
                        movement_type='OUT',
                        date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        reference_id=ot_id,
                        reason=f"Uso en OT-{ot_id}",
                    )
                    db.session.add(move)

                elif data['item_type'] == 'tool':
                    # Validate tool from Tool catalog (no stock deduction)
                    item = Tool.query.get(data['item_id'])
                    if not item or not item.is_active:
                        return jsonify({"error": "Herramienta no encontrada o inactiva"}), 404

                material = OTMaterial(**data)
                db.session.add(material)
                db.session.commit()
                return jsonify(material.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET - return materials for this OT
        materials = OTMaterial.query.filter_by(work_order_id=ot_id).all()

        # Pre-load tools and warehouse items in bulk
        tool_ids      = {m.item_id for m in materials if m.item_type == 'tool'}
        wh_ids        = {m.item_id for m in materials if m.item_type != 'tool'}
        tools_map     = {t.id: t for t in Tool.query.filter(Tool.id.in_(tool_ids)).all()}         if tool_ids else {}
        wh_items_map  = {w.id: w for w in WarehouseItem.query.filter(WarehouseItem.id.in_(wh_ids)).all()} if wh_ids   else {}

        result = []
        for m in materials:
            data = m.to_dict()
            if m.item_type == 'tool':
                item = tools_map.get(m.item_id)
                data['item_status'] = item.status if item else None
                data['item_stock'] = None
            else:
                item = wh_items_map.get(m.item_id)
                data['item_status'] = None
                data['item_stock'] = item.stock if item else None

            data['item_name']     = item.name     if item else 'Unknown'
            data['item_code']     = item.code     if item else ''
            data['item_category'] = item.category if item else ''
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

                # Generate Code
                last = WorkOrder.query.order_by(WorkOrder.id.desc()).first()
                next_id = (last.id if last else 0) + 1
                clean_data['code'] = f"OT-{next_id:04d}"

                # Create work order
                wo = WorkOrder(**clean_data)
                db.session.add(wo)
                db.session.flush()  # Get the ID

                # If created from notice, update notice status
                if clean_data.get('notice_id'):
                    notice = MaintenanceNotice.query.get(clean_data['notice_id'])
                    if notice:
                        notice.status = 'En Tratamiento'
                        notice.ot_number = wo.code

                db.session.commit()
                return jsonify(wo.to_dict()), 201

            except Exception as e:
                db.session.rollback()
                import traceback

                traceback.print_exc()
                logger.error(f"Error creating work order: {e}")
                return jsonify({"error": str(e)}), 500

        entries = WorkOrder.query.all()
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




