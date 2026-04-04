"""Tests for other modules: inspection, monitoring, activities, calendar, etc."""
import json


def test_inspection_crud(auth_admin):
    """Test inspection route + items + execution."""
    # Create route
    r = auth_admin.post('/api/inspection/routes', data=json.dumps({
        'name': 'Test Ronda',
        'frequency_days': 7,
    }), content_type='application/json')
    assert r.status_code == 201
    route_id = r.json['id']
    assert r.json['code'].startswith('INSP-')

    # Add item
    r2 = auth_admin.post(f'/api/inspection/routes/{route_id}/items', data=json.dumps({
        'description': 'Check alignment',
        'item_type': 'CHECK',
    }), content_type='application/json')
    assert r2.status_code == 201
    item_id = r2.json['id']

    # Execute
    r3 = auth_admin.post('/api/inspection/executions', data=json.dumps({
        'route_id': route_id,
        'execution_date': '2026-03-30',
        'executed_by': 'Tester',
        'results': [{'item_id': item_id, 'result': 'OK'}],
    }), content_type='application/json')
    assert r3.status_code == 201
    assert r3.json['overall_result'] == 'OK'


def test_activity_with_milestones(auth_admin):
    """Test activity + milestone lifecycle."""
    # Create activity
    r = auth_admin.post('/api/activities', data=json.dumps({
        'title': 'Test Fabricacion',
        'activity_type': 'FABRICACION',
        'priority': 'ALTA',
    }), content_type='application/json')
    assert r.status_code == 201
    act_id = r.json['id']
    assert r.json['status'] == 'ABIERTA'

    # Add milestones
    r2 = auth_admin.post(f'/api/activities/{act_id}/milestones', data=json.dumps({
        'description': 'Plano aprobado',
    }), content_type='application/json')
    assert r2.status_code == 201
    ms_id = r2.json['id']

    # Activity should be EN_PROGRESO now
    r3 = auth_admin.get('/api/activities?all=true')
    act = next(a for a in r3.json if a['id'] == act_id)
    assert act['status'] == 'EN_PROGRESO'
    assert act['milestones_total'] == 1

    # Complete milestone
    r4 = auth_admin.put(f'/api/milestones/{ms_id}', data=json.dumps({
        'status': 'COMPLETADO',
        'comment': 'Done',
    }), content_type='application/json')
    assert r4.status_code == 200

    # Activity should be COMPLETADA (all milestones done)
    r5 = auth_admin.get('/api/activities?all=true')
    act2 = next(a for a in r5.json if a['id'] == act_id)
    assert act2['status'] == 'COMPLETADA'


def test_maintenance_calendar(auth_admin):
    """Calendar endpoint should return events."""
    r = auth_admin.get('/api/maintenance-calendar')
    assert r.status_code == 200
    assert isinstance(r.json, list)


def test_dashboard_stats(auth_admin):
    """Dashboard stats endpoint should work."""
    r = auth_admin.get('/api/dashboard-stats')
    assert r.status_code == 200
    assert 'kpi' in r.json
    assert 'charts' in r.json
    assert 'recent' in r.json


def test_dashboard_kpis(auth_admin):
    """Dashboard KPIs with drill-down."""
    r = auth_admin.get('/api/dashboard-kpis?days=90&level=area')
    assert r.status_code == 200
    assert 'kpis' in r.json
    assert 'items' in r.json


def test_dashboard_trends(auth_admin):
    """Dashboard trends with cost data."""
    r = auth_admin.get('/api/dashboard-trends?months=6')
    assert r.status_code == 200
    assert 'trends' in r.json
    assert len(r.json['trends']) == 6


def test_powerbi_export(auth_admin):
    """Power BI export should generate Excel with all sheets."""
    r = auth_admin.get('/api/reports/powerbi-export')
    assert r.status_code == 200
    assert 'spreadsheet' in r.content_type


def test_db_maintenance_admin_only(auth_admin, client):
    """DB maintenance should be admin-only."""
    # Admin can access
    r = auth_admin.get('/api/admin/db-stats')
    assert r.status_code == 200

    # Create non-admin
    auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'nonadmin', 'password': 'nonadmin123', 'role': 'tecnico'
    }), content_type='application/json')
    client.get('/logout')
    client.post('/login', data={'username': 'nonadmin', 'password': 'nonadmin123'})

    r2 = client.get('/api/admin/db-stats')
    assert r2.status_code == 403
