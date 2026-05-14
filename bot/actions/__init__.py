"""Acciones del bot Telegram, separadas por dominio.

Cada accion expone una funcion `(app, data) -> (result | None, error | None)`
o tuplas mas anchas si la accion devuelve mas datos para el dispatcher.
El dispatcher en bot/telegram_bot.py importa de aca.
"""
from bot.actions.hammer_batches import change_hammer_batch, receive_hammer_batch
from bot.actions.specs import replicate_specs
from bot.actions.inspection import register_inspection

__all__ = [
    'change_hammer_batch',
    'receive_hammer_batch',
    'replicate_specs',
    'register_inspection',
]
