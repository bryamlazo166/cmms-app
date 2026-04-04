"""Tests for preventive maintenance cycle."""
import json


def test_generate_preventive_notices(auth_admin):
    """Generator should create avisos for overdue points."""
    # Create a lubrication point that's overdue
    auth_admin.post('/api/lubrication/points', data=json.dumps({
        'name': 'Test Lub Overdue',
        'frequency_days': 1,
        'warning_days': 0,
        'last_service_date': '2025-01-01',
    }), content_type='application/json')

    # Generate
    r = auth_admin.post('/api/generate-preventive-ots')
    assert r.status_code == 200
    assert r.json['created'] >= 1

    # Second run should skip (already has open notice)
    r2 = auth_admin.post('/api/generate-preventive-ots')
    assert r2.json['skipped'] >= 1


def test_notifications_scan(auth_admin):
    """Notification scan should detect overdue points."""
    r = auth_admin.post('/api/notifications/scan')
    assert r.status_code == 200
    assert 'created' in r.json


def test_notification_count(auth_admin):
    """Should return unread count."""
    r = auth_admin.get('/api/notifications/count')
    assert r.status_code == 200
    assert 'count' in r.json


def test_mark_notifications_read(auth_admin):
    """Should mark all as read."""
    r = auth_admin.post('/api/notifications/read',
                        data=json.dumps({}),
                        content_type='application/json')
    assert r.status_code == 200
