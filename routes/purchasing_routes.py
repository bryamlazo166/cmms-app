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

        # Enriquecer cada OC con sus OTs asociadas (para mostrar link en UI)
        from models import WorkOrder
        all_requests = PurchaseRequest.query.filter(
            PurchaseRequest.purchase_order_id.in_([o.id for o in orders])
        ).all() if orders else []
        reqs_by_po = {}
        ot_ids = set()
        for r in all_requests:
            reqs_by_po.setdefault(r.purchase_order_id, []).append(r)
            if r.work_order_id:
                ot_ids.add(r.work_order_id)
        wo_map = ({w.id: w for w in WorkOrder.query.filter(WorkOrder.id.in_(ot_ids)).all()}
                  if ot_ids else {})

        result = []
        for o in orders:
            d = o.to_dict()
            ot_list = []
            seen_wo_ids = set()
            for r in reqs_by_po.get(o.id, []):
                if not r.work_order_id or r.work_order_id in seen_wo_ids:
                    continue
                seen_wo_ids.add(r.work_order_id)
                wo = wo_map.get(r.work_order_id)
                if wo:
                    ot_list.append({
                        'id': wo.id,
                        'code': wo.code or f'OT-{wo.id}',
                        'description': (wo.description or '')[:80],
                        'status': wo.status,
                    })
            d['work_orders'] = ot_list
            result.append(d)
        return jsonify(result)

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

    @app.route('/api/purchase-orders/<int:id>/external-code', methods=['PUT'])
    def update_po_external_code(id):
        """Actualiza el codigo RQ interno de la empresa (ERP/SAP) y notas
        para una OC ya emitida. Permite dar seguimiento cruzado."""
        try:
            po = PurchaseOrder.query.get(id)
            if not po:
                return jsonify({'error': 'Orden de compra no encontrada'}), 404
            data = request.json or {}
            if 'external_rq_code' in data:
                code = (data.get('external_rq_code') or '').strip()
                po.external_rq_code = code or None
            if 'external_notes' in data:
                notes = (data.get('external_notes') or '').strip()
                po.external_notes = notes or None
            db.session.commit()
            return jsonify(po.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/purchase-orders/search', methods=['GET'])
    def search_purchase_orders():
        """Busqueda global en OCs por:
          - po_code, external_rq_code, provider_name (campos de la OC)
          - req_code, descripcion del item, nombre de spare_part o
            warehouse_item, codigo de OT relacionada (campos de los items
            asociados a la OC)
        Devuelve OCs con sus items que matchean para que el usuario pueda
        ubicar rapidamente que RQ contiene determinado item.
        """
        try:
            from sqlalchemy import or_
            q = (request.args.get('q') or '').strip()
            if not q or len(q) < 2:
                return jsonify({"error": "Pasa ?q= con al menos 2 caracteres"}), 400
            like = f"%{q}%"

            # Subquery: ids de PO cuyos items matchean
            from models import SparePart, WarehouseItem, WorkOrder
            req_q = db.session.query(PurchaseRequest).outerjoin(
                SparePart, PurchaseRequest.spare_part_id == SparePart.id
            ).outerjoin(
                WarehouseItem, PurchaseRequest.warehouse_item_id == WarehouseItem.id
            ).outerjoin(
                WorkOrder, PurchaseRequest.work_order_id == WorkOrder.id
            ).filter(
                PurchaseRequest.purchase_order_id.isnot(None),
                or_(
                    PurchaseRequest.req_code.ilike(like),
                    PurchaseRequest.description.ilike(like),
                    SparePart.name.ilike(like),
                    WarehouseItem.name.ilike(like),
                    WarehouseItem.code.ilike(like),
                    WorkOrder.code.ilike(like),
                )
            )
            matched_po_ids = set(r.purchase_order_id for r in req_q.all())

            # OCs cuyos campos directos matchean
            direct_q = PurchaseOrder.query.filter(or_(
                PurchaseOrder.po_code.ilike(like),
                PurchaseOrder.external_rq_code.ilike(like),
                PurchaseOrder.provider_name.ilike(like),
            )).all()
            for po in direct_q:
                matched_po_ids.add(po.id)

            if not matched_po_ids:
                return jsonify({"query": q, "results": []})

            pos = PurchaseOrder.query.filter(
                PurchaseOrder.id.in_(matched_po_ids)
            ).order_by(PurchaseOrder.id.desc()).all()

            # Para cada PO, marcar que items concretamente coinciden con la query
            results = []
            for po in pos:
                d = po.to_dict()
                matched_items = []
                for r in (po.requests or []):
                    sp_name = r.spare_part.name if r.spare_part else ''
                    wh_name = r.warehouse_item.name if r.warehouse_item else ''
                    wh_code = r.warehouse_item.code if r.warehouse_item else ''
                    blob = ' '.join([
                        r.req_code or '', r.description or '',
                        sp_name, wh_name, wh_code,
                    ]).lower()
                    if q.lower() in blob:
                        matched_items.append({
                            'id': r.id, 'req_code': r.req_code,
                            'item_label': sp_name or wh_name or r.description or '?',
                            'quantity': r.quantity, 'status': r.status,
                            'ot_code': r.work_order.code if r.work_order else None,
                        })
                d['matched_items'] = matched_items
                d['match_count'] = len(matched_items)
                results.append(d)
            return jsonify({"query": q, "results": results, "count": len(results)})
        except Exception as e:
            import traceback; traceback.print_exc()
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

