import datetime as dt

from flask import jsonify, request
from sqlalchemy import text


def register_rotative_assets_routes(
    app,
    db,
    RotativeAsset,
    RotativeAssetHistory,
    RotativeAssetSpec,
    RotativeAssetBOM=None,
    WarehouseItem=None,
    WorkOrder=None,
    LubricationExecution=None,
    LubricationPoint=None,
):
    # _generate_rotative_code removed — code assigned after flush

    def _is_postgres():
        try:
            bind = db.session.get_bind()
            return bool(bind and bind.dialect and bind.dialect.name == 'postgresql')
        except Exception:
            return False

    def _repair_history_sequence_if_needed():
        if not _is_postgres():
            return
        db.session.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('rotative_asset_history','id'),
                    COALESCE((SELECT MAX(id) FROM rotative_asset_history), 0) + 1,
                    false
                )
                """
            )
        )

    def _record_history(asset, event_type, event_date=None, comments=None):
        _repair_history_sequence_if_needed()
        db.session.add(
            RotativeAssetHistory(
                asset_id=asset.id,
                event_type=event_type,
                event_date=event_date or dt.date.today().isoformat(),
                comments=comments,
                area_id=asset.area_id,
                line_id=asset.line_id,
                equipment_id=asset.equipment_id,
                system_id=asset.system_id,
                component_id=asset.component_id,
            )
        )

    @app.route('/api/rotative-assets', methods=['GET', 'POST'])
    def handle_rotative_assets():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                asset = RotativeAsset(
                    code=data.get('code') or 'MR-TEMP',
                    name=data.get('name').strip(),
                    category=data.get('category'),
                    brand=data.get('brand'),
                    model=data.get('model'),
                    serial_number=data.get('serial_number'),
                    status=data.get('status') or 'Disponible',
                    install_date=data.get('install_date'),
                    notes=data.get('notes'),
                    is_active=bool(data.get('is_active', True)),
                    area_id=data.get('area_id'),
                    line_id=data.get('line_id'),
                    equipment_id=data.get('equipment_id'),
                    system_id=data.get('system_id'),
                    component_id=data.get('component_id'),
                )
                db.session.add(asset)
                db.session.flush()
                if asset.code == 'MR-TEMP':
                    asset.code = f"MR-{asset.id:04d}"

                _record_history(asset, 'CREACION', comments='Activo rotativo creado')
                db.session.commit()
                return jsonify(asset.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        show_all = request.args.get('all', 'false').lower() == 'true'
        area_id = request.args.get('area_id', type=int)
        line_id = request.args.get('line_id', type=int)
        equipment_id = request.args.get('equipment_id', type=int)
        component_id = request.args.get('component_id', type=int)
        status = request.args.get('status')

        query = RotativeAsset.query
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
        if status:
            query = query.filter_by(status=status)

        rows = query.order_by(RotativeAsset.id.desc()).all()
        return jsonify([r.to_dict() for r in rows])

    @app.route('/api/rotative-assets/<int:asset_id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_rotative_asset_id(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)
        if request.method == 'GET':
            return jsonify(asset.to_dict())

        if request.method == 'DELETE':
            try:
                asset.is_active = not asset.is_active
                _record_history(asset, 'CAMBIO_ACTIVO', comments='Toggle activo/inactivo')
                db.session.commit()
                return jsonify({"message": "Estado actualizado"})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        try:
            data = request.json or {}
            location_before = (asset.area_id, asset.line_id, asset.equipment_id, asset.system_id, asset.component_id)
            status_before = asset.status
            for field in [
                'code', 'name', 'category', 'brand', 'model', 'serial_number',
                'status', 'install_date', 'notes', 'is_active',
                'area_id', 'line_id', 'equipment_id', 'system_id', 'component_id',
            ]:
                if field in data:
                    setattr(asset, field, data[field])
            location_after = (asset.area_id, asset.line_id, asset.equipment_id, asset.system_id, asset.component_id)
            if location_before != location_after or status_before != asset.status:
                _record_history(asset, 'ACTUALIZACION', comments='Actualizacion de datos/ubicacion')
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/install', methods=['POST'])
    def install_rotative_asset(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)
        try:
            data = request.json or {}
            event_date = data.get('event_date') or dt.date.today().isoformat()
            asset.status = 'Instalado'
            asset.install_date = event_date
            asset.area_id = data.get('area_id')
            asset.line_id = data.get('line_id')
            asset.equipment_id = data.get('equipment_id')
            asset.system_id = data.get('system_id')
            asset.component_id = data.get('component_id')

            _record_history(asset, 'INSTALACION', event_date=event_date, comments=data.get('comments'))
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/remove', methods=['POST'])
    def remove_rotative_asset(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)
        try:
            data = request.json or {}
            event_date = data.get('event_date') or dt.date.today().isoformat()
            _record_history(asset, 'RETIRO', event_date=event_date, comments=data.get('comments'))

            asset.status = data.get('new_status') or 'Disponible'
            asset.area_id = None
            asset.line_id = None
            asset.equipment_id = None
            asset.system_id = None
            asset.component_id = None
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/history', methods=['GET'])
    def get_rotative_asset_history(asset_id):
        RotativeAsset.query.get_or_404(asset_id)
        rows = RotativeAssetHistory.query.filter_by(asset_id=asset_id).order_by(RotativeAssetHistory.id.desc()).all()
        return jsonify([r.to_dict() for r in rows])

    @app.route('/api/rotative-assets/<int:asset_id>/specs', methods=['GET', 'POST'])
    def handle_rotative_specs(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)

        if request.method == 'GET':
            rows = RotativeAssetSpec.query.filter_by(asset_id=asset_id, is_active=True).order_by(RotativeAssetSpec.order_index.asc(), RotativeAssetSpec.id.asc()).all()
            return jsonify([r.to_dict() for r in rows])

        try:
            data = request.json or {}
            key_name = (data.get('key_name') or '').strip()
            value_text = (data.get('value_text') or '').strip()
            unit = (data.get('unit') or '').strip() or None
            order_index = data.get('order_index')
            try:
                order_index = int(order_index) if order_index is not None else 0
            except Exception:
                order_index = 0

            if not key_name or not value_text:
                return jsonify({"error": "key_name y value_text son obligatorios"}), 400

            spec = None
            spec_id = data.get('id')
            if spec_id:
                spec = RotativeAssetSpec.query.filter_by(id=spec_id, asset_id=asset_id).first()

            if spec is None:
                spec = RotativeAssetSpec.query.filter_by(asset_id=asset_id, key_name=key_name, unit=unit, is_active=True).first()

            if spec:
                spec.value_text = value_text
                spec.order_index = order_index
                spec.is_active = True
                event_label = 'FICHA_ACTUALIZADA'
            else:
                spec = RotativeAssetSpec(
                    asset_id=asset_id,
                    key_name=key_name,
                    value_text=value_text,
                    unit=unit,
                    order_index=order_index,
                    is_active=True,
                )
                db.session.add(spec)
                event_label = 'FICHA_AGREGADA'

            _record_history(asset, event_label, comments=f'{key_name}={value_text}{(" " + unit) if unit else ""}')
            db.session.commit()
            return jsonify(spec.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/specs/<int:spec_id>', methods=['DELETE'])
    def delete_rotative_spec(spec_id):
        spec = RotativeAssetSpec.query.get_or_404(spec_id)
        try:
            spec.is_active = False
            asset = RotativeAsset.query.get(spec.asset_id)
            if asset:
                _record_history(asset, 'FICHA_ELIMINADA', comments=f'{spec.key_name} eliminado')
            db.session.commit()
            return jsonify({"message": "Caracteristica eliminada"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── BOM (Bill of Materials) ────────────────────────────────────────────

    @app.route('/api/rotative-assets/<int:asset_id>/bom', methods=['GET', 'POST'])
    def handle_asset_bom(asset_id):
        RotativeAsset.query.get_or_404(asset_id)

        if request.method == 'POST':
            if not RotativeAssetBOM:
                return jsonify({"error": "BOM no disponible"}), 500
            try:
                data = request.json or {}
                wi_id = data.get('warehouse_item_id')
                if not wi_id:
                    return jsonify({"error": "Seleccione un repuesto del almacen."}), 400
                existing = RotativeAssetBOM.query.filter_by(
                    asset_id=asset_id, warehouse_item_id=wi_id).first()
                if existing:
                    return jsonify({"error": "Este repuesto ya esta en la lista."}), 409
                bom = RotativeAssetBOM(
                    asset_id=asset_id,
                    warehouse_item_id=int(wi_id),
                    category=(data.get('category') or 'MECANICO').upper(),
                    quantity=float(data.get('quantity') or 1),
                    notes=data.get('notes'),
                )
                db.session.add(bom)
                db.session.commit()
                return jsonify(bom.to_dict()), 201
            except Exception as exc:
                db.session.rollback()
                return jsonify({"error": str(exc)}), 500

        if not RotativeAssetBOM:
            return jsonify([])
        items = RotativeAssetBOM.query.filter_by(asset_id=asset_id).all()
        return jsonify([b.to_dict() for b in items])

    @app.route('/api/rotative-assets/bom/<int:bom_id>', methods=['DELETE'])
    def delete_asset_bom(bom_id):
        if not RotativeAssetBOM:
            return jsonify({"error": "BOM no disponible"}), 500
        bom = RotativeAssetBOM.query.get_or_404(bom_id)
        db.session.delete(bom)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Swap: Uninstall current + Install replacement ──────────────────────

    @app.route('/api/rotative-assets/swap', methods=['POST'])
    def swap_rotative_assets():
        try:
            data = request.json or {}
            remove_id = data.get('remove_asset_id')
            install_id = data.get('install_asset_id')
            if not remove_id or not install_id:
                return jsonify({"error": "Se requiere remove_asset_id e install_asset_id."}), 400

            old_asset = RotativeAsset.query.get(remove_id)
            new_asset = RotativeAsset.query.get(install_id)
            if not old_asset or not new_asset:
                return jsonify({"error": "Activo no encontrado."}), 404

            location = {
                'area_id': old_asset.area_id, 'line_id': old_asset.line_id,
                'equipment_id': old_asset.equipment_id,
                'system_id': old_asset.system_id, 'component_id': old_asset.component_id,
            }
            swap_date = data.get('date') or dt.date.today().isoformat()
            reason = data.get('reason') or 'Swap de activo'

            _record_history(old_asset, 'RETIRO', event_date=swap_date,
                            comments=f"Retirado por swap: {reason}")
            old_asset.status = data.get('old_status') or 'En Taller'
            for k in location:
                setattr(old_asset, k, None)
            old_asset.install_date = None

            for k, v in location.items():
                setattr(new_asset, k, v)
            new_asset.status = 'Instalado'
            new_asset.install_date = swap_date
            _record_history(new_asset, 'INSTALACION', event_date=swap_date,
                            comments=f"Instalado por swap (reemplaza {old_asset.code}): {reason}")

            db.session.commit()
            return jsonify({'removed': old_asset.to_dict(), 'installed': new_asset.to_dict()})
        except Exception as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500

    # ── Consolidated Asset History ─────────────────────────────────────────

    @app.route('/api/rotative-assets/<int:asset_id>/full-history', methods=['GET'])
    def get_asset_full_history(asset_id):
        try:
            asset = RotativeAsset.query.get_or_404(asset_id)
            events = []

            for h in (asset.history or []):
                loc = ' / '.join(filter(None, [
                    h.area.name if h.area else None,
                    h.line.name if h.line else None,
                    h.equipment.name if h.equipment else None,
                ]))
                events.append({
                    'date': h.event_date, 'category': 'MOVIMIENTO',
                    'type': h.event_type.replace('_', ' '),
                    'description': h.comments, 'location': loc,
                })

            if WorkOrder:
                ots = WorkOrder.query.filter_by(rotative_asset_id=asset_id).all()
                for ot in ots:
                    events.append({
                        'date': ot.real_start_date or ot.scheduled_date,
                        'category': 'OT', 'type': ot.maintenance_type,
                        'description': f"{ot.code}: {ot.description or ot.failure_mode or ''}",
                        'location': None, 'status': ot.status,
                    })

            if asset.equipment_id and LubricationExecution and LubricationPoint:
                lub_points = LubricationPoint.query.filter_by(equipment_id=asset.equipment_id).all()
                lub_ids = [p.id for p in lub_points]
                if lub_ids:
                    lub_map = {p.id: p for p in lub_points}
                    for e in LubricationExecution.query.filter(LubricationExecution.point_id.in_(lub_ids)).all():
                        pt = lub_map.get(e.point_id)
                        events.append({
                            'date': e.execution_date, 'category': 'LUBRICACION',
                            'type': e.action_type,
                            'description': f"{pt.name if pt else ''}: {pt.lubricant_name if pt else ''} {e.quantity_used or ''} {e.quantity_unit or ''}",
                            'location': None,
                        })

            events.sort(key=lambda x: x.get('date') or '', reverse=True)

            bom_items = []
            if RotativeAssetBOM:
                bom_items = [b.to_dict() for b in RotativeAssetBOM.query.filter_by(asset_id=asset_id).all()]

            return jsonify({'asset': asset.to_dict(), 'events': events[:100], 'bom': bom_items})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
