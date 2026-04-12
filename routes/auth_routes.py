from flask import jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user


def register_auth_routes(app, db, logger, User, RolePermission=None):

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

    # ── Role Permissions ──────────────────────────────────────────────────

    MODULES = [
        {'key': 'avisos', 'label': 'Avisos'},
        {'key': 'ordenes', 'label': 'Ordenes de Trabajo'},
        {'key': 'compras', 'label': 'Compras'},
        {'key': 'almacen', 'label': 'Almacen'},
        {'key': 'herramientas', 'label': 'Herramientas'},
        {'key': 'activos_rotativos', 'label': 'Activos Rotativos'},
        {'key': 'activos_config', 'label': 'Arbol de Equipos'},
        {'key': 'monitoreo', 'label': 'Monitoreo'},
        {'key': 'lubricacion', 'label': 'Lubricacion'},
        {'key': 'inspecciones', 'label': 'Inspecciones'},
        {'key': 'espesores', 'label': 'Inspeccion Espesores UT'},
        {'key': 'cockpit', 'label': 'Cockpit Gerencial'},
        {'key': 'indicadores', 'label': 'Indicadores Directorio'},
        {'key': 'paradas', 'label': 'Paradas de Planta'},
        {'key': 'seguimiento', 'label': 'Seguimiento'},
        {'key': 'reportes', 'label': 'Reportes'},
        {'key': 'historial_equipo', 'label': 'Historial Equipo'},
        {'key': 'exportar', 'label': 'Exportar Excel'},
        {'key': 'usuarios', 'label': 'Gestion Usuarios'},
    ]

    ROLES = ['jefe_mtto', 'planner', 'supervisor', 'tecnico', 'operador', 'almacenero', 'gerencia']

    # Default permissions per role (mirrors _DEFAULT_PERMS in app.py)
    DEFAULTS = {
        'jefe_mtto': {
            'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': True},
            'compras': {'view': True, 'edit': True}, 'almacen': {'view': True, 'edit': True},
            'herramientas': {'view': True, 'edit': True}, 'lubricacion': {'view': True, 'edit': True},
            'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
            'espesores': {'view': True, 'edit': True}, 'cockpit': {'view': True, 'edit': False},
            'indicadores': {'view': True, 'edit': False},
            'paradas': {'view': True, 'edit': True},
            'seguimiento': {'view': True, 'edit': True}, 'reportes': {'view': True, 'edit': True},
            'activos_rotativos': {'view': True, 'edit': True}, 'activos_config': {'view': True, 'edit': False},
            'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
        'planner': {
            'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': True},
            'compras': {'view': True, 'edit': True}, 'almacen': {'view': True, 'edit': False},
            'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': True},
            'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
            'espesores': {'view': True, 'edit': True}, 'cockpit': {'view': False, 'edit': False},
            'indicadores': {'view': False, 'edit': False},
            'paradas': {'view': True, 'edit': True},
            'seguimiento': {'view': True, 'edit': True}, 'reportes': {'view': True, 'edit': False},
            'activos_rotativos': {'view': True, 'edit': False}, 'activos_config': {'view': True, 'edit': False},
            'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
        'supervisor': {
            'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': False},
            'compras': {'view': True, 'edit': False}, 'almacen': {'view': True, 'edit': False},
            'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': True},
            'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
            'espesores': {'view': True, 'edit': True}, 'cockpit': {'view': False, 'edit': False},
            'indicadores': {'view': False, 'edit': False},
            'paradas': {'view': True, 'edit': True},
            'seguimiento': {'view': True, 'edit': True}, 'reportes': {'view': True, 'edit': False},
            'activos_rotativos': {'view': True, 'edit': False}, 'activos_config': {'view': True, 'edit': False},
            'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
        'tecnico': {
            'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': True, 'edit': True},
            'compras': {'view': False, 'edit': False}, 'almacen': {'view': False, 'edit': False},
            'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': True},
            'inspecciones': {'view': True, 'edit': True}, 'monitoreo': {'view': True, 'edit': True},
            'espesores': {'view': True, 'edit': True}, 'cockpit': {'view': False, 'edit': False},
            'indicadores': {'view': False, 'edit': False},
            'paradas': {'view': True, 'edit': False},
            'seguimiento': {'view': False, 'edit': False}, 'reportes': {'view': False, 'edit': False},
            'activos_rotativos': {'view': False, 'edit': False}, 'activos_config': {'view': False, 'edit': False},
            'historial_equipo': {'view': False, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
        'operador': {
            'avisos': {'view': True, 'edit': True}, 'ordenes': {'view': False, 'edit': False},
            'compras': {'view': False, 'edit': False}, 'almacen': {'view': False, 'edit': False},
            'herramientas': {'view': False, 'edit': False}, 'lubricacion': {'view': False, 'edit': False},
            'inspecciones': {'view': False, 'edit': False}, 'monitoreo': {'view': False, 'edit': False},
            'espesores': {'view': False, 'edit': False}, 'cockpit': {'view': False, 'edit': False},
            'indicadores': {'view': False, 'edit': False},
            'paradas': {'view': False, 'edit': False},
            'seguimiento': {'view': False, 'edit': False}, 'reportes': {'view': False, 'edit': False},
            'activos_rotativos': {'view': False, 'edit': False}, 'activos_config': {'view': False, 'edit': False},
            'historial_equipo': {'view': False, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
        'almacenero': {
            'avisos': {'view': False, 'edit': False}, 'ordenes': {'view': False, 'edit': False},
            'compras': {'view': True, 'edit': True}, 'almacen': {'view': True, 'edit': True},
            'herramientas': {'view': True, 'edit': True}, 'lubricacion': {'view': False, 'edit': False},
            'inspecciones': {'view': False, 'edit': False}, 'monitoreo': {'view': False, 'edit': False},
            'espesores': {'view': False, 'edit': False}, 'cockpit': {'view': False, 'edit': False},
            'indicadores': {'view': False, 'edit': False},
            'paradas': {'view': False, 'edit': False},
            'seguimiento': {'view': False, 'edit': False}, 'reportes': {'view': False, 'edit': False},
            'activos_rotativos': {'view': False, 'edit': False}, 'activos_config': {'view': False, 'edit': False},
            'historial_equipo': {'view': False, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
        'gerencia': {
            'avisos': {'view': True, 'edit': False}, 'ordenes': {'view': True, 'edit': False},
            'compras': {'view': True, 'edit': False}, 'almacen': {'view': True, 'edit': False},
            'herramientas': {'view': True, 'edit': False}, 'lubricacion': {'view': True, 'edit': False},
            'inspecciones': {'view': True, 'edit': False}, 'monitoreo': {'view': True, 'edit': False},
            'espesores': {'view': True, 'edit': False}, 'cockpit': {'view': True, 'edit': False},
            'indicadores': {'view': True, 'edit': False},
            'paradas': {'view': True, 'edit': False},
            'seguimiento': {'view': True, 'edit': False}, 'reportes': {'view': True, 'edit': False},
            'activos_rotativos': {'view': True, 'edit': False}, 'activos_config': {'view': True, 'edit': False},
            'historial_equipo': {'view': True, 'edit': False}, 'exportar': {'view': False, 'edit': False},
            'usuarios': {'view': False, 'edit': False},
        },
    }

    def _get_permissions():
        """Load permissions from DB, fill with defaults if missing."""
        if not RolePermission:
            return DEFAULTS
        result = {}
        for role in ROLES:
            result[role] = {}
            for mod in MODULES:
                key = mod['key']
                perm = RolePermission.query.filter_by(role=role, module=key).first()
                if perm:
                    result[role][key] = {'view': perm.can_view, 'edit': perm.can_edit}
                else:
                    defaults = DEFAULTS.get(role, {}).get(key, {'view': True, 'edit': False})
                    result[role][key] = defaults
        return result

    @app.route('/api/auth/permissions', methods=['GET'])
    @login_required
    def get_permissions():
        if current_user.role != 'admin':
            # Non-admin gets their own permissions only
            perms = _get_permissions()
            return jsonify({current_user.role: perms.get(current_user.role, {})})
        return jsonify({
            'permissions': _get_permissions(),
            'modules': MODULES,
            'roles': ROLES,
        })

    @app.route('/api/auth/permissions', methods=['PUT'])
    @login_required
    def update_permissions():
        if current_user.role != 'admin':
            return jsonify({"error": "Solo admin puede modificar permisos."}), 403
        if not RolePermission:
            return jsonify({"error": "Modelo de permisos no disponible."}), 500

        data = request.get_json() or {}
        # data = { role: { module: { view: bool, edit: bool } } }
        for role, modules in data.items():
            if role not in ROLES:
                continue
            for module, perms in modules.items():
                existing = RolePermission.query.filter_by(role=role, module=module).first()
                if existing:
                    existing.can_view = bool(perms.get('view', True))
                    existing.can_edit = bool(perms.get('edit', False))
                else:
                    db.session.add(RolePermission(
                        role=role, module=module,
                        can_view=bool(perms.get('view', True)),
                        can_edit=bool(perms.get('edit', False)),
                    ))
        db.session.commit()
        return jsonify({"ok": True})
