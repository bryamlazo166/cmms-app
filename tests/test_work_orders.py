"""Tests for work orders module."""
import json


def test_create_work_order(auth_admin):
    """Create an OT and verify code generation."""
    r = auth_admin.post('/api/work-orders', data=json.dumps({
        'description': 'Cambio rodamiento',
        'maintenance_type': 'Correctivo',
        'status': 'Abierta',
    }), content_type='application/json')
    assert r.status_code == 201
    assert r.json['code'].startswith('OT-')
    assert r.json['status'] == 'Abierta'


def test_create_ot_from_notice(auth_admin):
    """OT created from notice should propagate source."""
    # Create notice with source
    r1 = auth_admin.post('/api/notices', data=json.dumps({
        'description': 'Preventivo test',
        'maintenance_type': 'Preventivo',
        'source_type': 'lubrication',
        'source_id': 99,
    }), content_type='application/json')
    nid = r1.json['id']

    # Create OT from notice
    r2 = auth_admin.post('/api/work-orders', data=json.dumps({
        'notice_id': nid,
        'description': 'OT from notice',
        'maintenance_type': 'Preventivo',
        'status': 'Programada',
    }), content_type='application/json')
    assert r2.status_code == 201
    # Source should propagate from notice to OT
    assert r2.json.get('source_type') == 'lubrication'
    assert r2.json.get('source_id') == 99


def test_close_ot_updates_notice(auth_admin):
    """Closing an OT should set linked notice to Cerrado."""
    # Create notice
    r1 = auth_admin.post('/api/notices', data=json.dumps({
        'description': 'Will close',
    }), content_type='application/json')
    nid = r1.json['id']

    # Create OT from notice
    r2 = auth_admin.post('/api/work-orders', data=json.dumps({
        'notice_id': nid,
        'description': 'To close',
        'status': 'Abierta',
    }), content_type='application/json')
    ot_id = r2.json['id']

    # Close OT
    r3 = auth_admin.put(f'/api/work-orders/{ot_id}', data=json.dumps({
        'status': 'Cerrada',
        'real_start_date': '2026-03-30T08:00',
        'real_end_date': '2026-03-30T10:00',
        'real_duration': 2.0,
    }), content_type='application/json')
    assert r3.status_code == 200

    # Check notice is closed
    r4 = auth_admin.get(f'/api/notices/{nid}')
    assert r4.json['status'] == 'Cerrado'


def test_ot_log_entries(auth_admin):
    """Test OT activity log (bitacora)."""
    # Create OT
    r = auth_admin.post('/api/work-orders', data=json.dumps({
        'description': 'Log test',
        'status': 'En Progreso',
    }), content_type='application/json')
    ot_id = r.json['id']

    # Add log entry
    r2 = auth_admin.post(f'/api/work_orders/{ot_id}/log', data=json.dumps({
        'log_date': '2026-03-15',
        'log_type': 'PROVEEDOR',
        'comment': 'Proveedor retira equipo',
    }), content_type='application/json')
    assert r2.status_code == 201

    # List entries
    r3 = auth_admin.get(f'/api/work_orders/{ot_id}/log')
    assert len(r3.json) == 1
    assert r3.json[0]['log_type'] == 'PROVEEDOR'

    # Delete entry
    log_id = r3.json[0]['id']
    r4 = auth_admin.delete(f'/api/work_orders/{ot_id}/log/{log_id}')
    assert r4.status_code == 200


def test_ot_report_tracking(auth_admin):
    """Test report required/received tracking."""
    # Create OT
    r = auth_admin.post('/api/work-orders', data=json.dumps({
        'description': 'Report test',
        'status': 'Cerrada',
    }), content_type='application/json')
    ot_id = r.json['id']

    # Set report required
    r2 = auth_admin.put(f'/api/work_orders/{ot_id}/report', data=json.dumps({
        'report_required': True,
        'report_status': 'PENDIENTE',
        'report_due_date': '2026-04-15',
    }), content_type='application/json')
    assert r2.status_code == 200

    # Check pending reports
    r3 = auth_admin.get('/api/pending-reports')
    pending = r3.json
    assert any(p['id'] == ot_id for p in pending)


def test_pagination_work_orders(auth_admin):
    """Work orders with ?page= should return paginated format."""
    r = auth_admin.get('/api/work-orders?page=1&per_page=2')
    assert r.status_code == 200
    data = r.json
    assert 'items' in data
    assert 'pagination' in data
