"""Tests for maintenance notices module."""
import json


def test_create_notice(auth_admin):
    """Create a notice and verify code generation."""
    r = auth_admin.post('/api/notices', data=json.dumps({
        'description': 'Motor hace ruido',
        'maintenance_type': 'Correctivo',
        'priority': 'Alta',
        'reporter_name': 'Test User',
        'reporter_type': 'PRODUCCION',
    }), content_type='application/json')
    assert r.status_code == 201
    data = r.json
    assert data['code'].startswith('AV-')
    assert data['status'] == 'Pendiente'
    assert data['description'] == 'Motor hace ruido'


def test_list_notices_ordered(auth_admin):
    """Notices should be ordered by id desc (most recent first)."""
    # Create two notices
    auth_admin.post('/api/notices', data=json.dumps({
        'description': 'First notice',
    }), content_type='application/json')
    auth_admin.post('/api/notices', data=json.dumps({
        'description': 'Second notice',
    }), content_type='application/json')

    r = auth_admin.get('/api/notices')
    notices = r.json
    assert len(notices) >= 2
    # First in list should have higher ID
    assert notices[0]['id'] > notices[1]['id']


def test_pagination(auth_admin):
    """Notices with ?page= should return paginated format."""
    r = auth_admin.get('/api/notices?page=1&per_page=2')
    assert r.status_code == 200
    data = r.json
    assert 'items' in data
    assert 'pagination' in data
    assert data['pagination']['page'] == 1
    assert data['pagination']['per_page'] == 2


def test_no_pagination_returns_array(auth_admin):
    """Without ?page=, should return plain array (backward compat)."""
    r = auth_admin.get('/api/notices')
    assert r.status_code == 200
    assert isinstance(r.json, list)


def test_update_notice(auth_admin):
    """Update a notice status."""
    # Create
    r = auth_admin.post('/api/notices', data=json.dumps({
        'description': 'To update',
    }), content_type='application/json')
    nid = r.json['id']

    # Update
    r2 = auth_admin.put(f'/api/notices/{nid}', data=json.dumps({
        'status': 'Anulado',
        'cancellation_reason': 'Test anulacion',
    }), content_type='application/json')
    assert r2.status_code == 200
    assert r2.json['status'] == 'Anulado'
