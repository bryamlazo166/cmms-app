from flask import jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user


def register_auth_routes(app, db, logger, User):

    # ── Pages ──────────────────────────────────────────────────────────────────

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        error = None
        if request.method == 'POST':
            username = (request.form.get('username') or '').strip().lower()
            password = request.form.get('password') or ''

            user = User.query.filter_by(username=username).first()
            if user and user.active and user.check_password(password):
                login_user(user, remember=True)
                next_url = request.args.get('next') or url_for('index')
                return redirect(next_url)
            error = 'Usuario o contraseña incorrectos.'

        return render_template('login.html', error=error)

    @app.route('/logout')
    def logout():
        logout_user()
        return redirect(url_for('login'))

    @app.route('/usuarios')
    @login_required
    def users_page():
        if current_user.role != 'admin':
            return redirect(url_for('index'))
        return render_template('users.html')

    # ── API: current user ──────────────────────────────────────────────────────

    @app.route('/api/auth/me', methods=['GET'])
    @login_required
    def auth_me():
        return jsonify(current_user.to_dict())

    # ── API: user management (admin only) ──────────────────────────────────────

    @app.route('/api/auth/users', methods=['GET'])
    @login_required
    def list_users():
        if current_user.role != 'admin':
            return jsonify({"error": "Acceso denegado."}), 403
        users = User.query.order_by(User.id).all()
        return jsonify([u.to_dict() for u in users])

    @app.route('/api/auth/users', methods=['POST'])
    @login_required
    def create_user():
        if current_user.role != 'admin':
            return jsonify({"error": "Acceso denegado."}), 403
        data = request.get_json() or {}
        username = (data.get('username') or '').strip().lower()
        password = (data.get('password') or '').strip()
        role = (data.get('role') or 'tecnico').strip()
        full_name = (data.get('full_name') or '').strip() or None

        if not username:
            return jsonify({"error": "username es obligatorio."}), 400
        if not password or len(password) < 6:
            return jsonify({"error": "La contraseña debe tener al menos 6 caracteres."}), 400
        if role not in ('admin', 'supervisor', 'tecnico', 'viewer'):
            return jsonify({"error": "Rol inválido. Usa: admin, supervisor, tecnico, viewer."}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({"error": f"El usuario '{username}' ya existe."}), 409

        user = User(username=username, role=role, full_name=full_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info(f"User created: {username} ({role}) by {current_user.username}")
        return jsonify(user.to_dict()), 201

    @app.route('/api/auth/users/<int:user_id>', methods=['PUT'])
    @login_required
    def update_user(user_id):
        if current_user.role != 'admin':
            return jsonify({"error": "Acceso denegado."}), 403
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "Usuario no encontrado."}), 404

        # Prevent removing the last admin
        if user.role == 'admin' and current_user.id == user.id:
            admin_count = User.query.filter_by(role='admin', active=True).count()
            if admin_count <= 1:
                data = request.get_json() or {}
                new_role = data.get('role')
                new_active = data.get('active')
                if (new_role and new_role != 'admin') or new_active is False:
                    return jsonify({"error": "No puedes desactivar o cambiar el rol del único administrador."}), 400

        data = request.get_json() or {}
        if 'full_name' in data:
            user.full_name = (data['full_name'] or '').strip() or None
        if 'role' in data and data['role'] in ('admin', 'supervisor', 'tecnico', 'viewer'):
            user.role = data['role']
        if 'active' in data:
            user.active = bool(data['active'])
        if data.get('password'):
            if len(data['password']) < 6:
                return jsonify({"error": "La contraseña debe tener al menos 6 caracteres."}), 400
            user.set_password(data['password'])

        db.session.commit()
        return jsonify(user.to_dict())

    @app.route('/api/auth/users/<int:user_id>', methods=['DELETE'])
    @login_required
    def delete_user(user_id):
        if current_user.role != 'admin':
            return jsonify({"error": "Acceso denegado."}), 403
        if user_id == current_user.id:
            return jsonify({"error": "No puedes eliminar tu propia cuenta."}), 400
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "Usuario no encontrado."}), 404
        user.active = False
        db.session.commit()
        return jsonify({"ok": True})

    @app.route('/api/auth/change-password', methods=['POST'])
    @login_required
    def change_password():
        data = request.get_json() or {}
        current_pwd = data.get('current_password') or ''
        new_pwd = data.get('new_password') or ''

        if not current_user.check_password(current_pwd):
            return jsonify({"error": "Contraseña actual incorrecta."}), 400
        if len(new_pwd) < 6:
            return jsonify({"error": "La nueva contraseña debe tener al menos 6 caracteres."}), 400

        current_user.set_password(new_pwd)
        db.session.commit()
        return jsonify({"ok": True})
