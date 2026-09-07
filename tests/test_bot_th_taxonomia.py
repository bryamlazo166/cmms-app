"""Tests de las reglas de taxonomia de los transportadores helicoidales (TH).

En los TH la jerga del taller no coincide con el arbol y el matcher generico
elegia mal el componente. Estas reglas (bot/resolvers.py) son deterministas:

  "se rompio el tornillo helicoidal"  -> TUBO CENTRAL  (el conjunto = el tubo)
  "se rompio el disco / la helice"    -> HELICE        (los alabes)
  "el TH se bloqueo"                  -> RELE TERMICO  (lo que actua)

Y no deben intervenir cuando la persona nombra otro componente del TH.

No tocan la BD: se le pasa al resolvedor un stub con las filas del arbol.
"""
import pytest

from bot.resolvers import th_component_override, COMPONENT_SYNONYMS


# Arbol de un TH real (SEC2-TH1): (component_id, nombre, system_id, sistema)
TH_ROWS = [
    (660, 'EJE CENTRAL', 70, 'TORNILLO SINFIN'),
    (661, 'EJE DE COLA', 70, 'TORNILLO SINFIN'),
    (662, 'EJE MOTRIZ', 70, 'TORNILLO SINFIN'),
    (663, 'HELICE', 70, 'TORNILLO SINFIN'),
    (665, 'TUBO CENTRAL', 70, 'TORNILLO SINFIN'),
    (938, 'CHUMACERA CONDUCIDA', 71, 'SISTEMA DE ACCIONAMIENTO'),
    (939, 'CHUMACERA MOTRIZ', 71, 'SISTEMA DE ACCIONAMIENTO'),
    (940, 'MOTORREDUCTOR', 71, 'SISTEMA DE ACCIONAMIENTO'),
    (936, 'CADENA', 71, 'SISTEMA DE ACCIONAMIENTO'),
    (1919, 'RELE TERMICO', 72, 'SISTEMA ELECTRICO'),
    (1920, 'RELE AUXILIAR', 72, 'SISTEMA ELECTRICO'),
    (1946, 'VARIADOR DE FRECUENCIA', 72, 'SISTEMA ELECTRICO'),
]

# Arbol de un equipo que NO es TH: las reglas no deben tocarlo.
NO_TH_ROWS = [
    (100, 'MOTOR ELECTRICO', 20, 'SISTEMA DE ACCIONAMIENTO'),
    (101, 'HELICE', 20, 'SISTEMA DE ACCIONAMIENTO'),
]


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _stmt, _params=None):
        return self

    def fetchall(self):
        return self.rows


class _FakeDb:
    def __init__(self, rows):
        self.session = _FakeSession(rows)


def _run(msg, rows=TH_ROWS):
    """Devuelve el nombre del componente que eligen las reglas, o None."""
    hit = th_component_override(_FakeDb(rows), lambda q: q, 40, msg)
    if not hit:
        return None
    return next(name for cid, name, _s, _sn in rows if cid == hit[0])


# ── El conjunto del tornillo es el TUBO CENTRAL, no la helice ───────────────

@pytest.mark.parametrize("msg", [
    "el tornillo helicoidal del TH1 del secador 2 se ha roto",
    "se rompio el tornillo sin fin del TH1",
    "se rajo el sinfin del TH1 secador #2",
    "el gusano del TH1 esta fisurado",
    "fisura en el tubo central del TH2",
])
def test_conjunto_del_tornillo_es_tubo_central(msg):
    assert _run(msg) == 'TUBO CENTRAL'


# ── Los alabes son la HELICE, solo cuando se los nombra ─────────────────────

@pytest.mark.parametrize("msg", [
    "se rompio el disco del tornillo helicoidal del TH1 secador 2",
    "se rompio la helice del TH1 del secador 2",
    "la hélice del TH1 esta desgastada",
    "se soltaron las espiras del TH1",
    "las paletas del TH1 estan gastadas",
])
def test_disco_o_helice_es_helice(msg):
    assert _run(msg) == 'HELICE'


def test_disco_gana_al_tornillo_cuando_aparecen_los_dos():
    # "disco del tornillo helicoidal" nombra el alabe: manda la mencion explicita.
    assert _run("se rompio el disco del tornillo helicoidal del TH1") == 'HELICE'


# ── El bloqueo se anota contra el RELE TERMICO ──────────────────────────────

@pytest.mark.parametrize("msg", [
    "el TH1 del secador 2 se ha bloqueado",
    "el TH1 se atasco con material",
    "el TH1 se trabo",
    "el TH1 se paro por sobrecarga",
    "el TH1 disparo el termico",
    "TH1 obstruido, no avanza el producto",
])
def test_bloqueo_es_rele_termico(msg):
    assert _run(msg) == 'RELE TERMICO'


# ── Si la persona nombra otro componente, manda lo que dijo ─────────────────

@pytest.mark.parametrize("msg", [
    "se rompio la chumacera motriz del TH1 del secador 2",
    "el motorreductor del TH1 hace ruido",
    "se salio la cadena del TH1",
    "el eje motriz del TH1 esta doblado",
    "el variador del TH1 marca falla",
    "el rele auxiliar del TH1 no engancha",
])
def test_no_interviene_si_nombran_otro_componente(msg):
    assert _run(msg) is None


def test_no_aplica_fuera_de_los_th():
    # Mismo lenguaje, pero el equipo no tiene sistema TORNILLO SINFIN.
    assert _run("se rompio la helice", rows=NO_TH_ROWS) is None
    assert _run("se bloqueo el equipo", rows=NO_TH_ROWS) is None


def test_sin_texto_o_sin_equipo_no_hace_nada():
    assert th_component_override(_FakeDb(TH_ROWS), lambda q: q, 40, "") is None
    assert th_component_override(_FakeDb(TH_ROWS), lambda q: q, None, "se bloqueo el TH1") is None


# ── El diccionario de sinonimos quedo coherente con las reglas ──────────────

def test_tornillo_helicoidal_ya_no_es_sinonimo_de_helice():
    assert 'tornillo helicoidal' not in COMPONENT_SYNONYMS['helice']
    assert 'sinfin' not in COMPONENT_SYNONYMS['helice']
    assert 'tornillo helicoidal' in COMPONENT_SYNONYMS['tubo central']
    assert 'disco' in COMPONENT_SYNONYMS['helice']
