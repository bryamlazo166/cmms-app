"""Las bromas del bot: que salten cuando toca y NUNCA cuando no toca.

El riesgo real no es que falle el chiste, es que se coma un reporte de falla:
si un tecnico escribe algo que dispare la broma por error, su aviso no se
registra. Por eso la mitad de las pruebas son mensajes normales de planta que
tienen que pasar de largo.
"""
from bot.easter_eggs import _RESPUESTAS_AUDITORIA, responder


def test_la_frase_de_la_auditoria_dispara():
    """La frase que pidio el usuario, y sus variantes naturales."""
    frases = [
        'Mañana ayudame a aprobar la auditoria 9001, 14001 y 45001',
        'mañana ayúdame a aprobar la auditoría 9001, 14001 y 45001',   # con tildes
        'MAÑANA AYUDAME A APROBAR LA AUDITORIA 9001, 14001 Y 45001',   # gritando
        '9001 14001 45001',                       # dos o mas normas: inconfundible
        'oye viene la auditoria iso 9001',        # una norma + palabra de auditoria
        'nos recertifican en 45001 la proxima semana',
        'hay que certificar la 45001 este año',
        'el auditor viene por la 14001',
        'la norma 9001 nos cae encima el lunes',
    ]
    for f in frases:
        assert responder(f, 'chat') is not None, f'no disparo con: {f}'


def test_los_mensajes_de_planta_pasan_de_largo():
    """Un reporte de falla NUNCA debe terminar en un chiste: se perderia."""
    normales = [
        'el motor del molino 2 esta calentando y hace ruido',
        'el digestor 9 tiene fuga de vapor en la tapa',
        # ISO VG 220 es un aceite normalisimo: 'iso' suelto no puede disparar
        'cambiar aceite ISO VG 220 del reductor del secador',
        # 'iso' vive dentro de 'piso' y 'aviso'
        'el piso del area de molino esta con aceite',
        'revisar el aviso AV-9001 que dejo el turno noche',
        # numero de norma dentro de un codigo de repuesto
        'rodamiento SKF 90015 para el transportador',
        'la norma del rodamiento es 6205',
        'necesito el informe de la OT-0312',
        'hola',
        '',
        None,
    ]
    for f in normales:
        assert responder(f, 'chat') is None, f'disparo indebidamente con: {f}'


def test_hay_variedad_y_no_repite_seguido():
    """Varias respuestas, y nunca la misma dos veces seguidas: mata el chiste."""
    assert len(_RESPUESTAS_AUDITORIA) >= 10
    assert len(set(_RESPUESTAS_AUDITORIA)) == len(_RESPUESTAS_AUDITORIA)

    frase = 'auditoria 9001 14001 45001'
    vistas, previa = set(), None
    for _ in range(40):
        r = responder(frase, 'chat-variedad')
        assert r != previa, 'repitio la misma broma dos veces seguidas'
        vistas.add(r)
        previa = r
    assert len(vistas) >= 8, 'muy poca variedad en las respuestas'

    # Cada conversacion lleva su propia rotacion
    a = responder(frase, 'chat-a')
    b = responder(frase, 'chat-b')
    assert a and b


def test_las_respuestas_estan_bien_formadas():
    for r in _RESPUESTAS_AUDITORIA:
        assert r.strip() == r and len(r) > 40
        # WhatsApp corta los mensajes largos y en Telegram se leen mal
        assert len(r) <= 600, f'respuesta demasiado larga: {r[:50]}...'
        # El asterisco de negrita tiene que venir en pares para que WhatsApp
        # no muestre el simbolo suelto
        assert r.count('*') % 2 == 0, f'negrita sin cerrar: {r[:50]}...'
