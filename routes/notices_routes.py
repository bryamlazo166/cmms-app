from flask import jsonify, request


def register_notices_routes(
    app,
    db,
    logger,
    MaintenanceNotice,
    WorkOrder,
    System,
    Component,
    Tool,
    WarehouseItem,
    update_entry,
    delete_entry,
):
    @app.route('/api/notices', methods=['GET', 'POST'])
    def handle_notices():
        if request.method == 'POST':
            try:
                data = request.json
                logger.info(f"Received notice data: {data}")

                # SANITIZATION: Only keep fields that exist in Model
                valid_keys = {c.name for c in MaintenanceNotice.__table__.columns}
                clean_data = {k: v for k, v in data.items() if k in valid_keys}

                # Convert empty strings to None
                for k, v in clean_data.items():
                    if isinstance(v, str) and v.strip() == "":
                        clean_data[k] = None

                logger.info(f"Cleaned notice data: {clean_data}")

                # Code will be assigned after flush (uses real DB id)

                # --- DUPLICATE DETECTION LOGIC (taxonomía completa) ---
                is_duplicate = False
                duplicate_reason = ""

                target_equip = clean_data.get('equipment_id')
                target_system = clean_data.get('system_id')
                target_comp = clean_data.get('component_id')
                target_failure = clean_data.get('failure_mode')

                if target_equip:
                    # Construir filtro progresivo por taxonomía
                    # Nivel 1: mismo equipo + mismo componente (más específico)
                    # Nivel 2: mismo equipo + mismo sistema (si no hay componente)
                    # Nivel 3: mismo equipo + mismo modo de falla (para bloqueos/atascamientos)

                    # 1. Buscar avisos activos con match de taxonomía
                    notice_q = MaintenanceNotice.query.filter(
                        MaintenanceNotice.equipment_id == target_equip,
                        MaintenanceNotice.status.in_(['Pendiente', 'En Progreso', 'En Tratamiento']),
                    )

                    existing_notice = None
                    if target_comp:
                        # Match exacto: equipo + componente
                        existing_notice = notice_q.filter(
                            MaintenanceNotice.component_id == target_comp
                        ).first()
                    elif target_system:
                        # Match por sistema (si no hay componente)
                        existing_notice = notice_q.filter(
                            MaintenanceNotice.system_id == target_system
                        ).first()
                    elif target_failure:
                        # Match por modo de falla (ej: Atascamiento del mismo equipo)
                        existing_notice = notice_q.filter(
                            MaintenanceNotice.failure_mode == target_failure
                        ).first()

                    if existing_notice:
                        is_duplicate = True
                        match_level = 'componente' if target_comp else ('sistema' if target_system else 'modo de falla')
                        duplicate_reason = f"Aviso activo {existing_notice.code} (mismo {match_level})"

                    # 2. Buscar OTs activas con match de taxonomía
                    if not is_duplicate:
                        ot_q = WorkOrder.query.filter(
                            WorkOrder.equipment_id == target_equip,
                            WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso']),
                        )
                        existing_ot = None
                        if target_comp:
                            existing_ot = ot_q.filter(WorkOrder.component_id == target_comp).first()
                        elif target_system:
                            existing_ot = ot_q.filter(WorkOrder.system_id == target_system).first()

                        if existing_ot:
                            is_duplicate = True
                            duplicate_reason = f"OT activa {existing_ot.code}"

                if is_duplicate:
                    clean_data['status'] = 'Duplicado'
                    original_desc = clean_data.get('description', '') or ''
                    clean_data['description'] = f"[POSIBLE DUPLICADO: {duplicate_reason}] {original_desc}"
                    logger.warning(f"Notice marked as duplicate: {duplicate_reason}")

                new_entry = MaintenanceNotice(**clean_data)
                db.session.add(new_entry)
                db.session.flush()
                new_entry.code = f"AV-{new_entry.id:04d}"
                db.session.commit()

                # RAG: indexar el nuevo aviso para busqueda semantica
                try:
                    from bot.telegram_bot import _index_entity_async
                    _index_entity_async(app, 'notice', new_entry.id)
                except Exception as _ei:
                    logger.warning(f"RAG index aviso {new_entry.id} fallo: {_ei}")

                resp_data = new_entry.to_dict()
                if is_duplicate:
                    resp_data['is_duplicate'] = True
                    resp_data['duplicate_reason'] = duplicate_reason

                return jsonify(resp_data), 201
            except Exception as e:
                db.session.rollback()
                import traceback

                traceback.print_exc()
                logger.error(f"Error creating notice: {e}")
                return jsonify({"error": str(e)}), 500

        page = request.args.get('page', type=int)
        query = MaintenanceNotice.query.order_by(MaintenanceNotice.id.desc())
        pagination_meta = None
        if page:
            from utils.crud_helpers import paginate_query
            entries, pagination_meta = paginate_query(query)
        else:
            entries = query.all()
        results = []

        # Pre-fetch cache to avoid N+1 if possible, but for simplicity we'll do direct lookups first or simple caching
        # Better: just resolve per item.
        for notice in entries:
            data = notice.to_dict()

            # Resolve Equipment ID
            equip_id = None
            if notice.equipment_id:
                equip_id = notice.equipment_id
            elif notice.system_id:
                # We need to import System/Component/Equipment if not available globally.
                # Assuming they are available as they are models.
                try:
                    sys = System.query.get(notice.system_id)
                    if sys:
                        equip_id = sys.equipment_id
                except Exception:
                    pass
            elif notice.component_id:
                try:
                    comp = Component.query.get(notice.component_id)
                    if comp:
                        sys = System.query.get(comp.system_id)
                        if sys:
                            equip_id = sys.equipment_id
                except Exception:
                    pass

            # Calculate Failure Count (Corrective + Closed)
            failure_count = 0
            if equip_id:
                try:
                    failure_count = WorkOrder.query.filter_by(
                        equipment_id=equip_id,
                        maintenance_type='Correctivo',
                        status='Cerrada',
                    ).count()
                except Exception as e:
                    logger.error(f"Error counting failures for equip {equip_id}: {e}")
                    logger.error(f"Error counting failures for equip {equip_id}: {e}")

            data['failure_count'] = failure_count

            # Include Failure Mode from linked OT if exists
            data['failure_mode'] = '-'
            if notice.work_order:
                data['failure_mode'] = notice.work_order.failure_mode or '-'

            results.append(data)

        if pagination_meta:
            return jsonify({'items': results, 'pagination': pagination_meta})
        return jsonify(results)

    @app.route('/api/notices/<int:id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_notice_id(id):
        if request.method == 'GET':
            notice = MaintenanceNotice.query.get(id)
            if not notice:
                return jsonify({"error": "Notice not found"}), 404
            return jsonify(notice.to_dict())
        if request.method == 'PUT':
            return update_entry(MaintenanceNotice, id, request.json)
        return delete_entry(MaintenanceNotice, id)

    @app.route('/api/predictive/check-duplicates', methods=['GET'])
    def check_duplicates():
        try:
            equip_id = request.args.get('equipment_id')
            exclude_notice_id = request.args.get('exclude_notice_id')

            if not equip_id:
                return jsonify({"error": "Equipment ID required"}), 400

            # 1. Active Notices
            notice_query = MaintenanceNotice.query.filter(
                MaintenanceNotice.equipment_id == equip_id,
                MaintenanceNotice.status.in_(['Pendiente', 'En Progreso', 'En Tratamiento']),
            )
            if exclude_notice_id:
                notice_query = notice_query.filter(MaintenanceNotice.id != exclude_notice_id)

            duplicate_notices = notice_query.all()

            # 2. Active Work Orders
            duplicate_ots = WorkOrder.query.filter(
                WorkOrder.equipment_id == equip_id,
                WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso']),
            ).all()

            return jsonify({
                "notices": [n.to_dict() for n in duplicate_notices],
                "work_orders": [ot.to_dict() for ot in duplicate_ots],
            })

        except Exception as e:
            logger.error(f"Duplicate Check Error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/predictive/ot-suggestions', methods=['GET'])
    def get_ot_suggestions():
        try:
            # Extract query params
            m_type = request.args.get('maintenance_type')
            comp_id = request.args.get('component_id')
            sys_id = request.args.get('system_id')
            equip_id = request.args.get('equipment_id')

            # Build query
            query = WorkOrder.query.filter_by(status='Cerrada')

            if m_type:
                query = query.filter_by(maintenance_type=m_type)

            # Hierarchy filtering - prioritize most specific
            if comp_id:
                query = query.filter_by(component_id=comp_id)
            elif sys_id:
                query = query.filter_by(system_id=sys_id)
            elif equip_id:
                query = query.filter_by(equipment_id=equip_id)
            else:
                return jsonify({"found": False, "message": "No asset specified"}), 200

            # Get most recent
            last_ot = query.order_by(WorkOrder.id.desc()).first()

            if not last_ot:
                return jsonify({"found": False, "message": "No history found"}), 200

            # Gather materials
            tools = []
            parts = []

            for m in last_ot.assigned_materials:
                item_name = "Unknown"
                code = ""
                if m.item_type == 'tool':
                    t = Tool.query.get(m.item_id)
                    if t:
                        item_name = t.name
                        code = t.code
                    tools.append(
                        {
                            "item_id": m.item_id,
                            "item_type": "tool",
                            "quantity": m.quantity,
                            "name": item_name,
                            "code": code,
                        }
                    )
                else:
                    w = WarehouseItem.query.get(m.item_id)
                    if w:
                        item_name = w.name
                        code = w.code
                    parts.append(
                        {
                            "item_id": m.item_id,
                            "item_type": "warehouse",
                            "quantity": m.quantity,
                            "name": item_name,
                            "code": code,
                        }
                    )

            return jsonify({"found": True, "tools": tools, "parts": parts, "source_ot": last_ot.code}), 200

        except Exception as e:
            logger.error(f"Suggestion Error: {e}")
            return jsonify({"error": str(e)}), 500
