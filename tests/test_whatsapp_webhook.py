"""Tests del bot WhatsApp (/api/public/whatsapp/webhook).

Cubre: auth del gateway (503/403/400), numero no registrado, saludo, flujo
completo de reporte con confirmacion (DRY-RUN y real), anti-duplicados con
"agregar observacion", correccion y cancelacion. La extraccion IA se mockea
(sin llamadas reales a DeepSeek).
"""
import pytest

TOKEN = 'test-token-whatsapp-123'
URL = '/api/public/whatsapp/webhook'
PHONE = '51999888777'
GROUP = '120363999888777@g.us'

EXTRACTION = {
    'es_reporte': True,
    'description': 'Sobrecalentamiento en motor electrico del Molino 2 - revisar rodamientos',
    'equipment_tag': 'MOLI2',
    'component_name': 'motor electrico',
    'system_name': None,
    'failure_mode': 'Sobrecalentamiento',
    'failure_category': 'Electrica',
    'blockage_object': None,
    'criticality': 'Alta',
    'maintenance_type': 'Correctivo',
    'scope': 'PLAN',
    'free_location': None,
    'event_date': None,
}


def _payload(**kw):
    base = {
        'message_id': 'MSG-1',
        'from': f'{PHONE}@s.whatsapp.net',
        'phone': PHONE,
        'push_name': 'Tester',
        'text': 'hola bot',
        'media': None,
        'timestamp': 1760000000,
    }
    base.update(kw)
    return base


def _post(client, **kw):
    return client.post(URL, json=_payload(**kw), headers={'X-Gateway-Token': TOKEN})


@pytest.fixture
def wa_env(app, monkeypatch):
    """Token configurado + usuario WhatsApp registrado + arbol minimo."""
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', TOKEN)
    from bot import whatsapp_handler as wh
    assert wh._ensure_wa_users_table(app)
    from sqlalchemy import text
    from database import db
    from models import Area, Line, Equipment, System, Component
    with app.app_context():
        # Arbol: Molienda > Linea Molinos > MOLINO 2 [MOLI2] > SIST ACCIONAMIENTO > MOTOR ELECTRICO
        if not Area.query.filter_by(name='Molienda').first():
            area = Area(name='Molienda')
            db.session.add(area)
            db.session.flush()
            line = Line(name='Linea Molinos', area_id=area.id)
            db.session.add(line)
            db.session.flush()
            eq = Equipment(name='MOLINO 2', tag='MOLI2', line_id=line.id)
            db.session.add(eq)
            db.session.flush()
            sys = System(name='SISTEMA DE ACCIONAMIENTO', equipment_id=eq.id)
            db.session.add(sys)
            db.session.flush()
            db.session.add(Component(name='MOTOR ELECTRICO', system_id=sys.id))
        u = db.session.execute(text(
            "SELECT id FROM bot_whatsapp_users WHERE phone_number = :p"), {"p": PHONE}).fetchone()
        if not u:
            db.session.execute(text(
                "INSERT INTO bot_whatsapp_users (phone_number, nombre, rol, areas_visibles, "
                "grupo_destino, grupo_nombre, activo) VALUES (:p, 'Tester Molino', "
                "'supervisor_area', NULL, :g, 'Produccion-Mantenimiento', TRUE)"),
                {"p": PHONE, "g": GROUP})
        db.session.commit()
    wh.invalidate_wa_users_cache()
    wh._sessions.clear()
    # Mock de la extraccion IA (sin llamadas reales)
    monkeypatch.setattr(wh, '_call_deepseek_extraction',
                        lambda app_, user_, msg_: dict(EXTRACTION))
    yield wh
    wh._sessions.clear()


# ── Auth del gateway ──────────────────────────────────────────────────────

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
    assert 'no esta registrado' in data['replies'][0].lower()
    assert '51000000000' in data['replies'][0]


# ── Conversacion ──────────────────────────────────────────────────────────

def test_saludo(client, wa_env):
    r = _post(client, text='hola')
    body = r.get_json()['replies'][0]
    assert 'Tester Molino' in body
    assert 'falla' in body.lower()


def test_flujo_dry_run_no_escribe(app, client, wa_env, monkeypatch):
    monkeypatch.setenv('WHATSAPP_DRY_RUN', '1')
    # 1) reporte -> confirmacion con el arbol resuelto
    r = _post(client, text='el motor del molino 2 esta calentando')
    body = r.get_json()['replies'][0]
    assert 'MOLI2' in body                      # path resuelto contra el arbol real
    assert 'MOTOR ELECTRICO' in body            # componente resuelto
    assert 'DRY-RUN' in body
    # 2) confirmar -> simulacion + pide evidencia (mismo flujo que produccion)
    r2 = _post(client, text='1')
    replies2 = r2.get_json()['replies']
    assert 'DRY-RUN' in replies2[0]
    assert 'AV-SIMULADO' in replies2[0]
    assert any('foto' in x.lower() for x in replies2)   # pide foto/video tambien en DRY
    assert not r2.get_json().get('forwards')    # DRY no reenvia a grupos
    # 3) enviar video en DRY -> simula reenvio, aclara que no se sube
    r3 = _post(client, text='', media={'type': 'video', 'mimetype': 'video/mp4', 'base64': 'aGk='})
    body3 = r3.get_json()['replies'][0]
    assert 'DRY-RUN' in body3
    assert 'no se suben' in body3.lower() or 'no se sube' in body3.lower()
    from sqlalchemy import text as _t
    from database import db
    with app.app_context():
        n = db.session.execute(_t(
            "SELECT count(*) FROM maintenance_notices WHERE reporter_type = 'whatsapp'"
        )).scalar()
    assert n == 0


def test_flujo_real_crea_aviso_y_reenvia(app, client, wa_env, monkeypatch):
    monkeypatch.setenv('WHATSAPP_DRY_RUN', '0')
    r = _post(client, text='el motor del molino 2 esta calentando')
    assert 'Es correcto' in r.get_json()['replies'][0].replace('¿', '')
    r2 = _post(client, text='si')
    data = r2.get_json()
    body = data['replies'][0]
    assert 'AV-' in body                        # codigo real
    # reenvio al grupo del reportero
    assert data['forwards'] and data['forwards'][0]['to'] == GROUP
    fwd_text = data['forwards'][0]['text']
    assert 'NUEVO AVISO' in fwd_text
    assert 'Tester Molino' in fwd_text
    from sqlalchemy import text as _t
    from database import db
    with app.app_context():
        row = db.session.execute(_t(
            "SELECT code, status, criticality, equipment_id FROM maintenance_notices "
            "WHERE reporter_type = 'whatsapp' ORDER BY id DESC LIMIT 1")).fetchone()
    assert row is not None
    assert row[1] == 'Pendiente'
    assert row[2] == 'Alta'
    assert row[3] is not None                   # quedo vinculado al equipo
    # 3) enviar VIDEO como evidencia: NO se sube a Supabase, SI se reenvia al grupo
    from bot import whatsapp_handler as wh
    llamadas_upload = []
    monkeypatch.setattr(wh, '_attach_media_to_notice',
                        lambda *a, **k: llamadas_upload.append(a) or None)
    r3 = _post(client, text='', media={'type': 'video', 'mimetype': 'video/mp4', 'base64': 'aGk='})
    d3 = r3.get_json()
    assert 'no se almacenan' in d3['replies'][0].lower()
    assert not llamadas_upload                              # video: sin upload
    assert d3['forwards'] and d3['forwards'][0]['to'] == GROUP
    assert d3['forwards'][0]['attach_incoming_media'] is True   # pero SI va al grupo


def test_duplicado_ofrece_agregar_observacion(app, client, wa_env, monkeypatch):
    """El aviso del test anterior sigue Pendiente -> nuevo reporte del mismo
    equipo debe detectar duplicado y permitir agregar la observacion."""
    monkeypatch.setenv('WHATSAPP_DRY_RUN', '0')
    r = _post(client, text='el motor del molino 2 sigue calentando, turno noche')
    body = r.get_json()['replies'][0]
    assert 'aviso(s) abierto(s)' in body
    assert 'AV-' in body
    assert '1' in body and '2' in body and '3' in body
    # elegir 1: agregar observacion
    r2 = _post(client, text='1')
    data = r2.get_json()
    assert 'quedo agregada' in data['replies'][0]
    assert data['forwards'] and 'ACTUALIZACION' in data['forwards'][0]['text']
    from sqlalchemy import text as _t
    from database import db
    with app.app_context():
        desc = db.session.execute(_t(
            "SELECT description FROM maintenance_notices "
            "WHERE reporter_type = 'whatsapp' ORDER BY id DESC LIMIT 1")).scalar()
    assert 'Obs de Tester Molino' in desc
    _post(client, text='listo')  # cerrar estado media


def test_cancelar_en_confirmacion(app, client, wa_env, monkeypatch):
    monkeypatch.setenv('WHATSAPP_DRY_RUN', '1')
    _post(client, text='falla en el motor del molino 2')
    r = _post(client, text='cancelar')
    assert 'cancelado' in r.get_json()['replies'][0].lower()
    # sin sesion: un "1" suelto ya no crea nada (la IA mock lo trata como reporte)
    from bot import whatsapp_handler as wh
    assert wh._get_session(PHONE) is None


def test_audio_no_soportado(client, wa_env):
    r = _post(client, text='', media={'type': 'audio', 'mimetype': 'audio/ogg', 'base64': 'aGk='})
    assert 'audio' in r.get_json()['replies'][0].lower()


# ── Panel admin de numeros ────────────────────────────────────────────────

def test_admin_whatsapp_users_crud(auth_admin):
    import json as _json
    # crear
    r = auth_admin.post('/api/admin/whatsapp-users', data=_json.dumps({
        'phone_number': '+51 911 222 333', 'nombre': 'Jimmy RMP',
        'rol': 'supervisor_area', 'areas_visibles': '7',
        'grupo_destino': '120363000111222@g.us', 'grupo_nombre': 'Recepcion de materia',
    }), content_type='application/json')
    assert r.status_code == 201
    assert r.get_json()['phone_number'] == '51911222333'  # normalizado a digitos
    # duplicado -> 409
    r2 = auth_admin.post('/api/admin/whatsapp-users', data=_json.dumps({
        'phone_number': '51911222333', 'nombre': 'Otro'}), content_type='application/json')
    assert r2.status_code == 409
    # listar
    r3 = auth_admin.get('/api/admin/whatsapp-users')
    assert r3.status_code == 200
    jimmy = [u for u in r3.get_json() if u['phone_number'] == '51911222333'][0]
    assert jimmy['grupo_nombre'] == 'Recepcion de materia'
    # editar
    r4 = auth_admin.put('/api/admin/whatsapp-users/51911222333', data=_json.dumps({
        'rol': 'supervisor_planta', 'puede_ver_todo': True}), content_type='application/json')
    assert r4.status_code == 200
    # meta (areas para el panel)
    r5 = auth_admin.get('/api/admin/whatsapp-users/meta')
    assert r5.status_code == 200
    assert 'areas' in r5.get_json()
    # eliminar
    r6 = auth_admin.delete('/api/admin/whatsapp-users/51911222333')
    assert r6.status_code == 200
    r7 = auth_admin.delete('/api/admin/whatsapp-users/51911222333')
    assert r7.status_code == 404


def test_admin_whatsapp_users_requiere_admin(auth_viewer):
    r = auth_viewer.get('/api/admin/whatsapp-users')
    assert r.status_code == 403
