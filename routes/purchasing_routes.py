from datetime import datetime

from flask import jsonify, request


def register_purchasing_routes(
    app,
    db,
    PurchaseRequest,
    PurchaseOrder,
    WarehouseItem,
    WarehouseMovement,
):
    @app.route('/api/purchase-requests', methods=['GET', 'POST'])
    def handle_requests():
        if request.method == 'POST':
            try:
                data = request.json

                if data['item_type'] == 'SERVICIO' and not data.get('description'):
                    return jsonify({"error": "Descripcion obligatoria para Servicios"}), 400

                if data['item_type'] == 'MATERIAL' and not data.get('spare_part_id') and not data.get('warehouse_item_id'):
                    return jsonify({"error": "Debe seleccionar un item del almacen."}), 400

                req = PurchaseRequest(
                    req_code='REQ-TEMP',
                    work_order_id=data['work_order_id'],
                    item_type=data['item_type'],
                    spare_part_id=data.get('spare_part_id'),
                    warehouse_item_id=data.get('warehouse_item_id'),
                    description=data.get('description'),
                    quantity=data['quantity']
                )
                db.session.add(req)
                db.session.flush()
                req.req_code = f"REQ-2026-{req.id:04d}"
                db.session.commit()
                return jsonify(req.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        show_all = request.args.get('all', 'false') == 'true'
        if show_all:
            reqs = PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).all()
        else:
            reqs = PurchaseRequest.query.filter(PurchaseRequest.status != 'RECIBIDO').order_by(PurchaseRequest.id.desc()).all()

        return jsonify([r.to_dict() for r in reqs])

    @app.route('/api/purchase-orders', methods=['GET', 'POST'])
    def handle_orders():
        if request.method == 'POST':
            try:
                data = request.json
                provider = data.get('provider_name')
                req_ids = data.get('request_ids', [])

                if not req_ids:
                    return jsonify({"error": "No requests selected"}), 400

                po = PurchaseOrder(
                    po_code='OC-TEMP',
                    provider_name=provider,
                    status='EMITIDA'
                )
                db.session.add(po)
                db.session.flush()
                po.po_code = f"OC-2026-{po.id:03d}"

                for rid in req_ids:
                    req = PurchaseRequest.query.get(rid)
                    if req:
                        req.purchase_order_id = po.id
                        req.status = 'EN_ORDEN'

                db.session.commit()
                return jsonify(po.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        orders = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).all()
        return jsonify([o.to_dict() for o in orders])

    def _receive_po_items(po, request_ids=None):
        selected_ids = set(request_ids or [])

        to_receive = []
        for req in po.requests:
            req_status = (req.status or '').upper()
            if req_status in {'RECIBIDO', 'CANCELADO', 'ANULADO'}:
                continue
            if selected_ids and req.id not in selected_ids:
                continue
            to_receive.append(req)

        for req in to_receive:
            if req.item_type == 'MATERIAL' and req.warehouse_item_id:
                item = WarehouseItem.query.get(req.warehouse_item_id)
                if item:
                    qty = int(float(req.quantity or 0))
                    if qty > 0:
                        item.stock = int(item.stock or 0) + qty
                        move = WarehouseMovement(
                            item_id=item.id,
                            quantity=qty,
                            movement_type='IN',
                            date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            reference_id=po.id,
                            reason=f"Recepcion OC {po.po_code} / {req.req_code}",
                        )
                        db.session.add(move)
            req.status = 'RECIBIDO'

        pending_after = [
            r for r in po.requests
            if (r.status or '').upper() not in {'RECIBIDO', 'CANCELADO', 'ANULADO'}
        ]
        po.status = 'PARCIAL' if pending_after else 'CERRADA'

    @app.route('/api/purchase-orders/<int:id>/receive', methods=['POST'])
    def receive_po_items(id):
        try:
            po = PurchaseOrder.query.get(id)
            if not po:
                return jsonify({'error': 'Orden de compra no encontrada'}), 404
            data = request.json or {}
            req_ids = data.get('request_ids') or []
            _receive_po_items(po, req_ids)
            db.session.commit()
            return jsonify(po.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/purchase-orders/<int:id>/close', methods=['POST'])
    def close_po(id):
        try:
            po = PurchaseOrder.query.get(id)
            if not po:
                return jsonify({'error': 'Orden de compra no encontrada'}), 404
            _receive_po_items(po)
            db.session.commit()
            return jsonify(po.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/list-spare-parts', methods=['GET'])
    def list_warehouse_items_for_purchasing():
        try:
            items = WarehouseItem.query.filter_by(is_active=True).all()
            return jsonify([{
                'id': i.id,
                'name': i.name,
                'code': i.code,
                'stock': i.stock,
                'brand': i.brand
            } for i in items])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

