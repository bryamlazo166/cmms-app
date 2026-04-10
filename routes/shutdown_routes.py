"""Rutas para gestión de paradas de planta (domingos de mantenimiento)."""
from flask import jsonify, request
from datetime import datetime


def register_shutdown_routes(
    app, db, logger,
    Shutdown, ShutdownArea, WorkOrder, Area, Equipment, Line,
    OTPersonnel, Technician,
):

    @app.route('/api/shutdowns', methods=['GET', 'POST'])
    def handle_shutdowns():
        if request.method == 'POST':
            try:
                data = request.json or {}
                from flask_login import current_user
                shutdown = Shutdown(
                    name=data.get('name', ''),
                    shutdown_date=data['shutdown_date'],
                    shutdown_type=data.get('shutdown_type', 'TOTAL'),
                    start_time=data.get('start_time', '07:00'),
                    end_time=data.get('end_time', '19:00'),
                    overtime=data.get('overtime', False),
                    status='PLANIFICADA',
                    production_requirements=data.get('production_requirements'),
                    observations=data.get('observations'),
                    created_by=current_user.full_name if hasattr(current_user, 'full_name') else None,
                )
                db.session.add(shutdown)
                db.session.flush()

                # Agregar áreas seleccionadas
                area_ids = data.get('area_ids', [])
                for aid in area_ids:
                    sa = ShutdownArea(shutdown_id=shutdown.id, area_id=int(aid))
                    db.session.add(sa)

                # Auto-generar nombre si vacío
                if not shutdown.name:
                    area_names = []
                    for aid in area_ids:
                        a = Area.query.get(int(aid))
                        if a:
                            area_names.append(a.name)
                    type_label = 'Parada Total' if shutdown.shutdown_type == 'TOTAL' else 'Parada Parcial'
                    if area_names and shutdown.shutdown_type == 'PARCIAL':
                        type_label += f' ({", ".join(area_names)})'
                    shutdown.name = f"{type_label} — {shutdown.shutdown_date}"

                db.session.commit()
                return jsonify(shutdown.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creando parada: {e}")
                return jsonify({"error": str(e)}), 500

        # GET
        year = request.args.get('year', type=int)
        status = request.args.get('status')
        q = Shutdown.query
        if year:
            q = q.filter(Shutdown.shutdown_date.like(f'{year}-%'))
        if status:
            q = q.filter_by(status=status)
        shutdowns = q.order_by(Shutdown.shutdown_date.desc()).limit(50).all()
        # Enriquecer con conteo de OTs
        result = []
        for s in shutdowns:
            d = s.to_dict()
            ot_count = WorkOrder.query.filter_by(shutdown_id=s.id).count()
            ot_closed = WorkOrder.query.filter_by(shutdown_id=s.id, status='Cerrada').count()
            d['ot_count'] = ot_count
            d['ot_closed'] = ot_closed
            d['compliance'] = round((ot_closed / ot_count * 100) if ot_count else 0, 1)
            # Horas estimadas
            from sqlalchemy import func
            total_hrs = db.session.query(func.coalesce(func.sum(WorkOrder.estimated_duration), 0)) \
                .filter(WorkOrder.shutdown_id == s.id).scalar()
            d['total_hours'] = float(total_hrs or 0)
            result.append(d)
        return jsonify(result)

    @app.route('/api/shutdowns/<int:shutdown_id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_shutdown_detail(shutdown_id):
        shutdown = Shutdown.query.get_or_404(shutdown_id)

        if request.method == 'DELETE':
            try:
                # Desvincular OTs
                WorkOrder.query.filter_by(shutdown_id=shutdown_id).update({"shutdown_id": None})
                ShutdownArea.query.filter_by(shutdown_id=shutdown_id).delete()
                db.session.delete(shutdown)
                db.session.commit()
                return jsonify({"message": "Parada eliminada"})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        if request.method == 'PUT':
            try:
                data = request.json or {}
                for key in ('name', 'shutdown_date', 'shutdown_type', 'start_time', 'end_time',
                            'status', 'production_requirements', 'observations', 'overtime'):
                    if key in data:
                        setattr(shutdown, key, data[key])
                # Actualizar áreas si vienen
                if 'area_ids' in data:
                    ShutdownArea.query.filter_by(shutdown_id=shutdown_id).delete()
                    for aid in data['area_ids']:
                        db.session.add(ShutdownArea(shutdown_id=shutdown_id, area_id=int(aid)))
                db.session.commit()
                return jsonify(shutdown.to_dict())
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET — detalle completo con OTs agrupadas por área
        d = shutdown.to_dict()
        ots = WorkOrder.query.filter_by(shutdown_id=shutdown_id).all()
        # Resolver nombres
        area_map = {a.id: a.name for a in Area.query.all()}
        line_map = {l.id: l for l in Line.query.all()}
        equip_map = {e.id: e for e in Equipment.query.all()}
        tech_map = {str(t.id): t.name for t in Technician.query.all()}

        ot_list = []
        for ot in ots:
            od = ot.to_dict()
            od['area_name'] = area_map.get(ot.area_id, '-')
            eq = equip_map.get(ot.equipment_id)
            od['equipment_name'] = eq.name if eq else '-'
            od['equipment_tag'] = eq.tag if eq else '-'
            ln = line_map.get(ot.line_id)
            od['line_name'] = ln.name if ln else '-'
            if not od.get('area_name') or od['area_name'] == '-':
                if ln:
                    od['area_name'] = area_map.get(ln.area_id, '-')
            od['technician_name'] = tech_map.get(str(ot.technician_id), ot.technician_id or '-')
            # Personal asignado
            personnel = OTPersonnel.query.filter_by(work_order_id=ot.id).all()
            od['personnel'] = [{'name': tech_map.get(str(p.technician_id), '-'), 'hours': p.hours_assigned}
                               for p in personnel]
            ot_list.append(od)

        # Agrupar por área
        by_area = {}
        for ot in ot_list:
            area = ot.get('area_name', 'Sin Área')
            if area not in by_area:
                by_area[area] = []
            by_area[area].append(ot)

        d['work_orders'] = ot_list
        d['by_area'] = by_area
        d['ot_count'] = len(ot_list)
        d['ot_closed'] = sum(1 for o in ot_list if o.get('status') == 'Cerrada')
        d['compliance'] = round((d['ot_closed'] / d['ot_count'] * 100) if d['ot_count'] else 0, 1)
        from sqlalchemy import func
        d['total_hours'] = float(db.session.query(
            func.coalesce(func.sum(WorkOrder.estimated_duration), 0)
        ).filter(WorkOrder.shutdown_id == shutdown_id).scalar() or 0)
        # Conteo técnicos
        tech_ids = set()
        for ot in ots:
            if ot.technician_id:
                tech_ids.add(ot.technician_id)
            for p in OTPersonnel.query.filter_by(work_order_id=ot.id).all():
                if p.technician_id:
                    tech_ids.add(str(p.technician_id))
        d['technician_count'] = len(tech_ids)
        return jsonify(d)

    @app.route('/api/shutdowns/<int:shutdown_id>/add-ot', methods=['POST'])
    def add_ot_to_shutdown(shutdown_id):
        """Vincular OT(s) existentes a una parada."""
        try:
            data = request.json or {}
            ot_ids = data.get('ot_ids', [])
            if not ot_ids:
                return jsonify({"error": "ot_ids requeridos"}), 400
            count = 0
            for oid in ot_ids:
                ot = WorkOrder.query.get(int(oid))
                if ot:
                    ot.shutdown_id = shutdown_id
                    count += 1
            db.session.commit()
            return jsonify({"message": f"{count} OTs vinculadas"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/remove-ot/<int:ot_id>', methods=['DELETE'])
    def remove_ot_from_shutdown(shutdown_id, ot_id):
        """Desvincular OT de una parada."""
        try:
            ot = WorkOrder.query.get_or_404(ot_id)
            if ot.shutdown_id == shutdown_id:
                ot.shutdown_id = None
                db.session.commit()
            return jsonify({"message": "OT desvinculada"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/suggestions', methods=['GET'])
    def get_shutdown_suggestions(shutdown_id):
        """OTs abiertas/pendientes que podrían agregarse a esta parada."""
        try:
            shutdown = Shutdown.query.get_or_404(shutdown_id)
            area_ids = [sa.area_id for sa in shutdown.areas]
            q = WorkOrder.query.filter(
                WorkOrder.status.in_(['Abierta', 'Programada']),
                WorkOrder.shutdown_id.is_(None),
            )
            if area_ids and shutdown.shutdown_type == 'PARCIAL':
                q = q.filter(WorkOrder.area_id.in_(area_ids))
            candidates = q.order_by(WorkOrder.id.desc()).limit(50).all()

            area_map = {a.id: a.name for a in Area.query.all()}
            equip_map = {e.id: e for e in Equipment.query.all()}
            result = []
            for ot in candidates:
                od = ot.to_dict()
                od['area_name'] = area_map.get(ot.area_id, '-')
                eq = equip_map.get(ot.equipment_id)
                od['equipment_name'] = eq.name if eq else '-'
                od['equipment_tag'] = eq.tag if eq else '-'
                result.append(od)
            return jsonify(result)
        except Exception as e:
            return jsonify([])
