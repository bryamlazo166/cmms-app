from flask import jsonify, request


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
            return create_entry(Provider, request.json, ['name'])

        providers = Provider.query.filter_by(is_active=True).all()
        return jsonify([provider.to_dict() for provider in providers])

    @app.route('/api/providers/<int:id>', methods=['PUT', 'DELETE'])
    def handle_provider_id(id):
        if request.method == 'PUT':
            return update_entry(Provider, id, request.json)

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
            return create_entry(Technician, request.json, ['name'])

        show_all = request.args.get('all', 'false').lower() == 'true'
        if show_all:
            technicians = Technician.query.all()
        else:
            technicians = Technician.query.filter_by(is_active=True).all()
        return jsonify([tech.to_dict() for tech in technicians])

    @app.route('/api/technicians/<int:id>', methods=['PUT', 'DELETE'])
    def handle_technician_id(id):
        if request.method == 'PUT':
            return update_entry(Technician, id, request.json)

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
