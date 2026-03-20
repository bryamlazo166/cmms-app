from flask import jsonify, request


def register_tools_routes(app, db, Tool):
    @app.route('/api/tools', methods=['GET', 'POST'])
    def handle_tools():
        if request.method == 'POST':
            try:
                data = request.json
                # Generate code
                last = Tool.query.order_by(Tool.id.desc()).first()
                next_id = (last.id if last else 0) + 1
                data['code'] = f"HRR-{next_id:03d}"
                
                tool = Tool(**data)
                db.session.add(tool)
                db.session.commit()
                return jsonify(tool.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        
        # GET - return active tools
        show_all = request.args.get('all', 'false').lower() == 'true'
        if show_all:
            tools = Tool.query.all()
        else:
            tools = Tool.query.filter_by(is_active=True).all()
        return jsonify([t.to_dict() for t in tools])

    @app.route('/api/tools/<int:id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_tool_id(id):
        tool = Tool.query.get_or_404(id)
        
        if request.method == 'GET':
            return jsonify(tool.to_dict())
        
        if request.method == 'PUT':
            data = request.json
            for key, value in data.items():
                if hasattr(tool, key):
                    setattr(tool, key, value)
            db.session.commit()
            return jsonify(tool.to_dict())
        
        # DELETE - soft delete
        tool.is_active = not tool.is_active
        db.session.commit()
        return jsonify({"message": f"Tool {'activated' if tool.is_active else 'deactivated'}"})


