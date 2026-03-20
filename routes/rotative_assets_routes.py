import datetime as dt

from flask import jsonify, request


def register_rotative_assets_routes(
    app,
    db,
    RotativeAsset,
    RotativeAssetHistory,
):
    def _generate_rotative_code():
        last = RotativeAsset.query.order_by(RotativeAsset.id.desc()).first()
        next_id = (last.id if last else 0) + 1
        return f"MR-{next_id:04d}"


    @app.route('/api/rotative-assets', methods=['GET', 'POST'])
    def handle_rotative_assets():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                asset = RotativeAsset(
                    code=data.get('code') or _generate_rotative_code(),
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
                    component_id=data.get('component_id')
                )
                db.session.add(asset)
                db.session.flush()
                db.session.add(RotativeAssetHistory(
                    asset_id=asset.id,
                    event_type='CREACION',
                    event_date=dt.date.today().isoformat(),
                    comments='Activo rotativo creado',
                    area_id=asset.area_id,
                    line_id=asset.line_id,
                    equipment_id=asset.equipment_id,
                    system_id=asset.system_id,
                    component_id=asset.component_id
                ))
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
            asset.is_active = not asset.is_active
            db.session.add(RotativeAssetHistory(
                asset_id=asset.id,
                event_type='CAMBIO_ACTIVO',
                event_date=dt.date.today().isoformat(),
                comments='Toggle activo/inactivo',
                area_id=asset.area_id,
                line_id=asset.line_id,
                equipment_id=asset.equipment_id,
                system_id=asset.system_id,
                component_id=asset.component_id
            ))
            db.session.commit()
            return jsonify({"message": "Estado actualizado"})

        try:
            data = request.json or {}
            location_before = (asset.area_id, asset.line_id, asset.equipment_id, asset.system_id, asset.component_id)
            status_before = asset.status
            for field in [
                'code', 'name', 'category', 'brand', 'model', 'serial_number',
                'status', 'install_date', 'notes', 'is_active',
                'area_id', 'line_id', 'equipment_id', 'system_id', 'component_id'
            ]:
                if field in data:
                    setattr(asset, field, data[field])
            location_after = (asset.area_id, asset.line_id, asset.equipment_id, asset.system_id, asset.component_id)
            if location_before != location_after or status_before != asset.status:
                db.session.add(RotativeAssetHistory(
                    asset_id=asset.id,
                    event_type='ACTUALIZACION',
                    event_date=dt.date.today().isoformat(),
                    comments='Actualizacion de datos/ubicacion',
                    area_id=asset.area_id,
                    line_id=asset.line_id,
                    equipment_id=asset.equipment_id,
                    system_id=asset.system_id,
                    component_id=asset.component_id
                ))
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

            db.session.add(RotativeAssetHistory(
                asset_id=asset.id,
                event_type='INSTALACION',
                event_date=event_date,
                comments=data.get('comments'),
                area_id=asset.area_id,
                line_id=asset.line_id,
                equipment_id=asset.equipment_id,
                system_id=asset.system_id,
                component_id=asset.component_id
            ))
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
            db.session.add(RotativeAssetHistory(
                asset_id=asset.id,
                event_type='RETIRO',
                event_date=event_date,
                comments=data.get('comments'),
                area_id=asset.area_id,
                line_id=asset.line_id,
                equipment_id=asset.equipment_id,
                system_id=asset.system_id,
                component_id=asset.component_id
            ))
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
        rows = RotativeAssetHistory.query.filter_by(asset_id=asset_id)\
            .order_by(RotativeAssetHistory.id.desc()).all()
        return jsonify([r.to_dict() for r in rows])




