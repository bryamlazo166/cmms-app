"""Configuracion compartida de DeepSeek.

DeepSeek retiro el modelo 'deepseek-chat' (julio 2026): la API ahora solo
acepta 'deepseek-v4-pro' o 'deepseek-v4-flash'. Flash es el sucesor directo
del tier chat (rapido/economico), y es el default aqui.

Los modelos v4 razonan por defecto (emiten 'reasoning_content'), lo que
consume el max_tokens antes de producir la respuesta final y multiplica la
latencia. Todas las llamadas del CMMS pasan 'thinking': disabled para
conservar el comportamiento (costo/latencia/formato) que tenia deepseek-chat.
"""
import os

DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash')
DEEPSEEK_THINKING = {'type': 'disabled'}
