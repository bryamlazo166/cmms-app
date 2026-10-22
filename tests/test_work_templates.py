"""Tests de trabajos estandar (OTs repetitivas que salen ya llenas)."""
import json

import pytest


@pytest.fixture
def plant(app):
    """Area con TH1, TH2 (con chumacera conducida) y un molino sin ella."""
    from database import db
    from models import Area, Line, Equipment, System, Component
    import uuid
    with app.app_context():
        area = Area(name=f'PLATAFORMA WT {uuid.uuid4().hex[:6]}')
        db.session.add(area)
        db.session.flush()
        line = Line(name='TRANSPORTE WT', area_id=area.id)
        db.session.add(line)
        db.session.flush()
        ids = {'area': area.id, 'line': line.id}
        for tag in ('WT-TH2', 'WT-TH1', 'WT-TH10'):
            eq = Equipment(name=f'TORNILLO {tag}', tag=tag, line_id=line.id)
            db.session.add(eq)
            db.session.flush()
            sys_ = System(name='SISTEMA DE ACCIONAMIENTO', equipment_id=eq.id)
            db.session.add(sys_)
            db.session.flush()
            comp = Component(name='CHUMACERA CONDUCIDA', system_id=sys_.id)
            other = Component(name='CHUMACERA MOTRIZ', system_id=sys_.id)
            db.session.add_all([comp, other])
            db.session.flush()
            ids[tag] = {'eq': eq.id, 'sys': sys_.id, 'comp': comp.id}
        mol = Equipment(name='MOLINO WT', tag='WT-MOL', line_id=line.id)
        db.session.add(mol)
        db.session.flush()
        ids['WT-MOL'] = {'eq': mol.id}
        db.session.commit()
        return ids


def _post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type='application/json')


def _create_template(client, plant, **extra):
    payload = {
        'name': 'Cambio de chumacera conducida',
        'description_template': 'Cambio de chumacera conducida del {tag}',
        'maintenance_type': 'Correctivo',
        'component_name': 'chumacera conducida',
        'area_id': plant['area'],
        'estimated_duration': 4,
        'tech_count': 2,
        'specialty': 'MECANICO',
        'materials': [
            {'item_type': 'free', 'name': 'Chumacera SNH 516', 'quantity': 1, 'unit': 'UND'},
            {'name': ''},  # se descarta
        ],
    }
    payload.update(extra)
    r = _post(client, '/api/work-templates', payload)
    assert r.status_code == 201, r.json
    return r.json


def test_template_requires_name_and_description(auth_admin):
    r = _post(auth_admin, '/api/work-templates', {'name': 'X'})
    assert r.status_code == 400


def test_targets_only_equipment_with_component(auth_admin, plant):
    tpl = _create_template(auth_admin, plant)
    assert len(tpl['materials']) == 1
    r = auth_admin.get(f"/api/work-templates/{tpl['id']}/targets")
    assert r.status_code == 200
    targets = r.json['targets']
    # El molino no tiene chumacera conducida; la chumacera motriz no cuenta
    assert [t['equipment_tag'] for t in targets] == ['WT-TH1', 'WT-TH2', 'WT-TH10']
    assert all(t['component_name'] == 'CHUMACERA CONDUCIDA' for t in targets)
    assert targets[0]['description'] == 'Cambio de chumacera conducida del WT-TH1'


def test_preview_targets_unsaved(auth_admin, app, plant):
    r = _post(auth_admin, '/api/work-templates/preview-targets', {
        'component_name': 'chumacera conducida', 'area_id': plant['area'], 'tag_filter': 'TH1',
    })
    assert r.status_code == 200
    assert r.json['tags'] == ['WT-TH1', 'WT-TH10']
    from models import WorkTemplate
    with app.app_context():
        assert WorkTemplate.query.filter_by(component_name='chumacera conducida', tag_filter='TH1').count() == 0


def test_generate_ot_only(auth_admin, app, plant):
    tpl = _create_template(auth_admin, plant)
    th1 = plant['WT-TH1']
    r = _post(auth_admin, f"/api/work-templates/{tpl['id']}/generate", {
        'targets': [{'equipment_id': th1['eq'], 'system_id': th1['sys'], 'component_id': th1['comp']}],
        'scheduled_date': '2026-10-25',
        'create_notice': False,
    })
    assert r.status_code == 201, r.json
    created = r.json['created']
    assert len(created) == 1 and created[0]['notice_code'] is None

    from models import WorkOrder, OTPersonnel, OTLogEntry, WorkTemplate
    with app.app_context():
        wo = WorkOrder.query.get(created[0]['id'])
        assert wo.code.startswith('OT-')
        assert wo.notice_id is None
        assert wo.status == 'Programada'
        assert wo.scheduled_date == '2026-10-25'
        assert wo.description == 'Cambio de chumacera conducida del WT-TH1'
        assert (wo.area_id, wo.line_id, wo.equipment_id, wo.system_id, wo.component_id) == \
            (plant['area'], plant['line'], th1['eq'], th1['sys'], th1['comp'])
        assert wo.estimated_duration == 4 and wo.tech_count == 2
        people = OTPersonnel.query.filter_by(work_order_id=wo.id).all()
        assert len(people) == 2 and all(p.specialty == 'MECANICO' for p in people)
        log = OTLogEntry.query.filter_by(work_order_id=wo.id).one()
        assert 'Chumacera SNH 516' in log.comment
        assert WorkTemplate.query.get(tpl['id']).use_count == 1


def test_generate_with_notice_and_open_ot_warning(auth_admin, app, plant):
    tpl = _create_template(auth_admin, plant, create_notice=True, priority='Alta')
    th2 = plant['WT-TH2']
    r = _post(auth_admin, f"/api/work-templates/{tpl['id']}/generate", {
        'targets': [{'equipment_id': th2['eq'], 'component_id': th2['comp']}],
    })
    assert r.status_code == 201, r.json
    item = r.json['created'][0]
    assert item['notice_code'].startswith('AV-')

    from models import WorkOrder, MaintenanceNotice
    with app.app_context():
        wo = WorkOrder.query.get(item['id'])
        assert wo.status == 'Abierta'
        assert wo.system_id == th2['sys']  # se deduce del componente
        notice = MaintenanceNotice.query.get(wo.notice_id)
        assert notice.ot_number == wo.code
        assert notice.status == 'En Tratamiento'
        assert notice.priority == 'Alta'
        assert notice.component_id == th2['comp']

    # La siguiente vista de equipos avisa que TH2 ya tiene una OT abierta
    r = auth_admin.get(f"/api/work-templates/{tpl['id']}/targets")
    by_tag = {t['equipment_tag']: t for t in r.json['targets']}
    assert by_tag['WT-TH2']['open_ot_code'] == item['code']
    assert by_tag['WT-TH1']['open_ot_code'] is None


def test_generate_rejects_foreign_component(auth_admin, app, plant):
    tpl = _create_template(auth_admin, plant)
    r = _post(auth_admin, f"/api/work-templates/{tpl['id']}/generate", {
        'targets': [{'equipment_id': plant['WT-MOL']['eq'], 'component_id': plant['WT-TH1']['comp']}],
    })
    assert r.status_code == 400
    from models import WorkOrder
    with app.app_context():
        assert WorkOrder.query.filter_by(equipment_id=plant['WT-MOL']['eq']).count() == 0


def test_fixed_equipment_template(auth_admin, plant):
    tpl = _create_template(auth_admin, plant,
                           name='Cambio de plancha de sacrificio',
                           description_template='Cambio de plancha de sacrificio del {equipo}',
                           component_name='', equipment_id=plant['WT-MOL']['eq'])
    r = auth_admin.get(f"/api/work-templates/{tpl['id']}/targets")
    targets = r.json['targets']
    assert len(targets) == 1
    assert targets[0]['description'] == 'Cambio de plancha de sacrificio del MOLINO WT'


def test_draft_from_ot_replaces_tag(auth_admin, plant):
    th1 = plant['WT-TH1']
    r = _post(auth_admin, '/api/work-orders', {
        'description': 'Cambio de chumacera conducida WT-TH1 por desgaste',
        'maintenance_type': 'Correctivo',
        'equipment_id': th1['eq'],
        'component_id': th1['comp'],
        'estimated_duration': 3,
    })
    ot_id = r.json['id']
    r = auth_admin.get(f'/api/work-templates/draft-from-ot/{ot_id}')
    assert r.status_code == 200
    assert r.json['description_template'] == 'Cambio de chumacera conducida {tag} por desgaste'
    assert r.json['component_name'] == 'CHUMACERA CONDUCIDA'
    assert r.json['estimated_duration'] == 3


def test_viewer_cannot_generate(auth_admin, plant, client):
    tpl = _create_template(auth_admin, plant)
    auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'wtviewer', 'password': 'viewer123', 'role': 'viewer'
    }), content_type='application/json')
    client.get('/logout')
    client.post('/login', data={'username': 'wtviewer', 'password': 'viewer123'})
    th1 = plant['WT-TH1']
    r = _post(client, f"/api/work-templates/{tpl['id']}/generate", {
        'targets': [{'equipment_id': th1['eq'], 'component_id': th1['comp']}],
    })
    assert r.status_code == 403
