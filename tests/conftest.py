"""Shared test fixtures for CMMS tests."""
import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DB_MODE'] = 'local'
os.environ['ALLOW_LOCAL_FALLBACK'] = '1'
os.environ['LOCAL_DATABASE_URL'] = 'sqlite://'  # In-memory DB for tests
# Desactivar rate limiting en tests (sino el limite "10 per 1 minute" en /login
# rompe la suite entera despues del 10mo test que use auth_admin).
os.environ['RATELIMIT_ENABLED'] = 'False'


@pytest.fixture(scope='session')
def app():
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    flask_app.config['RATELIMIT_ENABLED'] = False
    # Desactivar el Flask-Limiter en runtime tambien (por si fue creado antes
    # de que se aplicaran las env vars).
    try:
        from app import limiter as _limiter
        _limiter.enabled = False
    except Exception:
        pass
    with flask_app.app_context():
        from database import db
        db.create_all()
        from models import User
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='admin', full_name='Admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_admin(client):
    """Login as admin and return client."""
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    return client


@pytest.fixture
def auth_viewer(client, auth_admin):
    """Create and login as viewer."""
    import json
    auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'testviewer', 'password': 'viewer123', 'role': 'viewer'
    }), content_type='application/json')
    client.get('/logout')
    client.post('/login', data={'username': 'testviewer', 'password': 'viewer123'})
    return client


@pytest.fixture
def auth_supervisor(client, auth_admin):
    """Create and login as supervisor."""
    import json
    auth_admin.post('/api/auth/users', data=json.dumps({
        'username': 'testsup', 'password': 'sup123456', 'role': 'supervisor'
    }), content_type='application/json')
    client.get('/logout')
    client.post('/login', data={'username': 'testsup', 'password': 'sup123456'})
    return client
