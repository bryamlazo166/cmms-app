"""Rutas del bot WhatsApp: webhook del gateway + panel admin de numeros.

Webhook bajo /api/public/ porque el before_request global la exime de login de
sesion — la autenticacion aqui es machine-to-machine: el gateway manda el
header X-Gateway-Token y debe coincidir (comparacion timing-safe) con la
variable de entorno WHATSAPP_GATEWAY_TOKEN. Sin esa variable configurada el
webhook queda deshabilitado (503).

Panel /admin/whatsapp-users (solo admin): alta/baja/edicion de numeros
autorizados en bot_whatsapp_users, con rol, areas visibles y grupo destino.
"""
import os
import hmac

from flask import jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import text

_WA_ROLES = ('tecnico', 'supervisor_area', 'supervisor_planta')


def register_whatsapp_routes(app, db, logger):

    def _is_admin():
        return getattr(current_user, 'role', None) == 'admin'

    def _gateway_auth():
        """Auth machine-to-machine del gateway. Devuelve (resp, status) si falla, o None si OK."""
        expected = (os.getenv('WHATSAPP_GATEWAY_TOKEN') or '').strip()
        if not expected:
            return jsonify({"error": "Endpoint WhatsApp deshabilitado (falta WHATSAPP_GATEWAY_TOKEN)"}), 503
        provided = request.headers.get('X-Gateway-Token', '')
        if not hmac.compare_digest(provided, expected):
            logger.warning(f"WhatsApp gateway: token invalido desde {request.remote_addr}")
            return jsonify({"error": "Token invalido"}), 403
        return None

    @app.route('/api/public/whatsapp/webhook', methods=['POST'])
    def whatsapp_webhook():
        auth_err = _gateway_auth()
        if auth_err:
            return auth_err

        payload = request.get_json(silent=True) or {}
        if not payload.get('phone'):
            return jsonify({"error": "Payload invalido: falta 'phone'"}), 400

        try:
            from bot.whatsapp_handler import handle_incoming
            result = handle_incoming(app, payload) or {}
            return jsonify(result)
        except Exception as e:
            logger.error(f"WhatsApp webhook error: {e}", exc_info=True)
            # 200 con mensaje de cortesia: el gateway se lo muestra al usuario
            # en vez de un error generico de conexion.
            return jsonify({"replies": ["⚠️ Error interno del CMMS procesando tu mensaje. Ya quedo registrado en los logs."]}), 200

    # ── Cola de salida: el gateway sondea y envía (RCA, notificaciones) ───
    # Machine-to-machine (X-Gateway-Token). El gateway hace GET cada ~15 s,
    # envía cada mensaje por WhatsApp con retardo humano y confirma con ack.
    # Así Flask puede empujar mensajes proactivos SIN que el gateway abra
    # ningún puerto (sigue siendo cliente de Flask, seguro anti-baneo).

    @app.route('/api/public/whatsapp/outbox', methods=['GET'])
    def whatsapp_outbox_pull():
        auth_err = _gateway_auth()
        if auth_err:
            return auth_err
        try:
            from bot.rca import claim_outbox
            limit = request.args.get('limit', default=5, type=int)
            msgs = claim_outbox(app, limit=min(max(limit, 1), 10))
            return jsonify({"messages": msgs})
        except Exception as e:
            logger.error(f"whatsapp_outbox_pull error: {e}", exc_info=True)
            return jsonify({"messages": []}), 200

    @app.route('/api/public/whatsapp/outbox/ack', methods=['POST'])
    def whatsapp_outbox_ack():
        auth_err = _gateway_auth()
        if auth_err:
            return auth_err
        try:
            from bot.rca import ack_outbox
            results = (request.get_json(silent=True) or {}).get('results') or []
            ack_outbox(app, results)
            return jsonify({"ok": True})
        except Exception as e:
            logger.error(f"whatsapp_outbox_ack error: {e}", exc_info=True)
            return jsonify({"ok": False}), 200

    # ── Panel admin: usuarios del bot WhatsApp ────────────────────────────

    def _ensure_table():
        from bot.whatsapp_handler import _ensure_wa_users_table
        _ensure_wa_users_table(app)

    def _invalidate():
        from bot.whatsapp_handler import invalidate_wa_users_cache
        invalidate_wa_users_cache()

    @app.route('/api/admin/whatsapp-users', methods=['GET'])
    @login_required
    def list_whatsapp_users():
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        _ensure_table()
        try:
            rows = db.session.execute(text(
                "SELECT phone_number, nombre, rol, areas_visibles, grupo_destino, "
                "grupo_nombre, puede_ver_todo, activo, created_at "
                "FROM bot_whatsapp_users ORDER BY activo DESC, nombre"
            )).fetchall()
            return jsonify([{
                "phone_number": r[0], "nombre": r[1], "rol": r[2],
                "areas_visibles": r[3], "grupo_destino": r[4], "grupo_nombre": r[5],
                "puede_ver_todo": bool(r[6]), "activo": bool(r[7]),
                # sqlite devuelve str, postgres datetime — tolerar ambos
                "created_at": (r[8].isoformat() if hasattr(r[8], 'isoformat') else r[8]) if r[8] else None,
            } for r in rows])
        except Exception as e:
            logger.exception('list_whatsapp_users error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/whatsapp-users/meta', methods=['GET'])
    @login_required
    def whatsapp_users_meta():
        """Areas disponibles (para armar areas_visibles) — id y nombre."""
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            areas = db.session.execute(text(
                "SELECT id, name FROM areas ORDER BY name")).fetchall()
            return jsonify({"areas": [{"id": a[0], "name": a[1]} for a in areas],
                            "roles": list(_WA_ROLES)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/whatsapp-users', methods=['POST'])
    @login_required
    def create_whatsapp_user():
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        _ensure_table()
        data = request.get_json() or {}
        try:
            phone = ''.join(ch for ch in (data.get('phone_number') or '') if ch.isdigit())
            nombre = (data.get('nombre') or '').strip()
            if not phone or not nombre:
                return jsonify({"error": "phone_number y nombre son obligatorios"}), 400
            rol = (data.get('rol') or 'supervisor_area').strip().lower()
            if rol not in _WA_ROLES:
                rol = 'supervisor_area'
            areas = (data.get('areas_visibles') or '').strip() or None
            grupo = (data.get('grupo_destino') or '').strip() or None
            grupo_nombre = (data.get('grupo_nombre') or '').strip() or None
            puede_ver_todo = bool(data.get('puede_ver_todo', rol == 'supervisor_planta'))

            existing = db.session.execute(text(
                "SELECT 1 FROM bot_whatsapp_users WHERE phone_number = :p"
            ), {"p": phone}).scalar()
            if existing:
                return jsonify({"error": f"El numero {phone} ya existe"}), 409

            db.session.execute(text(
                "INSERT INTO bot_whatsapp_users (phone_number, nombre, rol, areas_visibles, "
                "grupo_destino, grupo_nombre, puede_ver_todo, activo) "
                "VALUES (:p, :n, :r, :a, :g, :gn, :pv, TRUE)"
            ), {"p": phone, "n": nombre, "r": rol, "a": areas, "g": grupo,
                "gn": grupo_nombre, "pv": puede_ver_todo})
            db.session.commit()
            _invalidate()
            return jsonify({"ok": True, "phone_number": phone}), 201
        except Exception as e:
            db.session.rollback()
            logger.exception('create_whatsapp_user error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/whatsapp-users/<phone>', methods=['PUT'])
    @login_required
    def update_whatsapp_user(phone):
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        data = request.get_json() or {}
        try:
            updates = {}
            if 'nombre' in data:
                v = (data['nombre'] or '').strip()
                if not v:
                    return jsonify({"error": "nombre no puede estar vacio"}), 400
                updates['nombre'] = v
            if 'rol' in data:
                r = (data['rol'] or '').strip().lower()
                if r in _WA_ROLES:
                    updates['rol'] = r
            if 'areas_visibles' in data:
                updates['areas_visibles'] = (data['areas_visibles'] or '').strip() or None
            if 'grupo_destino' in data:
                updates['grupo_destino'] = (data['grupo_destino'] or '').strip() or None
            if 'grupo_nombre' in data:
                updates['grupo_nombre'] = (data['grupo_nombre'] or '').strip() or None
            if 'puede_ver_todo' in data:
                updates['puede_ver_todo'] = bool(data['puede_ver_todo'])
            if 'activo' in data:
                updates['activo'] = bool(data['activo'])

            if not updates:
                return jsonify({"error": "Sin campos para actualizar"}), 400

            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates['p'] = ''.join(ch for ch in phone if ch.isdigit())
            result = db.session.execute(text(
                f"UPDATE bot_whatsapp_users SET {set_clause} WHERE phone_number = :p"
            ), updates)
            if result.rowcount == 0:
                db.session.rollback()
                return jsonify({"error": "No encontrado"}), 404
            db.session.commit()
            _invalidate()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.exception('update_whatsapp_user error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/admin/whatsapp-users/<phone>', methods=['DELETE'])
    @login_required
    def delete_whatsapp_user(phone):
        if not _is_admin():
            return jsonify({"error": "Solo admin"}), 403
        try:
            result = db.session.execute(text(
                "DELETE FROM bot_whatsapp_users WHERE phone_number = :p"
            ), {"p": ''.join(ch for ch in phone if ch.isdigit())})
            if result.rowcount == 0:
                db.session.rollback()
                return jsonify({"error": "No encontrado"}), 404
            db.session.commit()
            _invalidate()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.exception('delete_whatsapp_user error')
            return jsonify({"error": str(e)}), 500

    @app.route('/admin/whatsapp-users', methods=['GET'])
    @login_required
    def whatsapp_users_page():
        if not _is_admin():
            from flask import redirect, url_for
            return redirect(url_for('index'))
        from flask import render_template
        return render_template('whatsapp_users.html')
