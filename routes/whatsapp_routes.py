"""Webhook del gateway WhatsApp (Baileys, whatsapp-gateway/).

Ruta bajo /api/public/ porque el before_request global la exime de login de
sesion — la autenticacion aqui es machine-to-machine: el gateway manda el
header X-Gateway-Token y debe coincidir (comparacion timing-safe) con la
variable de entorno WHATSAPP_GATEWAY_TOKEN. Sin esa variable configurada el
webhook queda deshabilitado (503).
"""
import os
import hmac

from flask import jsonify, request


def register_whatsapp_routes(app, db, logger):

    @app.route('/api/public/whatsapp/webhook', methods=['POST'])
    def whatsapp_webhook():
        expected = (os.getenv('WHATSAPP_GATEWAY_TOKEN') or '').strip()
        if not expected:
            return jsonify({"error": "Webhook WhatsApp deshabilitado (falta WHATSAPP_GATEWAY_TOKEN)"}), 503

        provided = request.headers.get('X-Gateway-Token', '')
        if not hmac.compare_digest(provided, expected):
            logger.warning(f"WhatsApp webhook: token invalido desde {request.remote_addr}")
            return jsonify({"error": "Token invalido"}), 403

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
