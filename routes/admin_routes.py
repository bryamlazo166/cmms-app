import os

from flask import jsonify, request


def register_admin_routes(app, db, logger):
    @app.route('/api/initialize', methods=['POST'])
    def initialize_db():
        # Safety gate: disabled by default in runtime.
        if (os.getenv('ALLOW_DB_RESET', 'false').strip().lower() != 'true'):
            return jsonify({"error": "DB reset deshabilitado (ALLOW_DB_RESET=false)."}), 403

        admin_token = os.getenv('CMMS_ADMIN_TOKEN')
        request_token = request.headers.get('X-CMMS-ADMIN-TOKEN') or request.args.get('token')

        # Require explicit token to avoid accidental data loss.
        if not admin_token:
            return jsonify({"error": "CMMS_ADMIN_TOKEN no configurado."}), 403
        if request_token != admin_token:
            return jsonify({"error": "Token invalido para DB reset."}), 403

        try:
            with app.app_context():
                db.drop_all()
                db.create_all()
                logger.warning("Database reset executed via /api/initialize.")
            return jsonify({"message": "DB reset success"}), 201
        except Exception as e:
            logger.error(f"DB reset error: {e}")
            return jsonify({"error": str(e)}), 500
