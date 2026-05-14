"""Acciones del bot Telegram, separadas por dominio.

Cada accion expone una funcion `(app, data) -> (result | None, error | None)`.
El dispatcher en bot/telegram_bot.py importa de aca.
"""
from bot.actions.hammer_batches import change_hammer_batch, receive_hammer_batch

__all__ = [
    'change_hammer_batch',
    'receive_hammer_batch',
]
