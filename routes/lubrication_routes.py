import datetime as dt

from flask import jsonify, request


def register_lubrication_routes(
    app,
    db,
    logger,
    LubricationPoint,
    LubricationExecution,
    MaintenanceNotice,
    _calculate_lubrication_schedule,
):
    def _parse_date_flexible(raw):
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(str(raw), fmt).date()
            except Exception:
                pass
        return None

    def _friendly_error_message(exc, context):
        raw = str(exc or "")
        if "UndefinedColumn" in raw or "does not exist" in raw:
            return f"Error de esquema de base de datos en {context}. Ejecuta la migracion de lubricacion."
        return f"Error procesando {context}. Intenta nuevamente."

    def _generate_lubrication_code():
        last = LubricationPoint.query.order_by(LubricationPoint.id.desc()).first()
        next_id = (last.id if last else 0) + 1
        return f"LUB-{next_id:04d}"

    @app.route('/api/lubrication/points', methods=['GET', 'POST'])
    def handle_lubrication_points():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                code = data.get('code') or _generate_lubrication_code()
                last_service = data.get('last_service_date')
                frequency_days = int(data.get('frequency_days') or 30)
                warning_days = int(data.get('warning_days') or 3)
                next_due, semaphore = _calculate_lubrication_schedule(last_service, frequency_days, warning_days)

                point = LubricationPoint(
                    code=code,
                    name=data.get('name').strip(),
                    description=data.get('description'),
                    area_id=data.get('area_id'),
                    line_id=data.get('line_id'),
                    equipment_id=data.get('equipment_id'),
                    system_id=data.get('system_id'),
                    component_id=data.get('component_id'),
                    lubricant_name=data.get('lubricant_name'),
                    quantity_nominal=data.get('quantity_nominal'),
                    quantity_unit=data.get('quantity_unit') or 'L',
                    frequency_days=frequency_days,
                    warning_days=warning_days,
                    last_service_date=last_service,
                    next_due_date=next_due,
                    semaphore_status=semaphore,
                    is_active=bool(data.get('is_active', True))
                )
                db.session.add(point)
                db.session.commit()
                return jsonify(point.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception('Lubrication points POST error')
                return jsonify({"error": _friendly_error_message(e, 'puntos de lubricacion')}), 500

        show_all = request.args.get('all', 'false').lower() == 'true'
        query = LubricationPoint.query
        if not show_all:
            query = query.filter_by(is_active=True)
        points = query.order_by(LubricationPoint.id.desc()).all()
        result = []
        for p in points:
            d = p.to_dict()
            next_due, semaphore = _calculate_lubrication_schedule(
                d.get('last_service_date'),
                d.get('frequency_days'),
                d.get('warning_days')
            )
            d['next_due_date'] = next_due
            d['semaphore_status'] = semaphore
            result.append(d)
        return jsonify(result)

    @app.route('/api/lubrication/points/<int:point_id>', methods=['PUT', 'DELETE'])
    def handle_lubrication_point_id(point_id):
        point = LubricationPoint.query.get_or_404(point_id)
        if request.method == 'DELETE':
            point.is_active = False
            db.session.commit()
            return jsonify({"message": "Punto de lubricacion desactivado"})

        try:
            data = request.json or {}
            for field in [
                'code', 'name', 'description', 'area_id', 'line_id', 'equipment_id',
                'system_id', 'component_id', 'lubricant_name', 'quantity_nominal',
                'quantity_unit', 'frequency_days', 'warning_days', 'last_service_date', 'is_active'
            ]:
                if field in data:
                    setattr(point, field, data[field])

            point.frequency_days = int(point.frequency_days or 30)
            point.warning_days = int(point.warning_days or 3)
            next_due, semaphore = _calculate_lubrication_schedule(
                point.last_service_date,
                point.frequency_days,
                point.warning_days
            )
            point.next_due_date = next_due
            point.semaphore_status = semaphore
            db.session.commit()
            return jsonify(point.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.exception('Lubrication point PUT error')
            return jsonify({"error": _friendly_error_message(e, 'actualizacion de punto')}), 500

    @app.route('/api/lubrication/executions', methods=['GET', 'POST'])
    def handle_lubrication_executions():
        if request.method == 'POST':
            try:
                data = request.json or {}
                point_id = data.get('point_id')
                if not point_id:
                    return jsonify({"error": "point_id es obligatorio"}), 400
                point = LubricationPoint.query.get(point_id)
                if not point:
                    return jsonify({"error": "Punto no encontrado"}), 404

                execution_date = data.get('execution_date') or dt.date.today().isoformat()
                execution = LubricationExecution(
                    point_id=point.id,
                    execution_date=execution_date,
                    action_type=data.get('action_type') or 'SERVICIO',
                    quantity_used=data.get('quantity_used'),
                    quantity_unit=data.get('quantity_unit') or point.quantity_unit or 'L',
                    executed_by=data.get('executed_by'),
                    leak_detected=bool(data.get('leak_detected', False)),
                    anomaly_detected=bool(data.get('anomaly_detected', False)),
                    comments=data.get('comments')
                )

                point.last_service_date = execution_date
                next_due, semaphore = _calculate_lubrication_schedule(
                    point.last_service_date,
                    point.frequency_days,
                    point.warning_days
                )
                point.next_due_date = next_due
                point.semaphore_status = semaphore

                create_notice = bool(data.get('create_notice', True))
                if create_notice and (execution.leak_detected or execution.anomaly_detected):
                    notice_count = MaintenanceNotice.query.count() + 1
                    notice = MaintenanceNotice(
                        code=f"AV-{notice_count:04d}",
                        reporter_name=execution.executed_by or 'Tecnico Lubricacion',
                        reporter_type='MANTENIMIENTO',
                        area_id=point.area_id,
                        line_id=point.line_id,
                        equipment_id=point.equipment_id,
                        system_id=point.system_id,
                        component_id=point.component_id,
                        description=f"[LUBRICACION] {point.name}: {execution.comments or 'Anomalia detectada'}",
                        maintenance_type='Correctivo',
                        priority='Media',
                        status='Pendiente',
                        request_date=dt.date.today().isoformat()
                    )
                    db.session.add(notice)
                    db.session.flush()
                    execution.created_notice_id = notice.id

                db.session.add(execution)
                db.session.commit()
                return jsonify(execution.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception('Lubrication execution POST error')
                return jsonify({"error": _friendly_error_message(e, 'registro de ejecucion')}), 500

        point_id = request.args.get('point_id', type=int)
        query = LubricationExecution.query
        if point_id:
            query = query.filter_by(point_id=point_id)
        rows = query.order_by(LubricationExecution.id.desc()).limit(300).all()
        return jsonify([r.to_dict() for r in rows])

    @app.route('/api/lubrication/dashboard', methods=['GET'])
    def get_lubrication_dashboard():
        try:
            points = LubricationPoint.query.filter_by(is_active=True).all()
            kpi = {
                'total': len(points),
                'green': 0,
                'yellow': 0,
                'red': 0,
                'pending': 0,
                'due_now': 0,
                'compliance_percent': 100.0
            }
            today = dt.date.today()
            items = []
            for p in points:
                next_due, semaphore = _calculate_lubrication_schedule(
                    p.last_service_date,
                    p.frequency_days,
                    p.warning_days
                )
                due_date = _parse_date_flexible(next_due)

                if semaphore == 'VERDE':
                    kpi['green'] += 1
                elif semaphore == 'AMARILLO':
                    kpi['yellow'] += 1
                elif semaphore == 'ROJO':
                    kpi['red'] += 1
                else:
                    kpi['pending'] += 1

                if due_date and due_date <= today:
                    kpi['due_now'] += 1

                items.append({
                    'id': p.id,
                    'code': p.code,
                    'name': p.name,
                    'equipment_name': p.equipment.name if p.equipment else None,
                    'line_name': p.line.name if p.line else None,
                    'area_name': p.area.name if p.area else None,
                    'lubricant_name': p.lubricant_name,
                    'last_service_date': p.last_service_date,
                    'next_due_date': next_due,
                    'semaphore_status': semaphore,
                    'frequency_days': p.frequency_days,
                    'warning_days': p.warning_days
                })

            if kpi['total'] > 0:
                kpi['compliance_percent'] = round(((kpi['total'] - kpi['red']) / kpi['total']) * 100, 1)
            items.sort(key=lambda r: (r.get('next_due_date') or '9999-12-31'))
            return jsonify({'kpi': kpi, 'items': items[:200]})
        except Exception as e:
            logger.exception('Lubrication dashboard error')
            return jsonify({"error": _friendly_error_message(e, 'dashboard de lubricacion')}), 500
