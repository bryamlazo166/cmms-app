import datetime as dt

from flask import jsonify, request


def register_monitoring_routes(
    app,
    db,
    MonitoringPoint,
    MonitoringReading,
    MaintenanceNotice,
    _calculate_monitoring_schedule,
    _monitoring_semaphore_for_value,
    _nice_axis_step,
    _parse_date_flexible,
):
    # _generate_monitoring_code removed — code assigned after flush


    @app.route('/api/monitoring/points', methods=['GET', 'POST'])
    def handle_monitoring_points():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                frequency_days = int(data.get('frequency_days') or 7)
                warning_days = int(data.get('warning_days') or 1)
                last_measurement = data.get('last_measurement_date')
                next_due, semaphore = _calculate_monitoring_schedule(last_measurement, frequency_days, warning_days)

                point = MonitoringPoint(
                    code=data.get('code') or 'MON-TEMP',
                    name=data.get('name').strip(),
                    measurement_type=(data.get('measurement_type') or 'VIBRACION').upper(),
                    axis=(data.get('axis') or None),
                    unit=data.get('unit') or 'mm/s',
                    notes=data.get('notes'),
                    area_id=data.get('area_id'),
                    line_id=data.get('line_id'),
                    equipment_id=data.get('equipment_id'),
                    system_id=data.get('system_id'),
                    component_id=data.get('component_id'),
                    normal_min=data.get('normal_min'),
                    normal_max=data.get('normal_max'),
                    alarm_min=data.get('alarm_min'),
                    alarm_max=data.get('alarm_max'),
                    frequency_days=frequency_days,
                    warning_days=warning_days,
                    last_measurement_date=last_measurement,
                    next_due_date=next_due,
                    semaphore_status=semaphore,
                    is_active=bool(data.get('is_active', True))
                )
                db.session.add(point)
                db.session.flush()
                if point.code == 'MON-TEMP':
                    point.code = f"MON-{point.id:04d}"
                db.session.commit()
                return jsonify(point.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        show_all = request.args.get('all', 'false').lower() == 'true'
        due_filter = (request.args.get('due') or '').strip().lower()
        area_id = request.args.get('area_id', type=int)
        line_id = request.args.get('line_id', type=int)
        equipment_id = request.args.get('equipment_id', type=int)
        component_id = request.args.get('component_id', type=int)

        query = MonitoringPoint.query
        if not show_all:
            query = query.filter_by(is_active=True)
        if area_id:
            query = query.filter_by(area_id=area_id)
        if line_id:
            query = query.filter_by(line_id=line_id)
        if equipment_id:
            query = query.filter_by(equipment_id=equipment_id)
        if component_id:
            query = query.filter_by(component_id=component_id)

        points = query.order_by(MonitoringPoint.id.desc()).all()
        today = dt.date.today()
        result = []
        for p in points:
            d = p.to_dict()
            next_due, semaphore = _calculate_monitoring_schedule(
                d.get('last_measurement_date'),
                d.get('frequency_days'),
                d.get('warning_days')
            )
            d['next_due_date'] = next_due
            d['semaphore_status'] = semaphore
            due_date = _parse_date_flexible(next_due)

            if due_filter == 'overdue' and not (due_date and due_date < today):
                continue
            if due_filter == 'today' and not (due_date and due_date <= today):
                continue
            if due_filter == 'upcoming' and not (due_date and today < due_date <= today + dt.timedelta(days=7)):
                continue

            result.append(d)

        result.sort(key=lambda r: (r.get('next_due_date') or '9999-12-31', r.get('code') or ''))
        return jsonify(result)


    @app.route('/api/monitoring/points/<int:point_id>', methods=['PUT', 'DELETE'])
    def handle_monitoring_point_id(point_id):
        point = MonitoringPoint.query.get_or_404(point_id)

        if request.method == 'DELETE':
            point.is_active = False
            db.session.commit()
            return jsonify({"message": "Punto de monitoreo desactivado"})

        try:
            data = request.json or {}
            for field in [
                'code', 'name', 'measurement_type', 'axis', 'unit', 'notes',
                'area_id', 'line_id', 'equipment_id', 'system_id', 'component_id',
                'normal_min', 'normal_max', 'alarm_min', 'alarm_max',
                'frequency_days', 'warning_days', 'last_measurement_date', 'is_active'
            ]:
                if field in data:
                    setattr(point, field, data[field])

            point.frequency_days = int(point.frequency_days or 7)
            point.warning_days = int(point.warning_days or 1)
            point.measurement_type = (point.measurement_type or 'VIBRACION').upper()
            next_due, semaphore = _calculate_monitoring_schedule(
                point.last_measurement_date,
                point.frequency_days,
                point.warning_days
            )
            point.next_due_date = next_due
            point.semaphore_status = semaphore
            db.session.commit()
            return jsonify(point.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500


    @app.route('/api/monitoring/readings', methods=['GET', 'POST'])
    def handle_monitoring_readings():
        if request.method == 'POST':
            try:
                data = request.json or {}
                point_id = data.get('point_id')
                if not point_id:
                    return jsonify({"error": "point_id es obligatorio"}), 400
                if data.get('value') is None:
                    return jsonify({"error": "value es obligatorio"}), 400

                point = MonitoringPoint.query.get(point_id)
                if not point:
                    return jsonify({"error": "Punto no encontrado"}), 404

                reading_date = data.get('reading_date') or dt.date.today().isoformat()
                reading = MonitoringReading(
                    point_id=point.id,
                    reading_date=reading_date,
                    value=float(data.get('value')),
                    executed_by=data.get('executed_by'),
                    notes=data.get('notes'),
                    photo_url=data.get('photo_url'),
                    is_regularization=bool(data.get('is_regularization', False))
                )

                # Update point schedule and status from measured value
                point.last_measurement_date = reading_date
                next_due, schedule_status = _calculate_monitoring_schedule(
                    point.last_measurement_date,
                    point.frequency_days,
                    point.warning_days
                )
                value_status = _monitoring_semaphore_for_value(point, reading.value)
                point.next_due_date = next_due
                point.semaphore_status = value_status if value_status == 'ROJO' else schedule_status

                create_notice = bool(data.get('create_notice', True))
                if create_notice and value_status == 'ROJO':
                    notice = MaintenanceNotice(
                        reporter_name=reading.executed_by or "Tecnico Monitoreo",
                        reporter_type="MONITOREO",
                        area_id=point.area_id,
                        line_id=point.line_id,
                        equipment_id=point.equipment_id,
                        system_id=point.system_id,
                        component_id=point.component_id,
                        description=f"[MONITOREO] {point.name}: valor {reading.value} {point.unit}",
                        maintenance_type="Predictivo",
                        priority="Alta",
                        status="Pendiente",
                        request_date=dt.date.today().isoformat()
                    )
                    db.session.add(notice)
                    db.session.flush()
                    notice.code = f"AV-{notice.id:04d}"
                    reading.created_notice_id = notice.id

                db.session.add(reading)
                db.session.commit()
                payload = reading.to_dict()
                payload['value_status'] = value_status
                payload['schedule_status'] = schedule_status
                return jsonify(payload), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        point_id = request.args.get('point_id', type=int)
        limit = max(1, min(int(request.args.get('limit', 300)), 1000))
        query = MonitoringReading.query
        if point_id:
            query = query.filter_by(point_id=point_id)
        rows = query.order_by(MonitoringReading.id.desc()).limit(limit).all()
        return jsonify([r.to_dict() for r in rows])


    @app.route('/api/monitoring/dashboard', methods=['GET'])
    def get_monitoring_dashboard():
        try:
            area_id = request.args.get('area_id', type=int)
            line_id = request.args.get('line_id', type=int)
            equipment_id = request.args.get('equipment_id', type=int)
            selected_point_id = request.args.get('point_id', type=int)

            query = MonitoringPoint.query.filter_by(is_active=True)
            if area_id:
                query = query.filter_by(area_id=area_id)
            if line_id:
                query = query.filter_by(line_id=line_id)
            if equipment_id:
                query = query.filter_by(equipment_id=equipment_id)

            points = query.order_by(MonitoringPoint.id.asc()).all()
            today = dt.date.today()

            kpi = {
                "total_points": len(points),
                "due_today": 0,
                "overdue": 0,
                "upcoming": 0,
                "green": 0,
                "yellow": 0,
                "red": 0,
                "pending": 0
            }
            pending_rows = []
            for p in points:
                next_due, schedule_status = _calculate_monitoring_schedule(
                    p.last_measurement_date, p.frequency_days, p.warning_days
                )
                due_date = _parse_date_flexible(next_due)
                status = p.semaphore_status or schedule_status

                if status == 'VERDE':
                    kpi['green'] += 1
                elif status == 'AMARILLO':
                    kpi['yellow'] += 1
                elif status == 'ROJO':
                    kpi['red'] += 1
                else:
                    kpi['pending'] += 1

                if due_date:
                    if due_date < today:
                        kpi['overdue'] += 1
                    if due_date <= today:
                        kpi['due_today'] += 1
                        pending_rows.append({
                            "point_id": p.id,
                            "code": p.code,
                            "name": p.name,
                            "measurement_type": p.measurement_type,
                            "axis": p.axis,
                            "unit": p.unit,
                            "next_due_date": next_due,
                            "equipment_name": p.equipment.name if p.equipment else "-",
                            "line_name": p.line.name if p.line else "-",
                            "area_name": p.area.name if p.area else "-",
                            "semaphore_status": status
                        })
                    elif due_date <= today + dt.timedelta(days=7):
                        kpi['upcoming'] += 1

            pending_rows.sort(key=lambda r: (r.get('next_due_date') or '9999-12-31', r.get('code') or ''))

            if not selected_point_id and points:
                selected_point_id = points[0].id

            trend = []
            y_min = 0.0
            y_max = 10.0
            y_step = 2.0
            if selected_point_id:
                rows = MonitoringReading.query.filter_by(point_id=selected_point_id)\
                    .order_by(MonitoringReading.reading_date.desc(), MonitoringReading.id.desc())\
                    .limit(30).all()
                rows = list(reversed(rows))
                trend = [{
                    "reading_date": r.reading_date,
                    "value": r.value,
                    "executed_by": r.executed_by,
                    "notes": r.notes
                } for r in rows]
                if trend:
                    values = [float(t['value']) for t in trend]
                    vmin = min(values)
                    vmax = max(values)
                    if abs(vmax - vmin) < 1e-9:
                        pad = max(0.5, abs(vmax) * 0.2, 1.0)
                    else:
                        pad = max((vmax - vmin) * 0.2, 0.5)
                    y_min = vmin - pad
                    y_max = vmax + pad
                    y_step = _nice_axis_step(max((y_max - y_min) / 6, 0.1))
                    y_step = round(y_step, 4)

            return jsonify({
                "kpi": kpi,
                "pending_rows": pending_rows[:300],
                "selected_point_id": selected_point_id,
                "trend": trend,
                "trend_axis": {
                    "min": round(y_min, 4),
                    "max": round(y_max, 4),
                    "step": y_step
                }
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500



