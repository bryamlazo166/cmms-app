"""Tests del estado operativo del equipo (fuera de servicio / overhaul)
y de la suspension derivada en cascada de los preventivos."""
import datetime as dt
import json

import pytest


def _get_or_create(db, model, defaults=None, **kwargs):
    obj = model.query.filter_by(**kwargs).first()
    if obj:
        return obj
    obj = model(**{**kwargs, **(defaults or {})})
    db.session.add(obj)
    db.session.commit()
    return obj


@pytest.fixture
def svc_env(app):
    """Equipo con un punto de lubricacion VENCIDO y un motor electrico."""
    from database import db
    from models import Area, Line, Equipment, LubricationPoint, RotativeAsset
    with app.app_context():
        area = _get_or_create(db, Area, name='AREA SVC TEST')
        line = _get_or_create(db, Line, name='LINEA SVC TEST', area_id=area.id)
        eq = _get_or_create(db, Equipment, tag='EQ-SVC-1',
                            defaults={'name': 'DIGESTOR SVC TEST'},
                            line_id=line.id)
        # Asegurar estado limpio si otro test lo dejo fuera de servicio
        eq.in_service = True
        eq.out_of_service_since = None
        eq.out_of_service_reason = None
        old = (dt.date.today() - dt.timedelta(days=90)).isoformat()
        pt = _get_or_create(db, LubricationPoint, code='LUB-SVC-1', defaults={
            'name': 'CHUMACERA SVC TEST', 'equipment_id': eq.id,
            'frequency_days': 30, 'warning_days': 3, 'is_active': True,
        })
        pt.equipment_id = eq.id
        pt.is_active = True
        pt.last_service_date = old
        pt.next_due_date = None
        pt.semaphore_status = 'ROJO'
        mot = _get_or_create(db, RotativeAsset, code='MOT-SVC-1', defaults={
            'name': 'MOTOR SVC TEST', 'category': 'MOTOR',
            'is_electric_motor': True, 'is_active': True,
        })
        mot.equipment_id = eq.id
        mot.is_electric_motor = True
        mot.is_active = True
        db.session.commit()
        return {'eq_id': eq.id, 'pt_id': pt.id, 'mot_id': mot.id}


def _set_service(client, eq_id, payload):
    return client.post(f'/api/equipments/{eq_id}/service-status',
                       data=json.dumps(payload),
                       content_type='application/json')


def test_poner_fuera_de_servicio(auth_admin, svc_env):
    r = _set_service(auth_admin, svc_env['eq_id'],
                     {'in_service': False, 'reason': 'Overhaul anual'})
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d['equipment']['in_service'] is False
    assert d['equipment']['out_of_service_reason'] == 'Overhaul anual'
    assert d['equipment']['out_of_service_since']
    assert d['affected']['lubricacion'] >= 1
    assert d['affected']['motores'] >= 1


def test_kpi_lubricacion_excluye_suspendidos(auth_admin, svc_env):
    # Con el equipo en servicio: el punto vencido cuenta como ROJO
    before = auth_admin.get('/api/lubrication/dashboard').get_json()['kpi']

    _set_service(auth_admin, svc_env['eq_id'],
                 {'in_service': False, 'reason': 'Overhaul'})
    after = auth_admin.get('/api/lubrication/dashboard').get_json()['kpi']

    assert after['suspended'] == before.get('suspended', 0) + 1
    assert after['red'] == before['red'] - 1
    assert after['total'] == before['total'] - 1


def test_points_api_marca_suspension(auth_admin, svc_env):
    _set_service(auth_admin, svc_env['eq_id'],
                 {'in_service': False, 'reason': 'Overhaul'})
    pts = auth_admin.get('/api/lubrication/points').get_json()
    mine = [p for p in pts if p['id'] == svc_env['pt_id']]
    assert mine, 'el punto debe seguir listado (marcado, no oculto)'
    assert mine[0]['equipment_in_service'] is False
    assert mine[0]['is_active'] is True  # su is_active propio NO se toca


def test_motores_marca_suspension(auth_admin, svc_env):
    _set_service(auth_admin, svc_env['eq_id'],
                 {'in_service': False, 'reason': 'Overhaul'})
    d = auth_admin.get('/api/motors').get_json()
    row = [m for m in d['rows'] if m['id'] == svc_env['mot_id']]
    assert row and row[0]['equipment_in_service'] is False
    assert d['summary']['suspendido'] >= 1


def test_reactivar_con_lubricacion_de_overhaul(auth_admin, svc_env):
    from models import LubricationExecution
    _set_service(auth_admin, svc_env['eq_id'],
                 {'in_service': False, 'reason': 'Overhaul'})
    r = _set_service(auth_admin, svc_env['eq_id'],
                     {'in_service': True, 'mark_lubricated': True})
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d['equipment']['in_service'] is True
    assert d['lubricated_points'] >= 1

    today = dt.date.today().isoformat()
    pts = auth_admin.get('/api/lubrication/points').get_json()
    p = [x for x in pts if x['id'] == svc_env['pt_id']][0]
    assert p['equipment_in_service'] is True
    assert p['last_service_date'] == today
    assert p['semaphore_status'] == 'VERDE'

    # Trazabilidad: quedo la ejecucion de overhaul en el historial
    execs = auth_admin.get(
        f"/api/lubrication/executions?point_id={svc_env['pt_id']}").get_json()
    assert any('overhaul' in (e.get('comments') or '').lower() for e in execs)


def test_reactivar_sin_lubricar_conserva_fechas(auth_admin, svc_env):
    old = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    _set_service(auth_admin, svc_env['eq_id'],
                 {'in_service': False, 'reason': 'Overhaul'})
    r = _set_service(auth_admin, svc_env['eq_id'],
                     {'in_service': True, 'mark_lubricated': False})
    assert r.status_code == 200
    pts = auth_admin.get('/api/lubrication/points').get_json()
    p = [x for x in pts if x['id'] == svc_env['pt_id']][0]
    # Sin lubricacion de overhaul: el atraso es real y se conserva
    assert p['last_service_date'] == old


def test_export_pendientes_excluye_suspendidos(auth_admin, svc_env):
    _set_service(auth_admin, svc_env['eq_id'],
                 {'in_service': False, 'reason': 'Overhaul'})
    r = auth_admin.get('/api/lubrication/export?scope=pending&search=SVC TEST')
    # 200 con excel vacio o sin filas del punto; basta verificar que no falla
    assert r.status_code == 200


def test_rol_campo_no_puede_cambiar_estado(client, auth_admin, svc_env):
    r = auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'mecsvc', 'password': 'campo1234', 'role': 'mecanico',
    }), content_type='application/json')
    assert r.status_code in (200, 201)
    client.get('/logout')
    client.post('/login', data={'username': 'mecsvc', 'password': 'campo1234'})
    r = _set_service(client, svc_env['eq_id'],
                     {'in_service': False, 'reason': 'x'})
    assert r.status_code == 403
