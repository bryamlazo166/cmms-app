import datetime as dt

from flask import jsonify, request
from sqlalchemy import text


def register_inspection_routes(
    app, db, logger,
    InspectionRoute, InspectionItem, InspectionExecution, InspectionResult,
    MaintenanceNotice,
    _calculate_lubrication_schedule,  # reuse for schedule calc
    _parse_date_flexible,
):

    # ── Routes CRUD ────────────────────────────────────────────────────────

    @app.route('/api/inspection/routes', methods=['GET', 'POST'])
    def handle_inspection_routes():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                frequency_days = int(data.get('frequency_days') or 7)
                warning_days = int(data.get('warning_days') or 1)

                route = InspectionRoute(
                    name=data['name'].strip(),
                    description=data.get('description'),
                    area_id=data.get('area_id') or None,
                    line_id=data.get('line_id') or None,
                    equipment_id=data.get('equipment_id') or None,
                    frequency_days=frequency_days,
                    warning_days=warning_days,
                    is_active=True,
                )
                db.session.add(route)
                db.session.flush()
                route.code = f"INSP-{route.id:04d}"
                db.session.commit()
                return jsonify(route.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception("Inspection route POST error")
                return jsonify({"error": str(e)}), 500

        show_all = request.args.get('all', 'false').lower() == 'true'
        query = InspectionRoute.query
        if not show_all:
            query = query.filter_by(is_active=True)
        routes = query.order_by(InspectionRoute.id.desc()).all()

        result = []
        for r in routes:
            d = r.to_dict()
            next_due, semaphore = _calculate_lubrication_schedule(
                r.last_execution_date, r.frequency_days, r.warning_days
            )
            d['next_due_date'] = next_due
            d['semaphore_status'] = semaphore
            result.append(d)
        return jsonify(result)

    @app.route('/api/inspection/routes/<int:route_id>', methods=['PUT', 'DELETE'])
    def handle_inspection_route_id(route_id):
        route = InspectionRoute.query.get_or_404(route_id)

        if request.method == 'DELETE':
            route.is_active = not route.is_active
            db.session.commit()
            state = "activada" if route.is_active else "desactivada"
            return jsonify({"message": f"Ruta {state}", "is_active": route.is_active})

        try:
            data = request.json or {}
            for field in ['name', 'description', 'area_id', 'line_id', 'equipment_id',
                          'frequency_days', 'warning_days']:
                if field in data:
                    setattr(route, field, data[field] or None)
            route.frequency_days = int(route.frequency_days or 7)
            route.warning_days = int(route.warning_days or 1)
            db.session.commit()
            return jsonify(route.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── Items CRUD ─────────────────────────────────────────────────────────

    @app.route('/api/inspection/routes/<int:route_id>/items', methods=['GET', 'POST'])
    def handle_inspection_items(route_id):
        route = InspectionRoute.query.get_or_404(route_id)

        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('description') or '').strip():
                    return jsonify({"error": "description es obligatorio"}), 400

                max_order = db.session.query(db.func.max(InspectionItem.order_index)) \
                    .filter_by(route_id=route_id).scalar() or 0

                item = InspectionItem(
                    route_id=route_id,
                    description=data['description'].strip(),
                    item_type=(data.get('item_type') or 'CHECK').upper(),
                    unit=data.get('unit'),
                    alarm_min=data.get('alarm_min'),
                    alarm_max=data.get('alarm_max'),
                    criteria=data.get('criteria'),
                    order_index=max_order + 1,
                )
                db.session.add(item)
                db.session.commit()
                return jsonify(item.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        items = InspectionItem.query.filter_by(route_id=route_id, is_active=True) \
            .order_by(InspectionItem.order_index).all()
        return jsonify([i.to_dict() for i in items])

    @app.route('/api/inspection/items/<int:item_id>', methods=['PUT', 'DELETE'])
    def handle_inspection_item_id(item_id):
        item = InspectionItem.query.get_or_404(item_id)

        if request.method == 'DELETE':
            item.is_active = False
            db.session.commit()
            return jsonify({"ok": True})

        try:
            data = request.json or {}
            for field in ['description', 'item_type', 'unit', 'alarm_min', 'alarm_max', 'criteria']:
                if field in data:
                    setattr(item, field, data[field])
            db.session.commit()
            return jsonify(item.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── Executions ─────────────────────────────────────────────────────────

    @app.route('/api/inspection/executions', methods=['GET', 'POST'])
    def handle_inspection_executions():
        if request.method == 'POST':
            try:
                data = request.json or {}
                route_id = data.get('route_id')
                if not route_id:
                    return jsonify({"error": "route_id es obligatorio"}), 400

                route = InspectionRoute.query.get(route_id)
                if not route:
                    return jsonify({"error": "Ruta no encontrada"}), 404

                execution_date = data.get('execution_date') or dt.date.today().isoformat()
                results_data = data.get('results', [])

                # Create execution
                findings = 0
                exec_obj = InspectionExecution(
                    route_id=route_id,
                    execution_date=execution_date,
                    executed_by=data.get('executed_by'),
                    comments=data.get('comments'),
                )
                db.session.add(exec_obj)
                db.session.flush()

                # Process each item result
                for r in results_data:
                    item_id = r.get('item_id')
                    item = InspectionItem.query.get(item_id)
                    if not item:
                        continue

                    result_val = (r.get('result') or 'OK').upper()
                    value = r.get('value')
                    observation = r.get('observation')

                    # Auto-determine result for MEDICION based on thresholds
                    if item.item_type == 'MEDICION' and value is not None:
                        try:
                            v = float(value)
                            if (item.alarm_min is not None and v < item.alarm_min) or \
                               (item.alarm_max is not None and v > item.alarm_max):
                                result_val = 'ALARMA'
                            else:
                                result_val = 'OK'
                        except (ValueError, TypeError):
                            pass

                    if result_val in ('NO_OK', 'ALARMA'):
                        findings += 1

                    ir = InspectionResult(
                        execution_id=exec_obj.id,
                        item_id=item_id,
                        result=result_val,
                        value=float(value) if value is not None else None,
                        text_value=r.get('text_value'),
                        observation=observation,
                    )
                    db.session.add(ir)

                exec_obj.findings_count = findings
                exec_obj.overall_result = 'CON_HALLAZGOS' if findings > 0 else 'OK'

                # Update route schedule
                route.last_execution_date = execution_date
                next_due, semaphore = _calculate_lubrication_schedule(
                    execution_date, route.frequency_days, route.warning_days
                )
                route.next_due_date = next_due
                route.semaphore_status = semaphore

                # Auto-create notice if findings
                if findings > 0 and data.get('create_notice', True):
                    notice = MaintenanceNotice(
                        reporter_name=exec_obj.executed_by or 'Inspector',
                        reporter_type='INSPECCION',
                        area_id=route.area_id,
                        line_id=route.line_id,
                        equipment_id=route.equipment_id,
                        description=f"[INSPECCION] {route.name}: {findings} hallazgo(s). {exec_obj.comments or ''}",
                        maintenance_type='Preventivo',
                        priority='Media',
                        status='Pendiente',
                        request_date=execution_date,
                    )
                    db.session.add(notice)
                    db.session.flush()
                    notice.code = f"AV-{notice.id:04d}"
                    exec_obj.created_notice_id = notice.id

                db.session.commit()
                return jsonify(exec_obj.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception("Inspection execution POST error")
                return jsonify({"error": str(e)}), 500

        # GET
        route_id = request.args.get('route_id', type=int)
        query = InspectionExecution.query
        if route_id:
            query = query.filter_by(route_id=route_id)
        rows = query.order_by(InspectionExecution.id.desc()).limit(200).all()
        return jsonify([r.to_dict() for r in rows])

    @app.route('/api/inspection/executions/<int:exec_id>/results', methods=['GET'])
    def get_inspection_results(exec_id):
        results = InspectionResult.query.filter_by(execution_id=exec_id).all()
        return jsonify([r.to_dict() for r in results])

    # ── Dashboard ──────────────────────────────────────────────────────────

    @app.route('/api/inspection/dashboard', methods=['GET'])
    def inspection_dashboard():
        try:
            show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
            if show_inactive:
                routes = InspectionRoute.query.all()
            else:
                routes = InspectionRoute.query.filter_by(is_active=True).all()

            kpi = {'total': 0, 'green': 0, 'yellow': 0, 'red': 0, 'pending': 0, 'compliance': 100.0}
            items = []

            for r in routes:
                next_due, semaphore = _calculate_lubrication_schedule(
                    r.last_execution_date, r.frequency_days, r.warning_days
                )
                if r.is_active:
                    kpi['total'] += 1
                    if semaphore == 'VERDE':
                        kpi['green'] += 1
                    elif semaphore == 'AMARILLO':
                        kpi['yellow'] += 1
                    elif semaphore == 'ROJO':
                        kpi['red'] += 1
                    else:
                        kpi['pending'] += 1

                items.append({
                    'id': r.id,
                    'code': r.code,
                    'name': r.name,
                    'is_active': r.is_active,
                    'area_name': r.area.name if r.area else None,
                    'line_name': r.line.name if r.line else None,
                    'equipment_name': r.equipment.name if r.equipment else None,
                    'equipment_id': r.equipment_id,
                    'frequency_days': r.frequency_days,
                    'last_execution_date': r.last_execution_date,
                    'next_due_date': next_due,
                    'semaphore_status': semaphore,
                    'item_count': len([i for i in r.items if i.is_active]) if r.items else 0,
                })

            if kpi['total'] > 0:
                kpi['compliance'] = round(((kpi['total'] - kpi['red']) / kpi['total']) * 100, 1)

            items.sort(key=lambda x: (x.get('next_due_date') or '9999'))
            return jsonify({'kpi': kpi, 'items': items})
        except Exception as e:
            logger.exception("Inspection dashboard error")
            return jsonify({"error": str(e)}), 500
