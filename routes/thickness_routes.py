"""Rutas para inspección de espesores por ultrasonido (UT)."""
import datetime as dt

from flask import jsonify, request


def register_thickness_routes(
    app,
    db,
    logger,
    ThicknessPoint,
    ThicknessInspection,
    ThicknessReading,
    Equipment,
    MaintenanceNotice=None,
):

    def _today():
        return dt.date.today().isoformat()

    def _calc_status(value, point):
        """Devuelve (status, is_alert, is_critical) según el valor y los umbrales del punto."""
        if value is None:
            return ('NORMAL', False, False)
        if value <= point.scrap_thickness:
            return ('CRITICO', False, True)
        if value <= point.alarm_thickness:
            return ('ALERTA', True, False)
        return ('NORMAL', False, False)

    def _semaphore_for_equipment(equipment_id):
        """Calcula el semáforo de la próxima inspección programada del equipo."""
        last = ThicknessInspection.query.filter_by(equipment_id=equipment_id) \
            .order_by(ThicknessInspection.inspection_date.desc()).first()
        if not last or not last.next_due_date:
            return ('PENDIENTE', None)
        try:
            due = dt.date.fromisoformat(last.next_due_date)
            today = dt.date.today()
            days_left = (due - today).days
            if days_left < 0:
                return ('ROJO', days_left)
            if days_left <= 10:
                return ('AMARILLO', days_left)
            return ('VERDE', days_left)
        except Exception:
            return ('PENDIENTE', None)

    # ── CATALOGO DE PUNTOS ─────────────────────────────────────────────────
    @app.route('/api/thickness/points/<int:equipment_id>', methods=['GET', 'POST'])
    def handle_thickness_points(equipment_id):
        if request.method == 'POST':
            try:
                data = request.json or {}
                pt = ThicknessPoint(
                    equipment_id=equipment_id,
                    component_id=data.get('component_id'),
                    group_name=data.get('group_name', '').upper(),
                    section=data.get('section'),
                    position=data.get('position', '').upper(),
                    nominal_thickness=float(data.get('nominal_thickness', 25.4)),
                    alarm_thickness=float(data.get('alarm_thickness', 10.0)),
                    scrap_thickness=float(data.get('scrap_thickness', 8.0)),
                    order_index=data.get('order_index', 0),
                )
                db.session.add(pt)
                db.session.commit()
                return jsonify(pt.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        # GET
        points = ThicknessPoint.query.filter_by(
            equipment_id=equipment_id, is_active=True
        ).order_by(ThicknessPoint.group_name, ThicknessPoint.section, ThicknessPoint.order_index).all()
        return jsonify([p.to_dict() for p in points])

    @app.route('/api/thickness/points/<int:point_id>/edit', methods=['PUT'])
    def update_thickness_point(point_id):
        try:
            pt = ThicknessPoint.query.get_or_404(point_id)
            data = request.json or {}
            for key in ('nominal_thickness', 'alarm_thickness', 'scrap_thickness'):
                if key in data:
                    setattr(pt, key, float(data[key]))
            db.session.commit()
            return jsonify(pt.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── INSPECCIONES ───────────────────────────────────────────────────────
    @app.route('/api/thickness/inspections', methods=['GET', 'POST'])
    def handle_thickness_inspections():
        if request.method == 'POST':
            try:
                data = request.json or {}
                equipment_id = int(data['equipment_id'])
                inspection_date = data.get('inspection_date') or _today()
                frequency_days = int(data.get('frequency_days', 60))
                inspector = data.get('inspector_name')
                observations = data.get('observations')
                readings_data = data.get('readings', [])

                # Calcular next_due_date
                try:
                    insp_dt = dt.date.fromisoformat(inspection_date)
                except Exception:
                    insp_dt = dt.date.today()
                next_due = (insp_dt + dt.timedelta(days=frequency_days)).isoformat()

                # Crear inspección
                inspection = ThicknessInspection(
                    equipment_id=equipment_id,
                    inspection_date=inspection_date,
                    next_due_date=next_due,
                    frequency_days=frequency_days,
                    inspector_name=inspector,
                    status='COMPLETA',
                    observations=observations,
                    pdf_url=(data.get('pdf_url') or None),
                )
                db.session.add(inspection)
                db.session.flush()  # obtener id

                total = 0
                criticals = 0
                alerts = 0
                critical_details = []
                # Crear readings
                for r in readings_data:
                    point_id = int(r.get('point_id'))
                    value = r.get('value_mm')
                    if value is None or value == '':
                        continue
                    try:
                        value = float(value)
                    except Exception:
                        continue
                    pt = ThicknessPoint.query.get(point_id)
                    if not pt or pt.equipment_id != equipment_id:
                        continue
                    status, is_alert, is_critical = _calc_status(value, pt)
                    rd = ThicknessReading(
                        inspection_id=inspection.id,
                        point_id=point_id,
                        value_mm=value,
                        is_alert=is_alert,
                        is_critical=is_critical,
                    )
                    db.session.add(rd)
                    # Actualizar punto
                    pt.last_value = value
                    pt.last_date = inspection_date
                    pt.status = status
                    total += 1
                    if is_critical:
                        criticals += 1
                        critical_details.append(f"{pt.group_name} S{pt.section or ''}-{pt.position}: {value}mm (límite {pt.scrap_thickness}mm)")
                    elif is_alert:
                        alerts += 1

                inspection.total_points = total
                inspection.critical_points = criticals
                inspection.alert_points = alerts
                if criticals > 0:
                    inspection.semaphore_status = 'ROJO'
                elif alerts > 0:
                    inspection.semaphore_status = 'AMARILLO'
                else:
                    inspection.semaphore_status = 'VERDE'

                db.session.commit()

                # Generar aviso automático si hay puntos críticos
                if criticals > 0 and MaintenanceNotice:
                    try:
                        eq = Equipment.query.get(equipment_id)
                        eq_name = eq.name if eq else f"Equipo {equipment_id}"
                        desc = (f"Inspección UT detectó {criticals} punto(s) crítico(s) en {eq_name}.\n"
                                f"Detalles:\n- " + "\n- ".join(critical_details[:10]))
                        notice = MaintenanceNotice(
                            description=desc,
                            equipment_id=equipment_id,
                            criticality='Alta',
                            priority='Alta',
                            maintenance_type='Correctivo',
                            failure_category='Estructural',
                            failure_mode='Desgaste',
                            status='Pendiente',
                            scope='PLAN',
                            reporter_name=inspector or 'Sistema UT',
                        )
                        db.session.add(notice)
                        db.session.flush()
                        notice.code = f"AV-{notice.id:04d}"
                        db.session.commit()
                    except Exception as ne:
                        logger.warning(f"thickness: error al crear aviso automático: {ne}")
                        db.session.rollback()

                return jsonify(inspection.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creando inspección espesores: {e}")
                return jsonify({"error": str(e)}), 500

        # GET — listar inspecciones (filtrar por equipment_id opcional)
        equipment_id = request.args.get('equipment_id', type=int)
        q = ThicknessInspection.query
        if equipment_id:
            q = q.filter_by(equipment_id=equipment_id)
        inspections = q.order_by(ThicknessInspection.inspection_date.desc()).limit(100).all()
        return jsonify([i.to_dict() for i in inspections])

    @app.route('/api/thickness/inspections/<int:inspection_id>/pdf', methods=['PUT'])
    def update_thickness_pdf_url(inspection_id):
        try:
            inspection = ThicknessInspection.query.get_or_404(inspection_id)
            data = request.json or {}
            url = (data.get('pdf_url') or '').strip()
            if not url:
                return jsonify({"error": "pdf_url requerido"}), 400
            inspection.pdf_url = url
            db.session.commit()
            return jsonify(inspection.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/thickness/inspections/<int:inspection_id>/edit', methods=['PUT'])
    def edit_thickness_inspection(inspection_id):
        """Editar una inspección existente: actualiza metadata + reemplaza readings."""
        try:
            inspection = ThicknessInspection.query.get_or_404(inspection_id)
            data = request.json or {}
            equipment_id = inspection.equipment_id

            # Actualizar metadata
            if 'inspection_date' in data:
                inspection.inspection_date = data['inspection_date']
                freq = inspection.frequency_days or 60
                try:
                    insp_dt = dt.date.fromisoformat(data['inspection_date'])
                    inspection.next_due_date = (insp_dt + dt.timedelta(days=freq)).isoformat()
                except Exception:
                    pass
            if 'inspector_name' in data:
                inspection.inspector_name = data['inspector_name']
            if 'observations' in data:
                inspection.observations = data['observations']
            if 'pdf_url' in data:
                inspection.pdf_url = data.get('pdf_url') or None

            readings_data = data.get('readings', [])
            if readings_data:
                # Eliminar readings anteriores
                ThicknessReading.query.filter_by(inspection_id=inspection_id).delete()

                total = 0
                criticals = 0
                alerts = 0
                for r in readings_data:
                    point_id = int(r.get('point_id'))
                    value = r.get('value_mm')
                    if value is None or value == '':
                        continue
                    try:
                        value = float(value)
                    except Exception:
                        continue
                    pt = ThicknessPoint.query.get(point_id)
                    if not pt or pt.equipment_id != equipment_id:
                        continue
                    status, is_alert, is_critical = _calc_status(value, pt)
                    rd = ThicknessReading(
                        inspection_id=inspection_id,
                        point_id=point_id,
                        value_mm=value,
                        is_alert=is_alert,
                        is_critical=is_critical,
                    )
                    db.session.add(rd)
                    pt.last_value = value
                    pt.last_date = inspection.inspection_date
                    pt.status = status
                    total += 1
                    if is_critical:
                        criticals += 1
                    elif is_alert:
                        alerts += 1

                inspection.total_points = total
                inspection.critical_points = criticals
                inspection.alert_points = alerts
                if criticals > 0:
                    inspection.semaphore_status = 'ROJO'
                elif alerts > 0:
                    inspection.semaphore_status = 'AMARILLO'
                else:
                    inspection.semaphore_status = 'VERDE'

            db.session.commit()
            return jsonify(inspection.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error editando inspección espesores: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/thickness/inspections/<int:inspection_id>', methods=['GET', 'DELETE'])
    def handle_thickness_inspection_detail(inspection_id):
        inspection = ThicknessInspection.query.get_or_404(inspection_id)
        if request.method == 'DELETE':
            try:
                ThicknessReading.query.filter_by(inspection_id=inspection_id).delete()
                db.session.delete(inspection)
                db.session.commit()
                return jsonify({"message": "Inspección eliminada"})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        # GET con readings
        readings = ThicknessReading.query.filter_by(inspection_id=inspection_id).all()
        result = inspection.to_dict()
        result['readings'] = [r.to_dict() for r in readings]
        return jsonify(result)

    # ── DASHBOARD ──────────────────────────────────────────────────────────
    @app.route('/api/thickness/dashboard', methods=['GET'])
    def thickness_dashboard():
        try:
            # Equipos con puntos catalogados
            equipment_ids = db.session.query(ThicknessPoint.equipment_id).distinct().all()
            equipment_ids = [e[0] for e in equipment_ids]
            equipos = []
            for eq_id in equipment_ids:
                eq = Equipment.query.get(eq_id)
                if not eq:
                    continue
                last = ThicknessInspection.query.filter_by(equipment_id=eq_id) \
                    .order_by(ThicknessInspection.inspection_date.desc()).first()
                semaphore, days_left = _semaphore_for_equipment(eq_id)
                point_count = ThicknessPoint.query.filter_by(equipment_id=eq_id, is_active=True).count()
                critical_count = ThicknessPoint.query.filter_by(equipment_id=eq_id, status='CRITICO', is_active=True).count()
                alert_count = ThicknessPoint.query.filter_by(equipment_id=eq_id, status='ALERTA', is_active=True).count()
                equipos.append({
                    "equipment_id": eq_id,
                    "equipment_name": eq.name,
                    "equipment_tag": eq.tag,
                    "last_inspection_date": last.inspection_date if last else None,
                    "next_due_date": last.next_due_date if last else None,
                    "days_left": days_left,
                    "semaphore_status": semaphore,
                    "point_count": point_count,
                    "critical_count": critical_count,
                    "alert_count": alert_count,
                })
            equipos.sort(key=lambda x: (x['equipment_tag'] or ''))
            return jsonify({"equipos": equipos, "total": len(equipos)})
        except Exception as e:
            logger.error(f"thickness_dashboard error: {e}")
            return jsonify({"equipos": [], "total": 0, "error": str(e)}), 200

    # ── HISTORICO POR PUNTO ────────────────────────────────────────────────
    @app.route('/api/thickness/history/<int:point_id>', methods=['GET'])
    def thickness_point_history(point_id):
        readings = db.session.query(ThicknessReading, ThicknessInspection) \
            .join(ThicknessInspection, ThicknessReading.inspection_id == ThicknessInspection.id) \
            .filter(ThicknessReading.point_id == point_id) \
            .order_by(ThicknessInspection.inspection_date.asc()).all()
        return jsonify([{
            "value_mm": r.value_mm,
            "inspection_date": i.inspection_date,
            "is_critical": r.is_critical,
            "is_alert": r.is_alert,
        } for r, i in readings])
