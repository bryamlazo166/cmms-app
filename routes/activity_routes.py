import datetime as dt

from flask import jsonify, request


def register_activity_routes(app, db, logger, Activity, Milestone):

    @app.route('/api/activities', methods=['GET', 'POST'])
    def handle_activities():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('title') or '').strip():
                    return jsonify({"error": "title es obligatorio"}), 400

                act = Activity(
                    title=data['title'].strip(),
                    activity_type=(data.get('activity_type') or 'OTRO').upper(),
                    responsible=data.get('responsible'),
                    priority=(data.get('priority') or 'MEDIA').upper(),
                    status='ABIERTA',
                    description=data.get('description'),
                    start_date=data.get('start_date') or dt.date.today().isoformat(),
                    target_date=data.get('target_date'),
                    equipment_id=data.get('equipment_id') or None,
                )
                db.session.add(act)
                db.session.commit()
                return jsonify(act.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET — filter by status/type
        status = request.args.get('status')
        act_type = request.args.get('type')
        show_all = request.args.get('all', 'false').lower() == 'true'

        query = Activity.query
        if not show_all:
            query = query.filter(Activity.status.in_(['ABIERTA', 'EN_PROGRESO']))
        if status:
            query = query.filter_by(status=status)
        if act_type:
            query = query.filter_by(activity_type=act_type)
        activities = query.order_by(Activity.id.desc()).all()
        return jsonify([a.to_dict() for a in activities])

    @app.route('/api/activities/<int:act_id>', methods=['PUT', 'DELETE'])
    def handle_activity_id(act_id):
        act = Activity.query.get_or_404(act_id)

        if request.method == 'DELETE':
            act.status = 'CANCELADA'
            db.session.commit()
            return jsonify({"ok": True})

        try:
            data = request.json or {}
            for field in ['title', 'activity_type', 'responsible', 'priority',
                          'status', 'description', 'start_date', 'target_date',
                          'completion_date', 'equipment_id']:
                if field in data:
                    setattr(act, field, data[field] or None)

            # Auto-set completion date
            if data.get('status') == 'COMPLETADA' and not act.completion_date:
                act.completion_date = dt.date.today().isoformat()

            db.session.commit()
            return jsonify(act.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── Milestones ─────────────────────────────────────────────────────────

    @app.route('/api/activities/<int:act_id>/milestones', methods=['GET', 'POST'])
    def handle_milestones(act_id):
        Activity.query.get_or_404(act_id)

        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('description') or '').strip():
                    return jsonify({"error": "description es obligatorio"}), 400

                max_order = db.session.query(db.func.max(Milestone.order_index)) \
                    .filter_by(activity_id=act_id).scalar() or 0

                ms = Milestone(
                    activity_id=act_id,
                    description=data['description'].strip(),
                    target_date=data.get('target_date'),
                    status='PENDIENTE',
                    order_index=max_order + 1,
                )
                db.session.add(ms)

                # Auto-set activity to EN_PROGRESO if ABIERTA
                act = Activity.query.get(act_id)
                if act and act.status == 'ABIERTA':
                    act.status = 'EN_PROGRESO'

                db.session.commit()
                return jsonify(ms.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        milestones = Milestone.query.filter_by(activity_id=act_id, is_active=True) \
            .order_by(Milestone.order_index).all()
        return jsonify([m.to_dict() for m in milestones])

    @app.route('/api/milestones/<int:ms_id>', methods=['PUT', 'DELETE'])
    def handle_milestone_id(ms_id):
        ms = Milestone.query.get_or_404(ms_id)

        if request.method == 'DELETE':
            ms.is_active = False
            db.session.commit()
            return jsonify({"ok": True})

        try:
            data = request.json or {}
            for field in ['description', 'target_date', 'status', 'comment']:
                if field in data:
                    setattr(ms, field, data[field])

            # Auto-set completion date when completing
            if data.get('status') == 'COMPLETADO' and not ms.completion_date:
                ms.completion_date = dt.date.today().isoformat()
            elif data.get('status') != 'COMPLETADO':
                ms.completion_date = None

            db.session.commit()

            # Check if all milestones are done → auto-complete activity
            act = Activity.query.get(ms.activity_id)
            if act:
                active_ms = [m for m in act.milestones if m.is_active]
                all_done = active_ms and all(m.status == 'COMPLETADO' for m in active_ms)
                if all_done and act.status != 'COMPLETADA':
                    act.status = 'COMPLETADA'
                    act.completion_date = dt.date.today().isoformat()
                    db.session.commit()

            return jsonify(ms.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
