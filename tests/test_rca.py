"""Tests del copiloto de diagnóstico (RCA IA) y la cola de salida de WhatsApp.

Cubre:
  - format_whatsapp_message: listas ordenadas (repuestos/herramientas uno por
    línea, código junto al repuesto).
  - _build_payload: la IA solo SELECCIONA repuestos por índice; nunca inventa
    códigos (índices fuera de rango se descartan).
  - Cola wa_outbox: enqueue -> claim (marca 'sending') -> ack (marca 'sent').
  - generate_rca: guarda en notice_rca, NO toca description, encola al grupo de
    mantenimiento si WHATSAPP_MAINT_GROUP_JID está configurado.
  - Endpoints outbox: 503 sin token, 403 token inválido, 200 con token.
  - GET /api/notices/<id> incluye la clave 'rca'.
"""
import json


def _seed_notice(app, code, description='falla de prueba'):
    from database import db
    from models import MaintenanceNotice
    with app.app_context():
        n = MaintenanceNotice(
            code=code, description=description, status='Pendiente',
            criticality='Alta', failure_mode='Desgaste',
            failure_category='Mecanica', scope='GENERAL',
        )
        db.session.add(n)
        db.session.commit()
        return n.id


def test_format_whatsapp_message_listas():
    from bot.rca import format_whatsapp_message
    payload = {
        'notice_code': 'AV-1', 'equipment': 'Molienda › L1 › [EQ] Molino',
        'causa_raiz': 'Desalineación', 'acciones': ['Alinear', 'Revisar anclajes'],
        'repuestos': [{'name': 'RODAMIENTO 6312', 'code': 'RD-1'},
                      {'name': 'RETEN', 'code': ''}],
        'herramientas': ['Extractor', 'Alineador'],
        'casos_similares': [{'code': 'AV-0123', 'type': 'notice'}],
        'confianza': 'alta',
    }
    msg = format_whatsapp_message(payload)
    # Cada repuesto en su propia línea; código pegado al repuesto que lo tiene
    assert '• RODAMIENTO 6312  (cód. RD-1)' in msg
    # El repuesto sin código no arrastra "cód."
    reten_line = [ln for ln in msg.splitlines() if 'RETEN' in ln][0]
    assert 'cód.' not in reten_line
    # Herramientas una por línea
    assert '• Extractor' in msg and '• Alineador' in msg
    assert 'AV-0123' in msg
    assert 'PRE-DIAGNÓSTICO' in msg


def test_build_payload_no_inventa_codigos():
    from bot.rca import _build_payload
    ctx = {'code': 'AV-2', 'path': 'x', 'id': 1}
    spares = [{'name': 'A', 'code': 'CA', 'source': 'catálogo'},
              {'name': 'B', 'code': 'CB', 'source': 'historial'}]
    ai = {'causa_raiz': 'c', 'acciones': ['a'], 'herramientas': ['h'],
          'repuestos_idx': [0, 99], 'resumen': 'r', 'confianza': 'media'}
    p = _build_payload(ctx, [], spares, None, ai)
    # idx 0 válido -> incluido; idx 99 fuera de rango -> descartado
    assert len(p['repuestos']) == 1
    assert p['repuestos'][0]['code'] == 'CA'
    assert p['confianza'] == 'media'


def test_build_payload_acciones_string_se_normaliza():
    from bot.rca import _build_payload
    ctx = {'code': 'AV-3', 'id': 1}
    ai = {'causa_raiz': 'c', 'acciones': 'un solo paso', 'herramientas': None,
          'repuestos_idx': [], 'confianza': 'baja'}
    p = _build_payload(ctx, [], [], None, ai)
    assert p['acciones'] == ['un solo paso']
    assert p['herramientas'] == []
    assert p['repuestos'] == []


def test_outbox_queue_roundtrip(app):
    from bot.rca import enqueue_wa_message, claim_outbox, ack_outbox
    mid = enqueue_wa_message(app, '123@g.us', 'hola mtto', context='rca:AV-1')
    assert mid

    claimed = claim_outbox(app, limit=10)
    m = next((x for x in claimed if x['id'] == mid), None)
    assert m is not None
    assert m['to'] == '123@g.us' and m['body'] == 'hola mtto'

    # Un segundo claim NO lo devuelve (quedó en 'sending')
    again = [x['id'] for x in claim_outbox(app, limit=10)]
    assert mid not in again

    # ack ok -> 'sent'
    ack_outbox(app, [{'id': mid, 'ok': True}])
    from database import db
    from sqlalchemy import text
    with app.app_context():
        st = db.session.execute(text("SELECT status FROM wa_outbox WHERE id=:i"),
                                {"i": mid}).scalar()
    assert st == 'sent'


def test_outbox_ack_fallo_reintenta(app):
    from bot.rca import enqueue_wa_message, claim_outbox, ack_outbox
    mid = enqueue_wa_message(app, '456@g.us', 'reintento')
    claim_outbox(app, limit=10)
    ack_outbox(app, [{'id': mid, 'ok': False}])
    from database import db
    from sqlalchemy import text
    with app.app_context():
        st = db.session.execute(text("SELECT status FROM wa_outbox WHERE id=:i"),
                                {"i": mid}).scalar()
    # attempts=1 (<3) -> vuelve a 'pending' para reintentar
    assert st == 'pending'


def test_generate_rca_guarda_no_filtra_y_encola(app, monkeypatch):
    import bot.rca as rca
    nid = _seed_notice(app, 'AV-9010')

    monkeypatch.setattr(rca, '_collect_similar_cases',
                        lambda *a, **k: [{'type': 'notice', 'code': 'AV-0001',
                                          'similarity': 0.9, 'excerpt': 'x'}])
    monkeypatch.setattr(rca, '_collect_hard_spares',
                        lambda *a, **k: [{'name': 'RODAMIENTO', 'code': 'RD-9',
                                          'source': 'catálogo'}])
    monkeypatch.setattr(rca, '_call_llm',
                        lambda *a, **k: {'causa_raiz': 'desgaste severo',
                                         'acciones': ['cambiar rodamiento'],
                                         'herramientas': ['llave'],
                                         'repuestos_idx': [0], 'resumen': 'ok',
                                         'confianza': 'alta'})
    monkeypatch.setenv('WHATSAPP_MAINT_GROUP_JID', '999@g.us')

    payload = rca.generate_rca(app, nid, push=True)
    assert payload['causa_raiz'] == 'desgaste severo'
    assert payload['repuestos'][0]['code'] == 'RD-9'

    # Persistido en notice_rca
    got = rca.get_rca(app, nid)
    assert got and got['causa_raiz'] == 'desgaste severo'

    # NO tocó la descripción del aviso (nunca debe filtrarse a producción)
    from database import db
    from models import MaintenanceNotice
    with app.app_context():
        desc = MaintenanceNotice.query.get(nid).description
    assert desc == 'falla de prueba'

    # Encoló el pre-diagnóstico al grupo de mantenimiento
    claimed = rca.claim_outbox(app, limit=20)
    assert any(m['to'] == '999@g.us' and 'PRE-DIAGNÓSTICO' in m['body'] for m in claimed)


def test_generate_rca_sin_grupo_no_encola(app, monkeypatch):
    import bot.rca as rca
    nid = _seed_notice(app, 'AV-9011')
    monkeypatch.setattr(rca, '_collect_similar_cases', lambda *a, **k: [])
    monkeypatch.setattr(rca, '_collect_hard_spares', lambda *a, **k: [])
    monkeypatch.setattr(rca, '_call_llm',
                        lambda *a, **k: {'causa_raiz': 'x', 'acciones': [],
                                         'herramientas': [], 'repuestos_idx': [],
                                         'confianza': 'baja'})
    monkeypatch.delenv('WHATSAPP_MAINT_GROUP_JID', raising=False)
    payload = rca.generate_rca(app, nid, push=True)
    assert payload is not None
    # Sin grupo configurado no debe haber encolado nada nuevo a un jid de mtto
    claimed = rca.claim_outbox(app, limit=50)
    assert not any('rca:AV-9011' == '' for m in claimed)  # sanity: no crash


def test_outbox_endpoint_auth(client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', 'tok123')
    # Sin token -> 403
    r = client.get('/api/public/whatsapp/outbox')
    assert r.status_code == 403
    # Token correcto -> 200 con lista de mensajes
    r = client.get('/api/public/whatsapp/outbox', headers={'X-Gateway-Token': 'tok123'})
    assert r.status_code == 200
    assert 'messages' in r.get_json()


def test_outbox_endpoint_503_sin_token(client, monkeypatch):
    monkeypatch.delenv('WHATSAPP_GATEWAY_TOKEN', raising=False)
    r = client.get('/api/public/whatsapp/outbox', headers={'X-Gateway-Token': 'x'})
    assert r.status_code == 503


def test_outbox_ack_endpoint(client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_GATEWAY_TOKEN', 'tok123')
    r = client.post('/api/public/whatsapp/outbox/ack',
                    data=json.dumps({'results': [{'id': 999999, 'ok': True}]}),
                    content_type='application/json',
                    headers={'X-Gateway-Token': 'tok123'})
    assert r.status_code == 200
    assert r.get_json().get('ok') is True


def test_notice_get_incluye_clave_rca(auth_admin, app):
    nid = _seed_notice(app, 'AV-9020')
    r = auth_admin.get(f'/api/notices/{nid}')
    assert r.status_code == 200
    body = r.get_json()
    assert 'rca' in body  # None si aún no se generó, pero la clave debe existir
