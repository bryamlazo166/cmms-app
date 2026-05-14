"""Telemetria del bot Telegram: tokens, latencia, costo USD.

Cada llamada a Whisper o DeepSeek se persiste como `BotUsage`. Las
funciones aca son no-bloqueantes (best-effort): si la DB no responde,
loggea warning y sigue — nunca rompe el flujo del bot.

Tarifas referenciales (pueden cambiar; actualizar si el proveedor cambia):
- Whisper: USD 0.006 / minuto de audio
- DeepSeek Chat:
    * Cache miss input:  USD 0.27 / 1M tokens
    * Cache hit  input:  USD 0.07 / 1M tokens
    * Output:            USD 1.10 / 1M tokens

Para Whisper estimamos duracion ~= bytes / 16000 (audio OGG opus voz ~16kbps).
Es aproximacion: lo importante es el orden de magnitud.
"""
import logging
import time

logger = logging.getLogger(__name__)

# Tarifas USD por unidad
WHISPER_USD_PER_MINUTE = 0.006
DEEPSEEK_USD_PER_M_INPUT = 0.27
DEEPSEEK_USD_PER_M_INPUT_CACHED = 0.07
DEEPSEEK_USD_PER_M_OUTPUT = 1.10

# OGG opus voz aprox 16 kbps = 2000 bytes/seg
OGG_OPUS_BYTES_PER_SEC = 2000


def _estimate_audio_seconds(audio_bytes):
    if not audio_bytes or audio_bytes <= 0:
        return None
    return round(audio_bytes / OGG_OPUS_BYTES_PER_SEC, 1)


def _whisper_cost(audio_seconds):
    if not audio_seconds:
        return 0.0
    return round((audio_seconds / 60.0) * WHISPER_USD_PER_MINUTE, 6)


def _deepseek_cost(tokens_in, tokens_out, tokens_cached=0):
    if not tokens_in and not tokens_out:
        return 0.0
    ti = max(0, (tokens_in or 0) - (tokens_cached or 0))
    tc = (tokens_cached or 0)
    to = (tokens_out or 0)
    cost = (
        ti * DEEPSEEK_USD_PER_M_INPUT / 1_000_000 +
        tc * DEEPSEEK_USD_PER_M_INPUT_CACHED / 1_000_000 +
        to * DEEPSEEK_USD_PER_M_OUTPUT / 1_000_000
    )
    return round(cost, 6)


def track_whisper(app, chat_id, audio_bytes, latency_ms, status='success', error_msg=None):
    """Registra una llamada a Whisper."""
    audio_seconds = _estimate_audio_seconds(audio_bytes)
    cost = _whisper_cost(audio_seconds) if status == 'success' else 0.0
    _persist(app, dict(
        chat_id=chat_id,
        service='whisper',
        model_name='whisper-1',
        audio_bytes=audio_bytes,
        audio_duration_s=audio_seconds,
        latency_ms=latency_ms,
        cost_usd=cost,
        status=status,
        error_msg=error_msg,
    ))


def track_deepseek(app, chat_id, model_name, usage_dict, latency_ms, status='success', error_msg=None):
    """Registra una llamada a DeepSeek. usage_dict viene del response.usage."""
    usage_dict = usage_dict or {}
    tokens_in = usage_dict.get('prompt_tokens')
    tokens_out = usage_dict.get('completion_tokens')
    tokens_cached = usage_dict.get('prompt_cache_hit_tokens') or 0
    cost = _deepseek_cost(tokens_in, tokens_out, tokens_cached) if status == 'success' else 0.0
    _persist(app, dict(
        chat_id=chat_id,
        service='deepseek',
        model_name=model_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cached=tokens_cached,
        latency_ms=latency_ms,
        cost_usd=cost,
        status=status,
        error_msg=error_msg,
    ))


def _persist(app, fields):
    """Inserta una fila en bot_usage. Best-effort (no rompe el flujo)."""
    if app is None:
        return
    try:
        with app.app_context():
            from database import db as _db
            from models import BotUsage
            row = BotUsage(**fields)
            _db.session.add(row)
            _db.session.commit()
    except Exception as e:
        logger.warning(f"bot_usage persist fallo: {e}")
        try:
            from database import db as _db
            _db.session.rollback()
        except Exception:
            pass


class Stopwatch:
    """Helper para medir latencia. Uso:
        with Stopwatch() as sw: ...
        sw.elapsed_ms
    """
    def __enter__(self):
        self.t0 = time.monotonic()
        self.elapsed_ms = 0
        return self

    def __exit__(self, *args):
        self.elapsed_ms = int((time.monotonic() - self.t0) * 1000)
