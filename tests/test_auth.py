"""Tests for authentication and role-based access."""
import json


def test_health_no_auth(client):
    """Health endpoint should work without login."""
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json['status'] == 'ok'


def test_login_redirect(client):
    """Unauthenticated page request redirects to login."""
    r = client.get('/')
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_api_unauthorized(client):
    """Unauthenticated API request returns 401 JSON."""
    r = client.get('/api/notices')
    assert r.status_code == 401
    assert 'error' in r.json


def test_login_success(client):
    """Valid credentials should login and redirect."""
    r = client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert r.status_code == 302  # redirect to dashboard


def test_login_failure(client):
    """Invalid credentials show error."""
    r = client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    assert r.status_code == 200  # stays on login page
    assert b'incorrectos' in r.data


def test_admin_full_access(auth_admin):
    """Admin should access all endpoints."""
    assert auth_admin.get('/api/notices').status_code == 200
    assert auth_admin.get('/api/work-orders').status_code == 200
    assert auth_admin.get('/api/auth/users').status_code == 200
    assert auth_admin.get('/api/admin/db-stats').status_code == 200


def test_viewer_read_only(auth_viewer):
    """Viewer can GET but not POST/PUT/DELETE."""
    # GET allowed
    r = auth_viewer.get('/api/notices')
    assert r.status_code == 200

    # POST blocked
    r = auth_viewer.post('/api/notices', data=json.dumps({
        'description': 'test'
    }), content_type='application/json')
    assert r.status_code == 403

    # Export blocked
    r = auth_viewer.get('/api/reports/powerbi-export')
    assert r.status_code == 403


def test_viewer_cannot_manage_users(auth_viewer):
    """Viewer cannot access user management."""
    r = auth_viewer.get('/api/auth/users')
    assert r.status_code == 403


def test_create_user(auth_admin):
    """Admin can create new users."""
    r = auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'newtech',
        'password': 'tech123456',
        'role': 'tecnico',
        'full_name': 'New Tech',
    }), content_type='application/json')
    assert r.status_code == 201
    assert r.json['role'] == 'tecnico'


def test_change_password(auth_admin):
    """User can change own password."""
    r = auth_admin.post('/api/auth/change-password', data=json.dumps({
        'current_password': 'admin123',
        'new_password': 'admin456',
    }), content_type='application/json')
    assert r.status_code == 200

    # Change back
    auth_admin.post('/api/auth/change-password', data=json.dumps({
        'current_password': 'admin456',
        'new_password': 'admin123',
    }), content_type='application/json')
