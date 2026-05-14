"""Tests de telemetria del bot (bot/metrics.py).

Cubre:
  - Calculo de costo Whisper y DeepSeek
  - Estimacion de duracion de audio desde bytes
  - Persistencia en bot_usage
  - Endpoint /api/admin/bot-usage: resumen, por servicio, por dia, por chat
  - Solo admin puede ver el endpoint
"""
import json
import pytest

from bot.metrics import (
    _estimate_audio_seconds,
    _whisper_cost,
    _deepseek_cost,
    track_whisper,
    track_deepseek,
)


# ── Calculo de costo (funciones puras) ───────────────────────────────────────

def test_estimate_audio_seconds():
    # 60 segundos ~= 60 * 2000 bytes
    assert _estimate_audio_seconds(120_000) == 60.0
    assert _estimate_audio_seconds(0) is None
    assert _estimate_audio_seconds(None) is None


def test_whisper_cost_per_minute():
    # 60 segundos = 1 minuto = $0.006
    assert _whisper_cost(60) == 0.006
    assert _whisper_cost(30) == 0.003
    assert _whisper_cost(0) == 0.0
    assert _whisper_cost(None) == 0.0


def test_deepseek_cost_basic():
    # 1M tokens input puros (sin cache): $0.27
    assert _deepseek_cost(1_000_000, 0, 0) == 0.27
    # 1M tokens output: $1.10
    assert _deepseek_cost(0, 1_000_000, 0) == 1.10
    # Mix: 1M input + 100k output = $0.27 + $0.11 = $0.38
    assert _deepseek_cost(1_000_000, 100_000, 0) == 0.38


def test_deepseek_cost_with_cache_hit():
    # 1M tokens input con cache hit del 100%: $0.07 (no $0.27)
    assert _deepseek_cost(1_000_000, 0, 1_000_000) == 0.07
    # Mix: 50% cached
    # 500k regular = 0.135, 500k cached = 0.035 → total 0.17
    cost = _deepseek_cost(1_000_000, 0, 500_000)
    assert abs(cost - 0.17) < 0.001


def test_deepseek_cost_empty():
    assert _deepseek_cost(None, None, None) == 0.0
    assert _deepseek_cost(0, 0, 0) == 0.0


# ── Persistencia ─────────────────────────────────────────────────────────────

def test_track_whisper_persists(app):
    track_whisper(app, chat_id=99001, audio_bytes=60 * 2000, latency_ms=1500)
    with app.app_context():
        from models import BotUsage
        row = BotUsage.query.filter_by(chat_id=99001, service='whisper').first()
        assert row is not None
        assert row.audio_duration_s == 60.0
        assert row.cost_usd == 0.006
        assert row.status == 'success'
        assert row.latency_ms == 1500


def test_track_deepseek_persists(app):
    track_deepseek(app, chat_id=99002, model_name='deepseek-chat',
                   usage_dict={'prompt_tokens': 10000, 'completion_tokens': 500,
                               'prompt_cache_hit_tokens': 3000},
                   latency_ms=2800)
    with app.app_context():
        from models import BotUsage
        row = BotUsage.query.filter_by(chat_id=99002, service='deepseek').first()
        assert row is not None
        assert row.tokens_in == 10000
        assert row.tokens_out == 500
        assert row.tokens_cached == 3000
        # 7000 regular * 0.27/M + 3000 cached * 0.07/M + 500 out * 1.10/M
        # = 0.00189 + 0.00021 + 0.00055 = 0.00265
        assert abs(row.cost_usd - 0.00265) < 0.0001


def test_track_error_does_not_charge(app):
    track_deepseek(app, chat_id=99003, model_name='deepseek-chat',
                   usage_dict=None, latency_ms=0,
                   status='error', error_msg='HTTP 429 rate limited')
    with app.app_context():
        from models import BotUsage
        row = BotUsage.query.filter_by(chat_id=99003, service='deepseek').first()
        assert row is not None
        assert row.status == 'error'
        assert row.cost_usd == 0.0
        assert '429' in row.error_msg


def test_track_persist_best_effort_with_none_app(app):
    """track_* nunca debe romper el flujo del bot, incluso con app=None."""
    track_whisper(None, chat_id=99004, audio_bytes=100, latency_ms=10)
    track_deepseek(None, chat_id=99004, model_name='deepseek-chat',
                   usage_dict={'prompt_tokens': 100, 'completion_tokens': 10},
                   latency_ms=10)
    # No debe haber excepcion


# ── Endpoint admin ───────────────────────────────────────────────────────────

def test_bot_usage_endpoint_returns_summary(auth_admin, app):
    # Inserto algunas llamadas
    track_whisper(app, chat_id=88001, audio_bytes=30 * 2000, latency_ms=1200)
    track_deepseek(app, chat_id=88001, model_name='deepseek-chat',
                   usage_dict={'prompt_tokens': 5000, 'completion_tokens': 200},
                   latency_ms=3100)
    track_deepseek(app, chat_id=88002, model_name='deepseek-chat',
                   usage_dict=None, latency_ms=0, status='error', error_msg='HTTP 500')

    r = auth_admin.get('/api/admin/bot-usage?days=7')
    assert r.status_code == 200
    data = r.json
    assert data['period_days'] == 7
    assert data['grand_totals']['calls'] >= 3
    assert data['grand_totals']['cost_usd'] >= 0

    by_service = {s['service']: s for s in data['by_service']}
    assert 'whisper' in by_service
    assert 'deepseek' in by_service
    # Al menos 1 error registrado en deepseek
    assert by_service['deepseek']['errors'] >= 1


def test_bot_usage_endpoint_by_chat(auth_admin, app):
    track_deepseek(app, chat_id=77777, model_name='deepseek-chat',
                   usage_dict={'prompt_tokens': 1000, 'completion_tokens': 50},
                   latency_ms=100)
    r = auth_admin.get('/api/admin/bot-usage?days=7')
    chats = {c['chat_id'] for c in r.json['by_chat']}
    assert 77777 in chats


def test_bot_usage_endpoint_requires_admin(auth_supervisor):
    """Un supervisor no admin no debe ver el dashboard."""
    r = auth_supervisor.get('/api/admin/bot-usage?days=7')
    assert r.status_code == 403


def test_bot_usage_period_clamping(auth_admin):
    """days fuera de rango se clampa a [1, 365]."""
    r = auth_admin.get('/api/admin/bot-usage?days=0')
    assert r.status_code == 200
    assert r.json['period_days'] == 1

    r = auth_admin.get('/api/admin/bot-usage?days=99999')
    assert r.status_code == 200
    assert r.json['period_days'] == 365
