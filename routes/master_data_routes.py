from flask import jsonify, request
from flask_login import current_user


def _require_perm(module, action):
    """Devuelve None si el usuario actual tiene el permiso, o una tupla
    (response, status) lista para retornar si no. Admin siempre pasa."""
    role = getattr(current_user, 'role', None)
    if role == 'admin':
        return None
    if not role:
        return jsonify({"error": "No autenticado."}), 401
    try:
        from app import _load_role_perms
        perms = _load_role_perms(role)
        if perms.get(module, {}).get(action, False):
            return None
    except Exception:
        pass
    return jsonify({"error": f"No tienes permiso para esta accion en {module}."}), 403


def register_master_data_routes(
    app,
    db,
    Provider,
    Technician,
    Area,
    Line,
    Equipment,
    System,
    Component,
    SparePart,
    create_entry,
    get_entries,
    update_entry,
    delete_entry,
):
    @app.route('/api/providers', methods=['GET', 'POST'])
    def handle_providers():
        if request.method == 'POST':
            denied = _require_perm('proveedores', 'create')
            if denied:
                return denied
            return create_entry(Provider, request.json, ['name'])

        providers = Provider.query.filter_by(is_active=True).order_by(Provider.name).all()
        return jsonify([provider.to_dict() for provider in providers])

    @app.route('/api/providers/<int:id>', methods=['PUT', 'DELETE'])
    def handle_provider_id(id):
        if request.method == 'PUT':
            denied = _require_perm('proveedores', 'edit')
            if denied:
                return denied
            return update_entry(Provider, id, request.json)

        denied = _require_perm('proveedores', 'delete')
        if denied:
            return denied
        try:
            provider = Provider.query.get(id)
            if not provider:
                return jsonify({"error": "Provider not found"}), 404

            provider.is_active = False
            db.session.commit()
            return jsonify({"message": "Provider deactivated"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/technicians', methods=['GET', 'POST'])
    def handle_technicians():
        if request.method == 'POST':
            denied = _require_perm('tecnicos', 'create')
            if denied:
                return denied
            return create_entry(Technician, request.json, ['name'])

        show_all = request.args.get('all', 'false').lower() == 'true'
        if show_all:
            technicians = Technician.query.order_by(Technician.name).all()
        else:
            technicians = Technician.query.filter_by(is_active=True).order_by(Technician.name).all()
        return jsonify([tech.to_dict() for tech in technicians])

    @app.route('/api/technicians/<int:id>', methods=['PUT', 'DELETE'])
    def handle_technician_id(id):
        if request.method == 'PUT':
            denied = _require_perm('tecnicos', 'edit')
            if denied:
                return denied
            return update_entry(Technician, id, request.json)

        denied = _require_perm('tecnicos', 'delete')
        if denied:
            return denied
        try:
            tech = Technician.query.get(id)
            if not tech:
                return jsonify({"error": "Technician not found"}), 404

            tech.is_active = not tech.is_active
            db.session.commit()
            return jsonify({"message": f"Technician {'activated' if tech.is_active else 'deactivated'}"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/areas', methods=['GET', 'POST'])
    def handle_areas():
        if request.method == 'POST':
            return create_entry(Area, request.json, ['name'])
        return get_entries(Area)

    @app.route('/api/areas/<int:id>', methods=['PUT', 'DELETE'])
    def handle_area_id(id):
        if request.method == 'PUT':
            return update_entry(Area, id, request.json)
        return delete_entry(Area, id)

    @app.route('/api/lines', methods=['GET', 'POST'])
    def handle_lines():
        if request.method == 'POST':
            return create_entry(Line, request.json, ['name', 'area_id'])
        return get_entries(Line)

    @app.route('/api/lines/<int:id>', methods=['PUT', 'DELETE'])
    def handle_line_id(id):
        if request.method == 'PUT':
            return update_entry(Line, id, request.json)
        return delete_entry(Line, id)

    @app.route('/api/lines/<int:source_id>/merge-into/<int:target_id>', methods=['POST'])
    def merge_lines(source_id, target_id):
        """Fusiona dos lineas: mueve TODOS los equipos de source -> target y
        actualiza todas las tablas con line_id para mantener consistencia.
        Luego borra la linea source (que queda vacia).

        Permiso requerido: admin (operacion destructiva, no reversible).

        Tablas actualizadas:
          - equipments.line_id
          - maintenance_notices.line_id
          - work_orders.line_id
          - lubrication_points.line_id
          - inspection_routes.line_id
          - rotative_assets.line_id

        Body opcional: {"allow_cross_area": false} para permitir mover entre
        areas distintas (por defecto solo se permite mismo area).
        """
        perm = _require_perm('activos_config', 'edit')
        if perm: return perm
        if getattr(current_user, 'role', None) != 'admin':
            return jsonify({"error": "Solo admin puede fusionar lineas (operacion destructiva)."}), 403

        try:
            from sqlalchemy import text as _text
            data = request.json or {}
            allow_cross_area = bool(data.get('allow_cross_area', False))

            if source_id == target_id:
                return jsonify({"error": "Las lineas origen y destino no pueden ser iguales."}), 400

            source = Line.query.get(source_id)
            target = Line.query.get(target_id)
            if not source:
                return jsonify({"error": f"Linea origen {source_id} no existe."}), 404
            if not target:
                return jsonify({"error": f"Linea destino {target_id} no existe."}), 404

            if source.area_id != target.area_id and not allow_cross_area:
                return jsonify({
                    "error": (f"Las lineas estan en areas distintas (origen: area_id={source.area_id}, "
                              f"destino: area_id={target.area_id}). Pasa allow_cross_area=true para forzar."),
                }), 400

            # Contar items antes para feedback
            n_equips = Equipment.query.filter_by(line_id=source_id).count()

            # 1) Mover equipos
            db.session.execute(_text("""
                UPDATE equipments SET line_id = :tgt WHERE line_id = :src
            """), {"tgt": target_id, "src": source_id})

            # 2) Actualizar tablas relacionadas (cada una en try porque puede que
            #    la tabla/columna no exista en instalaciones antiguas).
            related_updated = {}
            for table_name, col_name in [
                ('maintenance_notices', 'line_id'),
                ('work_orders',         'line_id'),
                ('lubrication_points',  'line_id'),
                ('inspection_routes',   'line_id'),
                ('rotative_assets',     'line_id'),
            ]:
                try:
                    result = db.session.execute(_text(
                        f"UPDATE {table_name} SET {col_name} = :tgt WHERE {col_name} = :src"
                    ), {"tgt": target_id, "src": source_id})
                    related_updated[table_name] = result.rowcount if result.rowcount is not None else 0
                except Exception as ex_rel:
                    related_updated[table_name] = f"skipped ({ex_rel.__class__.__name__})"

            # 3) Verificar que la linea origen quedo vacia
            remaining = Equipment.query.filter_by(line_id=source_id).count()
            if remaining > 0:
                db.session.rollback()
                return jsonify({
                    "error": f"Despues del merge quedaron {remaining} equipos en la linea origen. Rollback.",
                }), 500

            # 4) Borrar la linea source
            source_name = source.name
            db.session.delete(source)
            db.session.commit()

            return jsonify({
                "ok": True,
                "message": f"Linea '{source_name}' (id {source_id}) fusionada en '{target.name}' (id {target_id})",
                "equipments_moved": n_equips,
                "related_rows_updated": related_updated,
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/equipments', methods=['GET', 'POST'])
    def handle_equipments():
        if request.method == 'POST':
            return create_entry(Equipment, request.json, ['name', 'tag', 'line_id'])
        return get_entries(Equipment)

    @app.route('/api/equipments/<int:id>', methods=['PUT', 'DELETE'])
    def handle_equipment_id(id):
        if request.method == 'PUT':
            return update_entry(Equipment, id, request.json)
        return delete_entry(Equipment, id)

    @app.route('/api/equipments/bulk-responsibility', methods=['POST'])
    def bulk_set_equipment_responsibility():
        """Asigna responsable y proveedor a multiples equipos a la vez.
        Body: { equipment_ids: [int], responsible_party: 'INTERNO'|'PROVEEDOR',
                provider_id: int|null }
        """
        try:
            data = request.json or {}
            ids = data.get('equipment_ids') or []
            party = data.get('responsible_party')
            provider_id = data.get('provider_id')
            if not ids:
                return jsonify({"error": "equipment_ids requerido"}), 400
            if party not in ('INTERNO', 'PROVEEDOR'):
                return jsonify({"error": "responsible_party debe ser INTERNO o PROVEEDOR"}), 400

            updated = 0
            for eq in Equipment.query.filter(Equipment.id.in_(ids)).all():
                eq.default_responsible_party = party
                eq.default_provider_id = provider_id if party == 'PROVEEDOR' else None
                updated += 1
            db.session.commit()
            return jsonify({"ok": True, "updated": updated})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/systems', methods=['GET', 'POST'])
    def handle_systems():
        if request.method == 'POST':
            return create_entry(System, request.json, ['name', 'equipment_id'])
        return get_entries(System)

    @app.route('/api/systems/<int:id>', methods=['PUT', 'DELETE'])
    def handle_system_id(id):
        if request.method == 'PUT':
            return update_entry(System, id, request.json)
        return delete_entry(System, id)

    @app.route('/api/components', methods=['GET', 'POST'])
    def handle_components():
        if request.method == 'POST':
            return create_entry(Component, request.json, ['name', 'system_id'])
        return get_entries(Component)

    @app.route('/api/components/<int:id>', methods=['PUT', 'DELETE'])
    def handle_component_id(id):
        if request.method == 'PUT':
            return update_entry(Component, id, request.json)
        return delete_entry(Component, id)

    @app.route('/api/spare-parts', methods=['GET', 'POST'])
    def handle_spare_parts():
        if request.method == 'POST':
            return create_entry(SparePart, request.json, ['name', 'component_id'])
        return get_entries(SparePart)

    @app.route('/api/spare-parts/<int:id>', methods=['PUT', 'DELETE'])
    def handle_spare_part_id(id):
        if request.method == 'PUT':
            return update_entry(SparePart, id, request.json)
        return delete_entry(SparePart, id)
