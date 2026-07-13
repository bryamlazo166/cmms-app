"""Tests del webhook WhatsApp (/api/public/whatsapp/webhook).

Verifica: token compartido (503 sin config, 403 invalido), payload minimo,
numero no registrado y flujo v1 (eco DRY-RUN) con usuario registrado.
"""
import json

TOKEN = 'test-token-whatsapp-123'
URL = '/api/public/whatsapp/webhook'


def _payload(**kw):
    base = {
        'message_id': 'ABC123',
        'from': '51999888777@s.whatsapp.net',
        'phone': '51999888777',
        'push_name': 'Tester',
        'text': 'hola bot',
        'media': None,
        'timestamp': 1760000000,
    }
    base.update(kw)
    return base


def test_webhook_deshabilitado_sin_env(client, monkeypatch):
    monkeypatch.delenv('WHATSAPP_GATEWAY_TOKEN', raising=False)
    r = client.post(URL, json=_payload())
    assert r.status_code == 503


def test_webhook_token_invalido(client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', TOKEN)
    r = client.post(URL, json=_payload(), headers={'X-Gateway-Token': 'otro-token'})
    assert r.status_code == 403


def test_webhook_payload_sin_phone(client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', TOKEN)
    r = client.post(URL, json={'text': 'hola'}, headers={'X-Gateway-Token': TOKEN})
    assert r.status_code == 400


def test_webhook_numero_no_registrado(client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', TOKEN)
    from bot import whatsapp_handler
    whatsapp_handler.invalidate_wa_users_cache()
    r = client.post(URL, json=_payload(phone='51000000000'),
                    headers={'X-Gateway-Token': TOKEN})
    assert r.status_code == 200
    data = r.get_json()
    assert data['replies']
    assert 'no esta registrado' in data['replies'][0].lower()
    # El numero se incluye para que el admin pueda darlo de alta
    assert '51000000000' in data['replies'][0]


def test_webhook_usuario_registrado_eco_dry_run(app, client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', TOKEN)
    monkeypatch.setenv('WHATSAPP_DRY_RUN', '1')

    # Alta del usuario directo en la tabla (el panel admin llega despues)
    from bot import whatsapp_handler
    assert whatsapp_handler._ensure_wa_users_table(app)
    from sqlalchemy import text
    from database import db
    with app.app_context():
        db.session.execute(text(
            "INSERT INTO bot_whatsapp_users "
            "(phone_number, nombre, rol, areas_visibles, grupo_destino, grupo_nombre, activo) "
            "VALUES ('51999888777', 'Tester Molino', 'supervisor_area', '3', "
            "'12036304@g.us', 'Produccion-Mantenimiento', TRUE)"
        ))
        db.session.commit()
    whatsapp_handler.invalidate_wa_users_cache()

    r = client.post(URL, json=_payload(text='el motor del molino 2 esta calentando'),
                    headers={'X-Gateway-Token': TOKEN})
    assert r.status_code == 200
    data = r.get_json()
    assert data['replies']
    body = data['replies'][0]
    assert 'Tester Molino' in body           # saluda con el nombre registrado
    assert 'molino 2' in body.lower()        # eco del mensaje recibido
    assert 'DRY-RUN' in body                 # el modo prueba queda explicito
    # v1 no reenvia nada a grupos todavia
    assert not data.get('forwards')


def test_webhook_media_sin_texto(app, client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', TOKEN)
    from bot import whatsapp_handler
    whatsapp_handler.invalidate_wa_users_cache()
    r = client.post(URL, json=_payload(
        text='',
        media={'type': 'image', 'mimetype': 'image/jpeg', 'base64': 'aGVsbG8='},
    ), headers={'X-Gateway-Token': TOKEN})
    assert r.status_code == 200
    data = r.get_json()
    assert data['replies']
    assert 'image' in data['replies'][0]
