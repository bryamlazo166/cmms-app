"""Respuestas con humor para frases sueltas — compartidas por Telegram y WhatsApp.

Viven aparte del flujo de avisos a proposito: se resuelven ANTES de llamar a la
IA, asi que no gastan una consulta a DeepSeek ni corren el riesgo de que el
extractor intente abrir una orden de trabajo por "auditoria ISO 45001".

Para agregar una broma nueva basta con sumar una entrada a EASTER_EGGS: un
detector y su lista de respuestas.
"""
import random
import re
import unicodedata


def _normalizar(texto):
    """Minusculas y sin tildes, para que 'auditoría' y 'auditoria' sean lo mismo."""
    t = (texto or '').lower()
    t = unicodedata.normalize('NFD', t)
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')


# ── Auditoria ISO ────────────────────────────────────────────────────────

# Numeros de norma con limite de palabra: "9001" suelto es la norma, pero
# dentro de un codigo de repuesto (SKF 90015) no lo es.
_RE_NORMAS = re.compile(r'(?<!\d)(9001|14001|45001)(?!\d)')
# Palabras de auditoria por raiz, tambien con limite: "iso" como subcadena
# vive dentro de "piso" y "aviso", que aparecen todo el tiempo en planta.
_RE_AUDITORIA = re.compile(r'\b(audit\w*|(?:re)?certific\w*|norma\w*|iso)\b')


def _detecta_auditoria_iso(norm):
    """Dispara con las normas ISO de gestion.

    Dos normas juntas ya son inconfundibles. Con una sola se exige ademas una
    palabra de auditoria, para no saltar si el numero viene en el codigo de un
    repuesto. Y nunca por "iso" a secas: el aceite ISO VG 220 es un consumible
    normalisimo, no una auditoria.
    """
    encontradas = set(_RE_NORMAS.findall(norm))
    if len(encontradas) >= 2:
        return True
    return bool(encontradas) and bool(_RE_AUDITORIA.search(norm))


_RESPUESTAS_AUDITORIA = [
    "Clarísimo. Mañana 5 a.m. pintamos el piso, escondemos los trapos detrás "
    "del digestor #4 y le decimos al auditor que ese ruido *siempre* ha sonado "
    "así. Certificación asegurada. 🎨",

    "Plan infalible, toma nota:\n"
    "• *9001* — imprimimos procedimientos que nadie ha leído y los metemos en "
    "un folder bonito.\n"
    "• *14001* — el aceite del piso pasa a llamarse «muestra para análisis».\n"
    "• *45001* — le prestamos casco al primero que pase por ahí.\n"
    "Las tres en un día. Somos unos genios. 🏆",

    "Mira, yo te doy MTBF, MTTR y disponibilidad al toque. Pero que el auditor "
    "no pregunte justo por el equipo que está parado... eso ya no es un bot, "
    "eso es suerte. 🍀",

    "¿Mañana? Perfecto. Tenemos unas 14 horas para 3 normas: 4 horas y media "
    "por norma. Técnicamente posible, siempre que nadie duerma y nadie "
    "pregunte nada. ⏱️",

    "La 45001 pide identificar los peligros del trabajo. Ya identifiqué uno: "
    "preparar tres auditorías en un día. Riesgo alto, probabilidad segura. ⚠️",

    "Cuenta conmigo. Yo distraigo al auditor con un gráfico de tendencia bien "
    "bonito mientras tú escondes el extintor vencido. Eso es trabajo en "
    "equipo. 🧯",

    "Consejo profesional: cuando el auditor pregunte «¿dónde está el "
    "registro?», *no* respondas «en el corazón». Ya lo intentaron. No "
    "funciona. 💔",

    "Puedo generarte 47 indicadores con fórmula y trazabilidad en 3 segundos. "
    "Lo que no puedo explicar es por qué la carpeta de capacitaciones tiene "
    "una sola hoja y está en blanco. 📄",

    "Ya lo tengo: le decimos que trabajamos con «mantenimiento predictivo "
    "basado en la intuición del maestro». Suena innovador. Capaz hasta nos dan "
    "un reconocimiento. 🔮",

    "La 14001 la sacamos fácil: la planta está tan limpia que hasta el polvo "
    "se fue solo. Las otras dos van a necesitar café. Mucho café. ☕",

    "Acepto, pero que quede en acta: yo vengo avisando desde el CMMS que hay "
    "un montón de OTs abiertas y nadie me hace caso. Cuando el auditor "
    "pregunte, yo tengo el historial. 🧾",

    "Traducción de «mañana ayúdame con tres ISO»: hoy nadie duerme. Yo voy "
    "preparando el checklist, tú vas preparando las excusas. 📝",

    "Buenas noticias: tus indicadores están calculados, ponderados y "
    "auditables. Malas noticias: el auditor va a preguntar por el rótulo del "
    "tablero, no por el MTBF. 🏷️",

    "Dato real: la norma no exige que la planta sea perfecta, exige que "
    "*demuestres* que sabes que no lo es. Eso sí lo tenemos de sobra. 📊",

    "Hecho. Le voy diciendo al secador #2 que se comporte mañana, que hay "
    "visita. A ver si me hace caso — conmigo nunca lo ha hecho. 🙃",
]


# Registro de bromas: (detector, respuestas). Sumar entradas aqui.
EASTER_EGGS = [
    ('auditoria_iso', _detecta_auditoria_iso, _RESPUESTAS_AUDITORIA),
]

# Ultima respuesta enviada por conversacion, para no repetir dos veces
# seguidas: la misma broma dos veces mata el chiste.
_ULTIMA = {}


def responder(texto, conversacion=None):
    """Respuesta con humor si el texto dispara alguna broma, o None.

    conversacion: identificador del chat (chat_id, telefono...) para no
    repetir la misma respuesta de forma consecutiva.
    """
    norm = _normalizar(texto)
    if not norm:
        return None
    for nombre, detecta, respuestas in EASTER_EGGS:
        try:
            if not detecta(norm):
                continue
        except Exception:
            continue
        if not respuestas:
            return None
        clave = (nombre, conversacion)
        previa = _ULTIMA.get(clave)
        opciones = [r for r in respuestas if r != previa] or list(respuestas)
        elegida = random.choice(opciones)
        _ULTIMA[clave] = elegida
        if len(_ULTIMA) > 500:          # cota: es una cache de cortesia
            _ULTIMA.clear()
        return elegida
    return None
