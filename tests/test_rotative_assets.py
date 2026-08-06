"""Ciclo de vida de un activo rotativo: instalar, cambiar, retirar, recibir.

Cubre lo que se rompia en produccion:
  - el swap no ofrecia candidatos porque los leia de la tabla ya filtrada;
  - retirar dejaba el activo "Disponible" aunque se hubiera ido al taller;
  - el historial del rotativo mostraba la lubricacion de las chumaceras del
    equipo, que son del sistema de transmision y no del motorreductor.
"""
import json

import pytest


def _post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type='application/json')


@pytest.fixture(autouse=True)
def clean_rotative(app):
    """La base de tests vive toda la sesion: cada test arranca sin rotativos.

    Sin esto los activos de un test aparecen como repuestos disponibles en el
    siguiente y los conteos de candidatos dejan de ser deterministas.
    """
    from database import db
    from models import (RotativeAsset, RotativeAssetHistory, RotativeAssetSpec,
                        LubricationExecution, LubricationPoint)

    with app.app_context():
        for model in (LubricationExecution, LubricationPoint, RotativeAssetHistory,
                      RotativeAssetSpec, RotativeAsset):
            db.session.query(model).delete()
        db.session.commit()
    yield


@pytest.fixture
def hierarchy(app):
    """Area / linea / equipo / sistema / componentes minimos (idempotente)."""
    from database import db
    from models import Area, Line, Equipment, System, Component

    def _get_or_create(model, defaults=None, **lookup):
        row = db.session.query(model).filter_by(**lookup).first()
        if row is None:
            row = model(**lookup, **(defaults or {}))
            db.session.add(row)
            db.session.flush()
        return row

    with app.app_context():
        area = _get_or_create(Area, name='COCCION TEST')
        line = _get_or_create(Line, name='LINEA TEST', area_id=area.id)
        eq = _get_or_create(Equipment, name='SECADOR TEST',
                            defaults={'tag': 'SECA-TEST'}, line_id=line.id)
        system = _get_or_create(System, name='TRANSMISION', equipment_id=eq.id)
        comp_mr = _get_or_create(Component, name='MOTORREDUCTOR', system_id=system.id)
        comp_chum = _get_or_create(Component, name='CHUMACERA MOTRIZ', system_id=system.id)
        db.session.commit()
        return {
            'area_id': area.id, 'line_id': line.id, 'equipment_id': eq.id,
            'system_id': system.id, 'comp_mr': comp_mr.id, 'comp_chum': comp_chum.id,
        }


@pytest.fixture
def assets(auth_admin, hierarchy):
    """Un motorreductor instalado y dos repuestos: uno igual, uno de otro tipo."""
    installed = _post(auth_admin, '/api/rotative-assets', {
        'name': 'MOTORREDUCTOR SECADOR TEST', 'category': 'MOTORREDUCTOR',
        'brand': 'ROSSI', 'model': 'MR-V-100', 'status': 'Disponible',
    }).get_json()
    spare_same = _post(auth_admin, '/api/rotative-assets', {
        'name': 'MOTORREDUCTOR STOCK', 'category': 'Motorreductor',  # otra caja
        'brand': 'ROSSI', 'model': 'MR-V-100', 'status': 'Disponible',
    }).get_json()
    spare_other = _post(auth_admin, '/api/rotative-assets', {
        'name': 'BOMBA STOCK', 'category': 'BOMBA CENTRIFUGA',
        'status': 'Disponible',
    }).get_json()

    res = _post(auth_admin, f"/api/rotative-assets/{installed['id']}/install", {
        'event_date': '2026-01-10',
        'area_id': hierarchy['area_id'], 'line_id': hierarchy['line_id'],
        'equipment_id': hierarchy['equipment_id'], 'system_id': hierarchy['system_id'],
        'component_id': hierarchy['comp_mr'],
    })
    assert res.status_code == 200, res.get_json()
    return {'installed': installed, 'spare_same': spare_same, 'spare_other': spare_other}


class TestSwapCandidates:
    def test_lista_los_disponibles_ordenados_por_compatibilidad(self, auth_admin, assets):
        res = auth_admin.get(f"/api/rotative-assets/{assets['installed']['id']}/swap-candidates")
        assert res.status_code == 200
        data = res.get_json()

        codes = [c['code'] for c in data['candidates']]
        assert assets['spare_same']['code'] in codes
        assert assets['spare_other']['code'] in codes
        # El del mismo tipo y modelo va primero
        assert codes[0] == assets['spare_same']['code']
        assert data['summary']['disponibles'] == 2
        assert data['summary']['compatibles'] == 1

    def test_marca_el_de_otro_tipo_como_poco_compatible(self, auth_admin, assets):
        data = auth_admin.get(
            f"/api/rotative-assets/{assets['installed']['id']}/swap-candidates").get_json()
        by_code = {c['code']: c for c in data['candidates']}

        same = by_code[assets['spare_same']['code']]
        assert same['match_level'] == 'ALTA'
        assert any('Mismo tipo' in r for r in same['reasons'])
        assert any('Mismo modelo' in r for r in same['reasons'])

        other = by_code[assets['spare_other']['code']]
        assert other['match_level'] == 'BAJA'
        assert any('Tipo distinto' in w for w in other['warnings'])

    def test_no_ofrece_los_instalados_ni_los_de_baja(self, auth_admin, assets):
        _post(auth_admin, f"/api/rotative-assets/{assets['spare_other']['id']}/remove",
              {'destination': 'BAJA', 'reason': 'Carcasa rajada'})
        data = auth_admin.get(
            f"/api/rotative-assets/{assets['installed']['id']}/swap-candidates").get_json()

        codes = [c['code'] for c in data['candidates']]
        assert assets['spare_other']['code'] not in codes
        assert assets['installed']['code'] not in codes
        assert [c['code'] for c in data['discarded']] == [assets['spare_other']['code']]


class TestRemoval:
    def test_al_taller_deja_trazabilidad_y_libera_la_ubicacion(self, auth_admin, assets):
        res = _post(auth_admin, f"/api/rotative-assets/{assets['installed']['id']}/remove", {
            'event_date': '2026-03-01', 'destination': 'TALLER',
            'reason': 'Rodamiento lado acople trabado',
            'expected_return_date': '2026-03-15',
        })
        assert res.status_code == 200
        a = res.get_json()

        assert a['status'] == 'En Taller'
        assert a['out_since'] == '2026-03-01'
        assert a['out_reason'] == 'Rodamiento lado acople trabado'
        assert a['expected_return_date'] == '2026-03-15'
        assert a['equipment_id'] is None and a['install_date'] is None

    def test_a_proveedor_exige_saber_a_quien_se_envio(self, auth_admin, assets):
        res = _post(auth_admin, f"/api/rotative-assets/{assets['installed']['id']}/remove",
                    {'destination': 'PROVEEDOR', 'reason': 'Rebobinado'})
        assert res.status_code == 400
        assert 'proveedor' in res.get_json()['error'].lower()

    def test_a_proveedor_registra_el_tercero(self, auth_admin, assets):
        provider = _post(auth_admin, '/api/providers',
                         {'name': 'TALLER EXTERNO SAC', 'specialty': 'Reductores'}).get_json()
        res = _post(auth_admin, f"/api/rotative-assets/{assets['installed']['id']}/remove", {
            'destination': 'PROVEEDOR', 'provider_id': provider['id'],
            'reason': 'Cambio de corona', 'expected_return_date': '2026-04-01',
        })
        assert res.status_code == 200
        a = res.get_json()
        assert a['status'] == 'En Proveedor'
        assert a['service_provider_name'] == 'TALLER EXTERNO SAC'

    def test_standby_no_arrastra_motivo_de_falla(self, auth_admin, assets):
        a = _post(auth_admin, f"/api/rotative-assets/{assets['installed']['id']}/remove",
                  {'destination': 'STANDBY'}).get_json()
        assert a['status'] == 'Disponible'
        assert a['out_since'] is None and a['out_reason'] is None

    def test_el_flujo_viejo_con_new_status_sigue_funcionando(self, auth_admin, assets):
        a = _post(auth_admin, f"/api/rotative-assets/{assets['installed']['id']}/remove",
                  {'new_status': 'En Taller'}).get_json()
        assert a['status'] == 'En Taller'


class TestReturnToService:
    def test_recibir_reparado_lo_devuelve_al_pool(self, auth_admin, assets):
        aid = assets['installed']['id']
        _post(auth_admin, f'/api/rotative-assets/{aid}/remove',
              {'destination': 'TALLER', 'reason': 'Ruido en reductor'})

        a = _post(auth_admin, f'/api/rotative-assets/{aid}/return-to-service', {
            'event_date': '2026-03-20', 'new_status': 'Disponible',
            'work_done': 'Cambio de rodamientos 6308',
        }).get_json()

        assert a['status'] == 'Disponible'
        assert a['out_since'] is None and a['expected_return_date'] is None

        hist = auth_admin.get(f'/api/rotative-assets/{aid}/history').get_json()
        assert hist[0]['event_type'] == 'RETORNO_SERVICIO'
        assert 'Cambio de rodamientos 6308' in hist[0]['comments']

    def test_irreparable_queda_de_baja(self, auth_admin, assets):
        aid = assets['installed']['id']
        _post(auth_admin, f'/api/rotative-assets/{aid}/remove', {'destination': 'TALLER'})
        a = _post(auth_admin, f'/api/rotative-assets/{aid}/return-to-service',
                  {'new_status': 'Baja'}).get_json()
        assert a['status'] == 'Baja'


class TestSwap:
    def test_el_reemplazo_hereda_la_ubicacion_y_el_viejo_va_al_taller(self, auth_admin, assets, hierarchy):
        res = _post(auth_admin, '/api/rotative-assets/swap', {
            'remove_asset_id': assets['installed']['id'],
            'install_asset_id': assets['spare_same']['id'],
            'date': '2026-05-02', 'destination': 'TALLER',
            'reason': 'Fuga de aceite por reten',
        })
        assert res.status_code == 200, res.get_json()
        data = res.get_json()

        assert data['installed']['status'] == 'Instalado'
        assert data['installed']['equipment_id'] == hierarchy['equipment_id']
        assert data['installed']['component_id'] == hierarchy['comp_mr']
        assert data['installed']['install_date'] == '2026-05-02'

        assert data['removed']['status'] == 'En Taller'
        assert data['removed']['equipment_id'] is None
        assert data['removed']['out_reason'] == 'Fuga de aceite por reten'

    def test_rechaza_instalar_uno_que_ya_esta_montado(self, auth_admin, assets, hierarchy):
        _post(auth_admin, f"/api/rotative-assets/{assets['spare_same']['id']}/install", {
            'area_id': hierarchy['area_id'], 'line_id': hierarchy['line_id'],
            'equipment_id': hierarchy['equipment_id'],
        })
        res = _post(auth_admin, '/api/rotative-assets/swap', {
            'remove_asset_id': assets['installed']['id'],
            'install_asset_id': assets['spare_same']['id'],
        })
        assert res.status_code == 400
        assert 'ya esta instalado' in res.get_json()['error']

    def test_rechaza_instalar_uno_de_baja(self, auth_admin, assets):
        _post(auth_admin, f"/api/rotative-assets/{assets['spare_same']['id']}/remove",
              {'destination': 'BAJA'})
        res = _post(auth_admin, '/api/rotative-assets/swap', {
            'remove_asset_id': assets['installed']['id'],
            'install_asset_id': assets['spare_same']['id'],
        })
        assert res.status_code == 400
        assert 'Baja' in res.get_json()['error']

    def test_ambos_movimientos_quedan_en_el_historial(self, auth_admin, assets):
        _post(auth_admin, '/api/rotative-assets/swap', {
            'remove_asset_id': assets['installed']['id'],
            'install_asset_id': assets['spare_same']['id'],
            'reason': 'Vibracion excesiva',
        })
        salida = auth_admin.get(
            f"/api/rotative-assets/{assets['installed']['id']}/history").get_json()
        entrada = auth_admin.get(
            f"/api/rotative-assets/{assets['spare_same']['id']}/history").get_json()

        assert salida[0]['event_type'] == 'RETIRO'
        assert 'Taller interno' in salida[0]['comments']
        assert assets['spare_same']['code'] in salida[0]['comments']
        # El retiro conserva de donde salio, aunque el activo ya no tenga ubicacion
        assert salida[0]['equipment_name'] == 'SECADOR TEST'

        assert entrada[0]['event_type'] == 'INSTALACION'
        assert assets['installed']['code'] in entrada[0]['comments']


class TestFullHistory:
    """El historial del rotativo no es el historial del equipo que lo aloja."""

    @pytest.fixture
    def con_lubricacion(self, app, auth_admin, assets, hierarchy):
        from database import db
        from models import LubricationPoint, LubricationExecution

        with app.app_context():
            propio = LubricationPoint(
                code='LUB-MR-TEST', name='ACEITE REDUCTOR SECADOR TEST',
                equipment_id=hierarchy['equipment_id'], system_id=hierarchy['system_id'],
                component_id=hierarchy['comp_mr'], lubricant_name='ISO VG 220')
            chumacera = LubricationPoint(
                code='LUB-CHM-TEST', name='LUBRICACION CHUMACERA MOTRIZ #1',
                equipment_id=hierarchy['equipment_id'], system_id=hierarchy['system_id'],
                component_id=hierarchy['comp_chum'], lubricant_name='GRASA FRIXO 177')
            db.session.add_all([propio, chumacera])
            db.session.flush()
            db.session.add_all([
                LubricationExecution(point_id=propio.id, execution_date='2026-02-01',
                                     action_type='CAMBIO'),
                LubricationExecution(point_id=chumacera.id, execution_date='2026-02-02',
                                     action_type='SERVICIO'),
            ])
            db.session.commit()
            return {'propio': propio.code, 'chumacera': chumacera.code}

    def test_la_lubricacion_de_chumaceras_no_cuenta_como_del_activo(
            self, auth_admin, assets, con_lubricacion):
        data = auth_admin.get(
            f"/api/rotative-assets/{assets['installed']['id']}/full-history").get_json()

        propios = [e for e in data['events']
                   if e['category'] == 'LUBRICACION' and e['scope'] == 'ACTIVO']
        entorno = [e for e in data['events']
                   if e['category'] == 'LUBRICACION' and e['scope'] == 'EQUIPO']

        assert [e['code'] for e in propios] == [con_lubricacion['propio']]
        assert [e['code'] for e in entorno] == [con_lubricacion['chumacera']]
        # El contador que alimenta los chips solo cuenta lo del activo
        assert data['counts']['lubricacion'] == 1
        assert data['counts']['entorno'] == 1

    def test_los_movimientos_del_activo_siempre_son_suyos(self, auth_admin, assets):
        data = auth_admin.get(
            f"/api/rotative-assets/{assets['installed']['id']}/full-history").get_json()
        movimientos = [e for e in data['events'] if e['category'] == 'MOVIMIENTO']
        assert movimientos
        assert all(e['scope'] == 'ACTIVO' for e in movimientos)
