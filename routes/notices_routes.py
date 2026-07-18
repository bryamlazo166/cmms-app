from datetime import datetime
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
    OTLogEntry=None,
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

                # F. Solicitud = momento de captura en el CMMS. El front manda
                # solo la fecha (input type=date) o nada; completamos con la
                # HORA actual de Lima para registrar el instante real, en
                # formato 'YYYY-MM-DD HH:MM'.
                from utils.tz import now_lima_iso
                _rd = clean_data.get('request_date')
                _now_lima = now_lima_iso(with_seconds=False).replace('T', ' ')
                if not _rd:
                    clean_data['request_date'] = _now_lima
                elif len(str(_rd).strip()) <= 10:
                    clean_data['request_date'] = f"{str(_rd).strip()[:10]} {_now_lima[11:16]}"

                # Defaults para los nuevos campos de reporte:
                # - report_channel: si no se especifica, asumir SISTEMA
                # - reported_at: si el canal es SISTEMA o no hay valor manual,
                #   usar request_date como aproximación (= momento de captura)
                if not clean_data.get('report_channel'):
                    clean_data['report_channel'] = 'SISTEMA'
                if not clean_data.get('reported_at'):
                    # Para canal SISTEMA reported_at = request_date (now)
                    clean_data['reported_at'] = clean_data.get('request_date')

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

                # Copiloto de diagnostico (RCA IA) para mantenimiento — solo si
                # el aviso no fue marcado como duplicado.
                if not is_duplicate:
                    try:
                        from bot.rca import trigger_rca_async
                        trigger_rca_async(app, new_entry.id)
                    except Exception as _er:
                        logger.warning(f"trigger RCA aviso {new_entry.id} fallo: {_er}")

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

        # Pre-cargar diccionarios de nombres para resolver IDs en el response.
        # Asi el frontend no necesita /api/areas, /api/lines, etc. para mostrar
        # nombres (eso evita que roles sin acceso a 'activos_config' vean solo
        # numeros en la tabla de avisos).
        from models import Area, Line, Equipment
        areas_map      = {a.id: a.name for a in Area.query.all()}
        lines_map      = {l.id: l.name for l in Line.query.all()}
        # Separar nombre y tag — antes solo devolvia el tag y la tabla mostraba
        # el codigo en lugar del nombre del equipo.
        equipments_map = {e.id: {'name': e.name, 'tag': e.tag} for e in Equipment.query.all()}
        systems_map    = {s.id: s.name for s in System.query.all()}
        components_map = {c.id: c.name for c in Component.query.all()}

        for notice in entries:
            data = notice.to_dict()
            data['area_name']      = areas_map.get(notice.area_id, '-') if notice.area_id else '-'
            data['line_name']      = lines_map.get(notice.line_id, '-') if notice.line_id else '-'
            eq_info = equipments_map.get(notice.equipment_id) if notice.equipment_id else None
            data['equipment_name'] = (eq_info['name'] if eq_info else '-')
            data['equipment_tag']  = (eq_info['tag'] if eq_info else None)
            data['system_name']    = systems_map.get(notice.system_id, '-') if notice.system_id else '-'
            data['component_name'] = components_map.get(notice.component_id, '-') if notice.component_id else '-'

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

    @app.route('/api/notices/tree', methods=['GET'])
    def notices_tree():
        """Árbol de equipos compacto para el formulario de reporte (Modo Campo).

        Vive bajo /api/notices (módulo 'avisos') a propósito: los roles de campo
        (tecnico/mecanico/electricista) tienen avisos.view pero NO activos_config,
        así que /api/areas etc. les daría 403.
        """
        try:
            from models import Area, Line, Equipment, System, Component
            return jsonify({
                "areas": [{"id": a.id, "name": a.name} for a in Area.query.order_by(Area.name)],
                "lines": [{"id": l.id, "name": l.name, "area_id": l.area_id}
                          for l in Line.query.order_by(Line.name)],
                "equipments": [{"id": e.id, "name": e.name, "tag": e.tag, "line_id": e.line_id}
                               for e in Equipment.query.order_by(Equipment.name)],
                "systems": [{"id": s.id, "name": s.name, "equipment_id": s.equipment_id}
                            for s in System.query.order_by(System.name)],
                "components": [{"id": c.id, "name": c.name, "system_id": c.system_id}
                               for c in Component.query.order_by(Component.name)],
            })
        except Exception as e:
            logger.exception('notices_tree error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/notices/<int:id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_notice_id(id):
        if request.method == 'GET':
            notice = MaintenanceNotice.query.get(id)
            if not notice:
                return jsonify({"error": "Notice not found"}), 404
            data = notice.to_dict()
            # Pre-diagnóstico IA (RCA) — visible solo aquí, en el CMMS con login.
            try:
                from bot.rca import get_rca
                data['rca'] = get_rca(app, id)
            except Exception as _re:
                logger.warning(f"get_rca aviso {id} fallo: {_re}")
                data['rca'] = None
            return jsonify(data)
        if request.method == 'PUT':
            data = request.json or {}
            # Preservar la HORA de captura: si el front reenvia request_date como
            # solo fecha (input type=date) y la fecha no cambio, conservar el
            # valor ya guardado que incluye la hora.
            _in_rd = data.get('request_date')
            if isinstance(_in_rd, str) and 0 < len(_in_rd.strip()) <= 10:
                _cur = MaintenanceNotice.query.get(id)
                if (_cur and _cur.request_date and len(str(_cur.request_date)) > 10
                        and str(_cur.request_date)[:10] == _in_rd.strip()[:10]):
                    data['request_date'] = _cur.request_date

            resp = update_entry(MaintenanceNotice, id, data)

            # Propagar el arbol de equipos del aviso a la OT vinculada para que
            # reportes/tableros la ubiquen en el area correcta. Aplica tambien a
            # OTs cerradas: corregir la taxonomia es una correccion de datos
            # historicos, no un cambio de flujo (antes se omitian las cerradas y
            # las correcciones del aviso nunca llegaban a la OT).
            try:
                TREE = ('area_id', 'line_id', 'equipment_id', 'system_id', 'component_id')
                if any(k in data for k in TREE):
                    notice = MaintenanceNotice.query.get(id)
                    wo = getattr(notice, 'work_order', None) if notice else None
                    if wo:
                        changed = False
                        for f in TREE:
                            nv = getattr(notice, f, None)
                            if getattr(wo, f, None) != nv:
                                setattr(wo, f, nv)
                                changed = True
                        if changed:
                            db.session.commit()
                            logger.info(f"Notice {id}: arbol de equipos propagado a OT {wo.code or wo.id}")
            except Exception as e:
                db.session.rollback()
                logger.exception(f"Error propagando arbol aviso->OT (notice {id}): {e}")

            return resp
        return delete_entry(MaintenanceNotice, id)

    # ── Edición auditada de la hora real del reporte ──────────────────
    # Restringido a jefatura/admin: cambiar reported_at modifica el T.respuesta
    # histórico, así que cada edición se registra en la bitácora de la OT vinculada
    # (si existe), o en logs del sistema si el aviso aún no tiene OT.
    @app.route('/api/notices/<int:id>/reported-at', methods=['PATCH'])
    def patch_notice_reported_at(id):
        try:
            from flask_login import current_user
            allowed_roles = ('admin', 'supervisor', 'gerencia')
            user_role = getattr(current_user, 'role', None)
            if user_role not in allowed_roles:
                return jsonify({"error": "Solo jefatura/administrador puede ajustar la hora del reporte."}), 403

            notice = MaintenanceNotice.query.get(id)
            if not notice:
                return jsonify({"error": "Notice not found"}), 404

            data = request.get_json() or {}
            prev_reported_at = notice.reported_at
            prev_channel = notice.report_channel

            new_reported = data.get('reported_at')
            if isinstance(new_reported, str) and new_reported.strip() == '':
                new_reported = None
            new_channel = data.get('report_channel')
            if isinstance(new_channel, str) and new_channel.strip() == '':
                new_channel = None

            notice.reported_at = new_reported
            if new_channel is not None:
                notice.report_channel = new_channel

            reason = (data.get('reason') or '').strip()

            changes = []
            if (prev_reported_at or '') != (notice.reported_at or ''):
                changes.append(f"Hora del reporte: {prev_reported_at or '—'} → {notice.reported_at or '—'}")
            if (prev_channel or '') != (notice.report_channel or ''):
                changes.append(f"Canal: {prev_channel or '—'} → {notice.report_channel or '—'}")

            # Auditoría: si el aviso tiene OT vinculada, escribir en su bitácora
            if changes and OTLogEntry and notice.work_order:
                author = None
                try:
                    author = current_user.full_name or current_user.username
                except Exception:
                    pass
                comment = 'Edición de hora real del reporte (aviso): ' + '; '.join(changes)
                if reason:
                    comment += f" | Motivo: {reason}"
                db.session.add(OTLogEntry(
                    work_order_id=notice.work_order.id,
                    log_date=datetime.now().strftime('%Y-%m-%d'),
                    log_type='NOTA',
                    author=author or 'sistema',
                    comment=comment,
                ))

            db.session.commit()
            logger.info(f"Notice {notice.id} reported_at edited by {user_role}: {len(changes)} cambios")
            return jsonify(notice.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Error patching notice reported_at {id}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/notices/<int:id>/rca/regenerate', methods=['POST'])
    def regenerate_notice_rca(id):
        """Regenera el pre-diagnóstico IA de un aviso (bajo demanda desde la ficha).

        Por defecto NO reenvía al grupo de mantenimiento (push=false): solo
        actualiza la ficha. Pasar {"push": true} para volver a avisar al grupo.
        """
        try:
            notice = MaintenanceNotice.query.get(id)
            if not notice:
                return jsonify({"error": "Notice not found"}), 404
            from bot.rca import generate_rca
            push = bool((request.get_json(silent=True) or {}).get('push', False))
            payload = generate_rca(app, id, push=push)
            if payload is None:
                return jsonify({"error": "No se pudo generar el diagnóstico (¿falta DEEPSEEK_API_KEY?)"}), 503
            return jsonify({"ok": True, "rca": payload})
        except Exception as e:
            logger.exception(f"regenerate RCA {id}")
            return jsonify({"error": str(e)}), 500

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
