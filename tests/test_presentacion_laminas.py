"""Tests del selector de laminas de la presentacion mensual.

No todas las laminas sirven todos los meses: la de carga de trabajo necesita
la asignacion de personal cargada, y proyectada a medias resta credibilidad.
Se puede apagar antes de presentar, y la decision se guarda en la BD para que
valga tambien desde otra maquina.
"""
import json

import pytest

from routes.presentacion_routes import LAMINAS, SETTING_LAMINAS


CLAVES = [c for c, _ in LAMINAS]


def _meta(client, month='2026-08'):
    r = client.get(f'/api/presentacion/data?month={month}&vista=mes&meses=4&modo=inherente')
    assert r.status_code == 200
    return r.get_json()['meta']


def _guardar(client, visibles):
    return client.post('/api/presentacion/laminas',
                       data=json.dumps({'visibles': visibles}),
                       content_type='application/json')


def test_por_defecto_se_presentan_todas(auth_admin):
    laminas = _meta(auth_admin)['laminas']
    assert [l['clave'] for l in laminas] == CLAVES
    assert all(l['visible'] for l in laminas)
    assert all(l['nombre'] for l in laminas)


def test_apagar_una_lamina_y_que_persista(auth_admin):
    r = _guardar(auth_admin, [c for c in CLAVES if c != 'carga'])
    assert r.status_code == 200
    assert r.get_json()['ocultas'] == ['carga']

    # Se ve en la siguiente carga de la presentacion, no solo en la respuesta
    laminas = {l['clave']: l['visible'] for l in _meta(auth_admin)['laminas']}
    assert laminas['carga'] is False
    assert all(v for k, v in laminas.items() if k != 'carga')

    _guardar(auth_admin, CLAVES)      # dejar el estado limpio


def test_se_guarda_el_complemento_para_que_una_lamina_nueva_salga_encendida(app, auth_admin):
    """En la BD quedan las OCULTAS. Asi, si manana se agrega una lamina, no
    aparece escondida sin que nadie se entere."""
    _guardar(auth_admin, [c for c in CLAVES if c != 'carga'])
    with app.app_context():
        from database import db
        from models import AppSetting
        fila = db.session.get(AppSetting, SETTING_LAMINAS)
        assert fila.value == 'carga'
    _guardar(auth_admin, CLAVES)


def test_no_se_pueden_apagar_todas(auth_admin):
    r = _guardar(auth_admin, [])
    assert r.status_code == 400
    assert 'al menos una' in r.get_json()['error'].lower()
    # y la presentacion sigue completa
    assert all(l['visible'] for l in _meta(auth_admin)['laminas'])


def test_claves_invalidas_no_apagan_la_presentacion(auth_admin):
    r = _guardar(auth_admin, ['no_existe', 'otra_cosa'])
    assert r.status_code == 400
    assert all(l['visible'] for l in _meta(auth_admin)['laminas'])


def test_pide_una_lista(auth_admin):
    r = auth_admin.post('/api/presentacion/laminas', data=json.dumps({}),
                        content_type='application/json')
    assert r.status_code == 400


def test_la_pagina_identifica_cada_lamina(auth_admin):
    """El HTML tiene que marcar cada lamina y cada entrada del indice con su
    clave; si no, el selector no puede ocultarlas ni renumerarlas."""
    html = auth_admin.get('/indicadores-mensuales').data.decode('utf-8')
    for clave in CLAVES:
        assert f'data-slide="{clave}"' in html, f'falta la lamina {clave}'
        assert f'data-idx="{clave}"' in html, f'falta el indice de {clave}'
    assert 'data-slide="portada"' in html
    assert 'abrirLaminas()' in html


def test_requiere_login(client):
    client.get('/logout')
    r = client.post('/api/presentacion/laminas', data=json.dumps({'visibles': CLAVES}),
                    content_type='application/json')
    assert r.status_code in (302, 401)
