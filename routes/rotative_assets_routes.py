import datetime as dt

from flask import jsonify, request
from sqlalchemy import text


def register_rotative_assets_routes(
    app,
    db,
    RotativeAsset,
    RotativeAssetHistory,
    RotativeAssetSpec,
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
