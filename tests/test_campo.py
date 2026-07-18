"""Tests del Modo Campo (app móvil) y de los roles mecanico/electricista."""
import json
import pytest


def _mk_user(auth_admin, username, role, password='campo1234'):
    r = auth_admin.post('/api/auth/users', data=json.dumps({
        'username': username, 'password': password, 'role': role,
        'full_name': username.upper(),
    }), content_type='application/json')
    assert r.status_code in (200, 201), r.get_data(as_text=True)


def _login(client, username, password='campo1234'):
    client.get('/logout')
    r = client.post('/login', data={'username': username, 'password': password})
    assert r.status_code in (200, 302)
    return client


# ── Roles nuevos ───────────────────────────────────────────────────────────

def test_crear_usuarios_mecanico_y_electricista(auth_admin):
    _mk_user(auth_admin, 'mec1', 'mecanico')
    _mk_user(auth_admin, 'elec1', 'electricista')


def test_rol_invalido_rechazado(auth_admin):
    r = auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'xrol', 'password': 'algo1234', 'role': 'gasfitero'
    }), content_type='application/json')
    assert r.status_code == 400


def test_mecanico_puede_avisos_y_ordenes(client, auth_admin):
    _mk_user(auth_admin, 'mec2', 'mecanico')
    c = _login(client, 'mec2')
    # avisos: view
    assert c.get('/api/notices').status_code == 200
    # ordenes: view (filtrado a sus OTs; sin Technician vinculado → lista vacía)
    r = c.get('/api/work-orders?page=1&per_page=10')
    assert r.status_code == 200
    data = r.get_json()
    items = data.get('items') if isinstance(data, dict) else data
    assert items == []
    # compras: bloqueado
    assert c.get('/api/purchase-orders').status_code in (403, 404)


def test_electricista_puede_motores(client, auth_admin):
    _mk_user(auth_admin, 'elec2', 'electricista')
    c = _login(client, 'elec2')
    r = c.get('/api/motors')
    assert r.status_code == 200


# ── Página /campo y árbol ligero ───────────────────────────────────────────

def test_campo_requiere_login(client):
    client.get('/logout')
    r = client.get('/campo')
    assert r.status_code in (301, 302)


def test_campo_page_y_tree(client, auth_admin):
    _mk_user(auth_admin, 'mec3', 'mecanico')
    c = _login(client, 'mec3')
    r = c.get('/campo')
    assert r.status_code == 200
    assert 'Modo Campo' in r.get_data(as_text=True)
    # Árbol ligero accesible para rol de campo (no requiere activos_config)
    r = c.get('/api/notices/tree')
    assert r.status_code == 200
    d = r.get_json()
    for k in ('areas', 'lines', 'equipments', 'systems', 'components'):
        assert k in d


def test_mecanico_crea_aviso_desde_campo(client, auth_admin):
    _mk_user(auth_admin, 'mec4', 'mecanico')
    c = _login(client, 'mec4')
    r = c.post('/api/notices', data=json.dumps({
        'description': 'Prueba desde modo campo',
        'criticality': 'Media', 'priority': 'Media',
        'reporter_name': 'MEC4', 'report_channel': 'SISTEMA',
        'scope': 'GENERAL', 'status': 'Pendiente',
    }), content_type='application/json')
    assert r.status_code == 201
    assert r.get_json()['code'].startswith('AV-')


# ── Medición eléctrica con tensión ─────────────────────────────────────────

@pytest.fixture
def motor(app):
    from database import db
    from models import RotativeAsset
    with app.app_context():
        m = RotativeAsset.query.filter_by(code='MOT-TEST-C').first()
        if not m:
            m = RotativeAsset(code='MOT-TEST-C', name='MOTOR CAMPO TEST',
                              category='MOTOR', is_electric_motor=True,
                              is_active=True)
            db.session.add(m)
            db.session.commit()
        return m.id


def test_registro_corriente_y_tension(client, auth_admin, motor):
    _mk_user(auth_admin, 'elec3', 'electricista')
    c = _login(client, 'elec3')
    r = c.post(f'/api/motors/{motor}/tests', data=json.dumps({
        'test_type': 'CORRIENTE', 'context': 'PROGRAMADO',
        'current_r': 42.1, 'current_s': 41.8, 'current_t': 42.5,
        'voltage_rs': 442.0, 'voltage_st': 440.5, 'voltage_tr': 441.2,
        'executed_by': 'ELEC3',
    }), content_type='application/json')
    assert r.status_code in (200, 201), r.get_data(as_text=True)

    # La tensión quedó guardada y sale en el historial
    r = c.get(f'/api/motors/{motor}/tests')
    assert r.status_code == 200
    tests = r.get_json()
    assert tests, 'debe existir la medición'
    t = tests[0]
    assert t['voltage_rs'] == 442.0
    assert t['voltage_st'] == 440.5
    assert t['voltage_tr'] == 441.2
    assert t['current_r'] == 42.1


def test_registro_megado(client, auth_admin, motor):
    _mk_user(auth_admin, 'elec4', 'electricista')
    c = _login(client, 'elec4')
    r = c.post(f'/api/motors/{motor}/tests', data=json.dumps({
        'test_type': 'MEGADO', 'insulation_mohm': 850, 'test_voltage_v': 1000,
        'executed_by': 'ELEC4',
    }), content_type='application/json')
    assert r.status_code in (200, 201), r.get_data(as_text=True)
