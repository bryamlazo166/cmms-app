from datetime import datetime

from flask import jsonify, request


# Catalogos de valores validos (espejo de los usados en el frontend)
VALID_TYPES = {'COMPRA_ESPECIAL', 'FABRICACION', 'MEJORA', 'REPUESTO_ESTRATEGICO'}
VALID_PRIORITIES = {'BAJA', 'MEDIA', 'ALTA'}
VALID_STATUSES = {
    'REGISTRADO', 'EN_EVALUACION', 'APROBADO', 'EN_GESTION', 'CERRADO', 'RECHAZADO'
}


def register_requirements_routes(
    app,
    db,
    Requirement,
    WorkOrder,
    PurchaseRequest,
):
    """Modulo 'Requerimientos' (backlog tecnico).

    Necesidades reconocidas pero NO planificadas: compras especiales,
    fabricaciones, mejoras/upgrades y repuestos estrategicos sin OT ni aviso.
    """

    @app.route('/api/requirements', methods=['GET', 'POST'])
    def handle_requirements():
        if request.method == 'POST':
            try:
                data = request.json or {}

                if not (data.get('title') or '').strip():
                    return jsonify({"error": "El titulo es obligatorio."}), 400

                req_type = data.get('req_type')
                if req_type not in VALID_TYPES:
                    return jsonify({"error": f"Tipo invalido. Use uno de: {', '.join(sorted(VALID_TYPES))}"}), 400

                priority = data.get('priority') or 'MEDIA'
                if priority not in VALID_PRIORITIES:
                    return jsonify({"error": "Prioridad invalida."}), 400

                r = Requirement(
                    code='RQM-TEMP',
                    title=data['title'].strip(),
                    description=data.get('description') or None,
                    req_type=req_type,
                    priority=priority,
                    status='REGISTRADO',
                    area_id=data.get('area_id') or None,
                    line_id=data.get('line_id') or None,
                    equipment_id=data.get('equipment_id') or None,
                    estimated_cost=data.get('estimated_cost') or None,
                    quantity=data.get('quantity') or None,
                    unit=data.get('unit') or None,
                    target_date=data.get('target_date') or None,
                    requested_by=data.get('requested_by') or None,
                    justification=data.get('justification') or None,
                    notes=data.get('notes') or None,
                )
                db.session.add(r)
                db.session.flush()
                r.code = f"RQM-2026-{r.id:04d}"
                db.session.commit()
                return jsonify(r.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET — listado con filtros opcionales
        q = Requirement.query
        status = request.args.get('status')
        req_type = request.args.get('req_type')
        priority = request.args.get('priority')
        equipment_id = request.args.get('equipment_id')
        # Por defecto se ocultan los terminales salvo ?all=true
        show_all = request.args.get('all', 'false') == 'true'

        if status:
            q = q.filter(Requirement.status == status)
        elif not show_all:
            q = q.filter(Requirement.status.notin_(['CERRADO', 'RECHAZADO']))
        if req_type:
            q = q.filter(Requirement.req_type == req_type)
        if priority:
            q = q.filter(Requirement.priority == priority)
        if equipment_id:
            q = q.filter(Requirement.equipment_id == int(equipment_id))

        items = q.order_by(Requirement.id.desc()).all()
        return jsonify([r.to_dict() for r in items])

    @app.route('/api/requirements/<int:id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_requirement(id):
        r = Requirement.query.get(id)
        if not r:
            return jsonify({"error": "Requerimiento no encontrado"}), 404

        if request.method == 'GET':
            return jsonify(r.to_dict())

        if request.method == 'PUT':
            try:
                data = request.json or {}

                if 'req_type' in data and data['req_type'] not in VALID_TYPES:
                    return jsonify({"error": "Tipo invalido."}), 400
                if 'priority' in data and data['priority'] not in VALID_PRIORITIES:
                    return jsonify({"error": "Prioridad invalida."}), 400
                if 'status' in data and data['status'] not in VALID_STATUSES:
                    return jsonify({"error": "Estado invalido."}), 400

                editable = [
                    'title', 'description', 'req_type', 'priority', 'status',
                    'area_id', 'line_id', 'equipment_id', 'estimated_cost',
                    'quantity', 'unit', 'target_date', 'requested_by',
                    'justification', 'notes',
                ]
                for f in editable:
                    if f in data:
                        val = data.get(f)
                        setattr(r, f, val if val != '' else None)

                # Si pasa a estado terminal manualmente, sellar closed_at
                if r.status in ('CERRADO', 'RECHAZADO') and not r.closed_at:
                    r.closed_at = datetime.utcnow()
                elif r.status not in ('CERRADO', 'RECHAZADO'):
                    r.closed_at = None

                db.session.commit()
                return jsonify(r.to_dict())
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        if request.method == 'DELETE':
            try:
                db.session.delete(r)
                db.session.commit()
                return jsonify({"msg": "Requerimiento eliminado"})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

    @app.route('/api/requirements/<int:id>/convert', methods=['POST'])
    def convert_requirement(id):
        """Promueve un requerimiento a OT, a Requisicion de compra, o lo cierra.

        body: { "target": "OT" | "REQ" | "MANUAL", ... }
          - OT:     genera un WorkOrder standalone (sin notice) ligado al requerimiento
          - REQ:    genera un PurchaseRequest (compra sin OT) ligado al requerimiento
          - MANUAL: marca el requerimiento como CERRADO sin generar nada
        """
        r = Requirement.query.get(id)
        if not r:
            return jsonify({"error": "Requerimiento no encontrado"}), 404

        if r.status in ('CERRADO', 'RECHAZADO'):
            return jsonify({"error": "El requerimiento ya esta cerrado."}), 400

        data = request.json or {}
        target = (data.get('target') or '').upper()

        try:
            if target == 'OT':
                wo = WorkOrder(
                    code='OT-TEMP',
                    area_id=r.area_id,
                    line_id=r.line_id,
                    equipment_id=r.equipment_id,
                    description=data.get('description') or f"[{r.code}] {r.title}",
                    maintenance_type=data.get('maintenance_type') or 'Correctivo',
                    status='Abierta',
                )
                db.session.add(wo)
                db.session.flush()
                wo.code = f"OT-{wo.id:04d}"

                r.work_order_id = wo.id
                r.converted_to_type = 'OT'
                r.status = 'EN_GESTION'
                db.session.commit()
                return jsonify({
                    "msg": f"OT {wo.code} creada desde {r.code}",
                    "work_order": wo.to_dict(),
                    "requirement": r.to_dict(),
                }), 201

            if target == 'REQ':
                pr = PurchaseRequest(
                    req_code='REQ-TEMP',
                    work_order_id=None,
                    requirement_id=r.id,
                    item_type=data.get('item_type') or 'SERVICIO',
                    description=data.get('description') or f"[{r.code}] {r.title}",
                    quantity=data.get('quantity') or r.quantity or 1,
                )
                db.session.add(pr)
                db.session.flush()
                pr.req_code = f"REQ-2026-{pr.id:04d}"

                r.converted_to_type = 'REQ'
                r.status = 'EN_GESTION'
                db.session.commit()
                return jsonify({
                    "msg": f"Requisicion {pr.req_code} creada desde {r.code}",
                    "purchase_request": pr.to_dict(),
                    "requirement": r.to_dict(),
                }), 201

            if target == 'MANUAL':
                r.converted_to_type = 'MANUAL'
                r.status = 'CERRADO'
                r.closed_at = datetime.utcnow()
                db.session.commit()
                return jsonify({
                    "msg": f"{r.code} cerrado manualmente",
                    "requirement": r.to_dict(),
                })

            return jsonify({"error": "target invalido. Use OT, REQ o MANUAL."}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
