"""Tests del modulo de lotes de martillos FAPMETAL.

Cubre:
  - CRUD basico de lotes
  - Estado agregado y alertas
  - Flujo principal: cambio en molino con inferencia de lotes
  - Recibir lote rellenado de FAPMETAL
  - Conciliacion trimestral
  - Reglas de negocio: no se puede cambiar sin stock, no se puede recibir si no esta en FAPMETAL, etc.
  - Funciones del bot (bot.actions.hammer_batches): inferencia + manejo de errores
"""
import json
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_batch(client, code, state='RELLENADO_EN_STOCK', hammers=72):
    r = client.post('/api/hammer-batches', data=json.dumps({
        'code': code, 'state': state, 'hammers_count': hammers,
    }), content_type='application/json')
    assert r.status_code == 201, r.get_json()
    return r.json


@pytest.fixture
def three_batches(auth_admin):
    """Setup tipico: 3 lotes en circulacion."""
    # Cleanup previo para evitar contaminacion entre tests del mismo archivo
    from app import db
    from models import HammerBatch, HammerBatchMovement
    with auth_admin.application.app_context():
        HammerBatchMovement.query.delete()
        HammerBatch.query.delete()
        db.session.commit()
    a = _create_batch(auth_admin, 'LOTE-A', 'INSTALADO_M1')
    b = _create_batch(auth_admin, 'LOTE-B', 'INSTALADO_M2')
    c = _create_batch(auth_admin, 'LOTE-C', 'RELLENADO_EN_STOCK')
    return {'A': a, 'B': b, 'C': c, 'client': auth_admin}


# ── CRUD basico ──────────────────────────────────────────────────────────────

def test_create_batch_assigns_defaults(auth_admin):
    r = auth_admin.post('/api/hammer-batches', data=json.dumps({
        'code': 'LOTE-TEST-CREATE',
    }), content_type='application/json')
    assert r.status_code == 201
    data = r.json
    assert data['code'] == 'LOTE-TEST-CREATE'
    assert data['state'] == 'RELLENADO_EN_STOCK'
    assert data['hammers_count'] == 72
    assert data['refill_count'] == 0
    assert data['is_active'] is True


def test_create_batch_duplicate_code_returns_409(auth_admin):
    auth_admin.post('/api/hammer-batches', data=json.dumps({'code': 'LOTE-DUP'}),
                    content_type='application/json')
    r = auth_admin.post('/api/hammer-batches', data=json.dumps({'code': 'LOTE-DUP'}),
                        content_type='application/json')
    assert r.status_code == 409
    assert 'ya existe' in r.json['error'].lower()


def test_create_batch_without_code_fails(auth_admin):
    r = auth_admin.post('/api/hammer-batches', data=json.dumps({}),
                        content_type='application/json')
    assert r.status_code == 400


def test_list_batches_excludes_discarded_by_default(three_batches):
    client = three_batches['client']
    # Descartar uno (necesita no estar instalado, asi que lo recibimos primero)
    # Pasamos LOTE-C de RELLENADO a DESCARTADO directamente
    r = client.post(f'/api/hammer-batches/{three_batches["C"]["id"]}/discard',
                    data=json.dumps({}), content_type='application/json')
    assert r.status_code == 200

    listed = client.get('/api/hammer-batches').json
    codes = {b['code'] for b in listed}
    assert 'LOTE-A' in codes and 'LOTE-B' in codes
    assert 'LOTE-C' not in codes

    listed_all = client.get('/api/hammer-batches?include_discarded=1').json
    assert {'LOTE-A', 'LOTE-B', 'LOTE-C'}.issubset({b['code'] for b in listed_all})


def test_get_batch_returns_movements(three_batches):
    client = three_batches['client']
    bid = three_batches['A']['id']
    r = client.get(f'/api/hammer-batches/{bid}')
    assert r.status_code == 200
    data = r.json
    assert 'movements' in data
    assert any(m['event_type'] == 'ALTA' for m in data['movements'])


def test_get_unknown_batch_returns_404(auth_admin):
    r = auth_admin.get('/api/hammer-batches/99999')
    assert r.status_code == 404


# ── Estado agregado y alertas ────────────────────────────────────────────────

def test_state_endpoint_groups_by_slot(three_batches):
    client = three_batches['client']
    r = client.get('/api/hammer-batches/state')
    assert r.status_code == 200
    data = r.json
    assert len(data['molino_1']) == 1
    assert data['molino_1'][0]['code'] == 'LOTE-A'
    assert len(data['molino_2']) == 1
    assert data['molino_2'][0]['code'] == 'LOTE-B'
    assert len(data['rellenado_stock']) == 1
    assert data['rellenado_stock'][0]['code'] == 'LOTE-C'
    assert len(data['en_fapmetal']) == 0
    assert data['alertas'] == []


def test_state_alerts_missing_mill(auth_admin):
    # Cleanup
    from app import db
    from models import HammerBatch, HammerBatchMovement
    with auth_admin.application.app_context():
        HammerBatchMovement.query.delete()
        HammerBatch.query.delete()
        db.session.commit()
    # Solo creo M1 — falta M2 y stock
    _create_batch(auth_admin, 'LOTE-ALERTA-1', 'INSTALADO_M1')
    r = auth_admin.get('/api/hammer-batches/state')
    alertas = r.json['alertas']
    assert any('Molino #2' in a for a in alertas)
    assert any('transito' in a or 'stock' in a for a in alertas)


# ── Flujo principal: cambio de lote ──────────────────────────────────────────

def test_change_with_inferred_batches(three_batches):
    client = three_batches['client']
    r = client.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M1',
        'start_time': '2026-05-10T04:30',
        'end_time': '2026-05-10T05:30',
        'lubrication_done': True,
    }), content_type='application/json')
    assert r.status_code == 201, r.get_json()
    data = r.json
    assert data['batch_out']['code'] == 'LOTE-A'
    assert data['batch_out']['state'] == 'EN_FAPMETAL'
    assert data['batch_in']['code'] == 'LOTE-C'
    assert data['batch_in']['state'] == 'INSTALADO_M1'
    assert data['batch_in']['refill_count'] == 1
    wo = data['work_order']
    assert wo['code'].startswith('OT-')
    assert wo['maintenance_type'] == 'Preventivo'
    assert wo['status'] == 'Cerrada'
    assert wo['real_duration'] == 1.0  # 04:30 -> 05:30
    assert 'Lubricacion' in wo['execution_comments']


def test_change_without_stock_fails(auth_admin):
    from app import db
    from models import HammerBatch, HammerBatchMovement
    with auth_admin.application.app_context():
        HammerBatchMovement.query.delete()
        HammerBatch.query.delete()
        db.session.commit()
    _create_batch(auth_admin, 'LOTE-X', 'INSTALADO_M1')
    r = auth_admin.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M1', 'start_time': '2026-05-10T04:30', 'end_time': '2026-05-10T05:30',
    }), content_type='application/json')
    assert r.status_code == 400
    assert 'stock' in r.json['error'].lower() or 'fapmetal' in r.json['error'].lower()


def test_change_invalid_mill_rejected(three_batches):
    client = three_batches['client']
    r = client.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M9', 'start_time': '2026-05-10T04:30', 'end_time': '2026-05-10T05:30',
    }), content_type='application/json')
    assert r.status_code == 400


def test_change_missing_times_rejected(three_batches):
    client = three_batches['client']
    r = client.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M1',
    }), content_type='application/json')
    assert r.status_code == 400


# ── Recibir rellenado ────────────────────────────────────────────────────────

def test_receive_refilled_batch(three_batches):
    client = three_batches['client']
    # Primero hago un cambio para que LOTE-A vaya a FAPMETAL
    client.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M1', 'start_time': '2026-05-10T04:30', 'end_time': '2026-05-10T05:30',
    }), content_type='application/json')

    # Ahora LOTE-A esta en EN_FAPMETAL — lo recibo
    aid = three_batches['A']['id']
    r = client.post(f'/api/hammer-batches/{aid}/receive', data=json.dumps({
        'event_date': '2026-05-12'
    }), content_type='application/json')
    assert r.status_code == 200
    assert r.json['state'] == 'RELLENADO_EN_STOCK'


def test_receive_not_in_fapmetal_fails(three_batches):
    client = three_batches['client']
    # LOTE-A esta INSTALADO_M1, no en FAPMETAL
    aid = three_batches['A']['id']
    r = client.post(f'/api/hammer-batches/{aid}/receive', data=json.dumps({}),
                    content_type='application/json')
    assert r.status_code == 400


# ── Discard (baja de lote) ───────────────────────────────────────────────────

def test_discard_installed_batch_fails(three_batches):
    """No se puede dar de baja un lote instalado en un molino."""
    client = three_batches['client']
    aid = three_batches['A']['id']  # INSTALADO_M1
    r = client.post(f'/api/hammer-batches/{aid}/discard', data=json.dumps({}),
                    content_type='application/json')
    assert r.status_code == 400


def test_discard_stock_batch_succeeds(three_batches):
    client = three_batches['client']
    cid = three_batches['C']['id']  # RELLENADO_EN_STOCK
    r = client.post(f'/api/hammer-batches/{cid}/discard', data=json.dumps({}),
                    content_type='application/json')
    assert r.status_code == 200
    assert r.json['state'] == 'DESCARTADO'
    assert r.json['is_active'] is False


# ── Conciliacion FAPMETAL ────────────────────────────────────────────────────

def test_conciliation_summary(three_batches):
    client = three_batches['client']
    # Hago 2 cambios para tener movimientos en el periodo
    client.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M1', 'start_time': '2026-05-10T04:30', 'end_time': '2026-05-10T05:30',
    }), content_type='application/json')
    # Recibo LOTE-A
    aid = three_batches['A']['id']
    client.post(f'/api/hammer-batches/{aid}/receive', data=json.dumps({}),
                content_type='application/json')
    # Otro cambio en M2 — LOTE-B sale, LOTE-A entra (ya rellenado)
    client.post('/api/hammer-batches/change', data=json.dumps({
        'mill': 'M2', 'start_time': '2026-05-12T04:00', 'end_time': '2026-05-12T05:10',
    }), content_type='application/json')

    r = client.get('/api/hammer-batches/conciliation?start=2026-05-01&end=2026-05-31')
    assert r.status_code == 200
    t = r.json['totals']
    assert t['cambios_molino_1'] == 1
    assert t['cambios_molino_2'] == 1
    assert t['cambios_total'] == 2
    assert t['martillos_enviados'] == 144  # 2 lotes × 72
    assert t['martillos_recibidos'] == 72   # 1 lote
    assert t['saldo_pendiente_hammers'] == 72


# ── Funciones del bot (bot/actions/hammer_batches.py) ────────────────────────

def test_bot_change_function_works(three_batches, app):
    """Las funciones extraidas a bot/actions/ deben funcionar igual que el endpoint."""
    from bot.actions.hammer_batches import change_hammer_batch
    info, err = change_hammer_batch(app, {
        'mill': 'M1',
        'start_time': '2026-05-10T04:30',
        'end_time': '2026-05-10T05:30',
        'lubrication_done': True,
    })
    assert err is None
    assert info['mill'] == 'M1'
    assert info['batch_out_code'] == 'LOTE-A'
    assert info['batch_in_code'] == 'LOTE-C'
    assert info['batch_in_refill_count'] == 1
    assert info['ot_code'].startswith('OT-')


def test_bot_receive_function_infers_batch(three_batches, app):
    """Si hay un solo lote en FAPMETAL, receive_hammer_batch lo infiere sin batch_code."""
    from bot.actions.hammer_batches import change_hammer_batch, receive_hammer_batch
    # Primero hago cambio para que LOTE-A vaya a FAPMETAL
    change_hammer_batch(app, {
        'mill': 'M1', 'start_time': '2026-05-10T04:30', 'end_time': '2026-05-10T05:30',
    })
    # Ahora recibo sin especificar codigo
    info, err = receive_hammer_batch(app, {})
    assert err is None
    assert info['code'] == 'LOTE-A'


def test_bot_change_no_stock_error_message(auth_admin, app):
    """El error de 'no hay stock' debe ser claro y accionable para el usuario del bot."""
    from app import db
    from models import HammerBatch, HammerBatchMovement
    with app.app_context():
        HammerBatchMovement.query.delete()
        HammerBatch.query.delete()
        db.session.commit()
    _create_batch(auth_admin, 'LOTE-SOLO-M1', 'INSTALADO_M1')

    from bot.actions.hammer_batches import change_hammer_batch
    info, err = change_hammer_batch(app, {
        'mill': 'M1', 'start_time': '2026-05-10T04:30', 'end_time': '2026-05-10T05:30',
    })
    assert info is None
    assert 'stock' in err.lower() or 'fapmetal' in err.lower()


def test_bot_module_reexport():
    """Confirma que el re-export en telegram_bot apunta a la funcion real."""
    from bot.actions.hammer_batches import change_hammer_batch, receive_hammer_batch
    from bot.telegram_bot import _change_hammer_batch, _receive_hammer_batch
    assert _change_hammer_batch is change_hammer_batch
    assert _receive_hammer_batch is receive_hammer_batch
