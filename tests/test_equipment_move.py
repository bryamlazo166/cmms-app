"""Mudanza de un equipo a otra linea/area y export de repuestos por equipo."""
import json


def _crear_estructura(auth_admin, sufijo):
    """Area de secado y area de molino, con un equipo ENFRIADOR en secado.
    El sufijo evita choques de nombre entre tests (la BD es de sesion)."""
    r = auth_admin.post('/api/areas', data=json.dumps({'name': f'SECADO {sufijo}'}),
                        content_type='application/json')
    area_origen = r.get_json()['id']
    r = auth_admin.post('/api/areas', data=json.dumps({'name': f'MOLINO {sufijo}'}),
                        content_type='application/json')
    area_destino = r.get_json()['id']

    r = auth_admin.post('/api/lines', data=json.dumps(
        {'name': f'LINEA SECADO {sufijo}', 'area_id': area_origen}),
        content_type='application/json')
    linea_origen = r.get_json()['id']
    r = auth_admin.post('/api/lines', data=json.dumps(
        {'name': f'LINEA MOLINO {sufijo}', 'area_id': area_destino}),
        content_type='application/json')
    linea_destino = r.get_json()['id']

    r = auth_admin.post('/api/equipments', data=json.dumps(
        {'name': f'ENFRIADOR {sufijo}', 'tag': f'ENF-{sufijo}', 'line_id': linea_origen}),
        content_type='application/json')
    equipo = r.get_json()['id']

    return {
        'area_origen': area_origen, 'area_destino': area_destino,
        'linea_origen': linea_origen, 'linea_destino': linea_destino,
        'equipo': equipo,
    }


def test_move_preview_muestra_ubicacion_actual(auth_admin):
    ids = _crear_estructura(auth_admin, 'A1')
    r = auth_admin.get(f"/api/equipments/{ids['equipo']}/move")
    assert r.status_code == 200
    d = r.get_json()
    assert d['equipment']['tag'] == 'ENF-A1'
    assert d['current']['area_name'] == 'SECADO A1'
    assert d['current']['line_name'] == 'LINEA SECADO A1'
    assert isinstance(d['impact'], dict)


def test_move_arrastra_activos_y_lubricacion(auth_admin, app):
    ids = _crear_estructura(auth_admin, 'A2')
    with app.app_context():
        from database import db
        from models import RotativeAsset, LubricationPoint, MaintenanceNotice

        activo = RotativeAsset(
            code='MOT-TEST-1', name='MOTOR ENFRIADOR', status='Instalado',
            area_id=ids['area_origen'], line_id=ids['linea_origen'],
            equipment_id=ids['equipo'])
        punto = LubricationPoint(
            code='LUB-TEST-1', name='CHUMACERA ENFRIADOR',
            area_id=ids['area_origen'], line_id=ids['linea_origen'],
            equipment_id=ids['equipo'], lubricant_name='GRASA NLGI 2',
            frequency_days=30)
        aviso = MaintenanceNotice(
            code='AV-TEST-1', description='Ruido en enfriador', status='ABIERTO',
            area_id=ids['area_origen'], line_id=ids['linea_origen'],
            equipment_id=ids['equipo'])
        db.session.add_all([activo, punto, aviso])
        db.session.commit()
        activo_id, punto_id, aviso_id = activo.id, punto.id, aviso.id

    r = auth_admin.post(f"/api/equipments/{ids['equipo']}/move", data=json.dumps({
        'target_line_id': ids['linea_destino'],
        'comment': 'reubicacion por implementacion',
    }), content_type='application/json')
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d['to']['area_name'] == 'MOLINO A2'

    with app.app_context():
        from models import (Equipment, RotativeAsset, LubricationPoint,
                            MaintenanceNotice, RotativeAssetHistory)
        eq = Equipment.query.get(ids['equipo'])
        assert eq.line_id == ids['linea_destino']

        # Todo lo que colgaba del equipo quedo en la nueva ubicacion.
        for modelo, oid in ((RotativeAsset, activo_id),
                            (LubricationPoint, punto_id),
                            (MaintenanceNotice, aviso_id)):
            fila = modelo.query.get(oid)
            assert fila.area_id == ids['area_destino'], modelo.__name__
            assert fila.line_id == ids['linea_destino'], modelo.__name__

        # La mudanza queda registrada en el historial del activo rotativo.
        hist = RotativeAssetHistory.query.filter_by(asset_id=activo_id).all()
        assert any('reubicacion por implementacion' in (h.comments or '')
                   for h in hist)


def test_move_rechaza_linea_invalida(auth_admin):
    ids = _crear_estructura(auth_admin, 'A3')
    r = auth_admin.post(f"/api/equipments/{ids['equipo']}/move", data=json.dumps(
        {'target_line_id': ids['linea_origen']}), content_type='application/json')
    assert r.status_code == 400

    r = auth_admin.post(f"/api/equipments/{ids['equipo']}/move", data=json.dumps(
        {'target_line_id': 999999}), content_type='application/json')
    assert r.status_code == 404

    r = auth_admin.post(f"/api/equipments/{ids['equipo']}/move", data=json.dumps({}),
                        content_type='application/json')
    assert r.status_code == 400


def test_export_bom_devuelve_excel(auth_admin, app):
    ids = _crear_estructura(auth_admin, 'A4')
    with app.app_context():
        from database import db
        from models import (RotativeAsset, RotativeAssetBOM, RotativeAssetSpec,
                            WarehouseItem, WarehouseMovement)

        item = WarehouseItem(code='REP-9001', name='RODAMIENTO 6308 2RS',
                             stock=1, unit='pza', family='RODAMIENTOS',
                             lead_time=30, min_stock=1)
        db.session.add(item)
        db.session.flush()

        activo = RotativeAsset(
            code='MOT-TEST-2', name='MOTOR ENFRIADOR 2', status='Instalado',
            area_id=ids['area_origen'], line_id=ids['linea_origen'],
            equipment_id=ids['equipo'])
        db.session.add(activo)
        db.session.flush()

        db.session.add_all([
            RotativeAssetBOM(asset_id=activo.id, warehouse_item_id=item.id,
                             quantity=2, category='MECANICO'),
            RotativeAssetBOM(asset_id=activo.id, free_text='RETEN 45x62x8',
                             quantity=1, category='MECANICO'),
            RotativeAssetSpec(asset_id=activo.id, key_name='Rodamiento lado libre',
                              value_text='6206-2RS'),
            WarehouseMovement(item_id=item.id, quantity=-3, movement_type='OUT',
                              date='2026-07-01 10:00:00', reason='consumo OT'),
        ])
        db.session.commit()

    r = auth_admin.get('/api/warehouse/export-bom')
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    assert 'spreadsheetml' in r.headers['Content-Type']

    import io
    import pandas as pd
    libro = pd.ExcelFile(io.BytesIO(r.data))
    assert 'Consolidado' in libro.sheet_names
    assert 'Detalle por equipo' in libro.sheet_names
    assert 'Por catalogar' in libro.sheet_names
    assert 'Repuestos en fichas tecnicas' in libro.sheet_names
    assert 'Consumo de almacen' in libro.sheet_names

    consolidado = libro.parse('Consolidado')
    fila = consolidado[consolidado['Codigo'] == 'REP-9001'].iloc[0]
    assert fila['Cantidad necesaria (todos los equipos)'] == 2
    assert fila['Faltante'] == 1  # necesita 2, hay 1

    detalle = libro.parse('Detalle por equipo')
    assert 'ENFRIADOR A4' in set(detalle['Equipo'])

    catalogar = libro.parse('Por catalogar')
    assert 'RETEN 45x62x8' in set(catalogar['Repuesto'])

    fichas = libro.parse('Repuestos en fichas tecnicas')
    assert '6206-2RS' in set(fichas['Valor (repuesto)'])


def test_export_bom_filtra_por_area(auth_admin):
    ids = _crear_estructura(auth_admin, 'A5')
    r = auth_admin.get(f"/api/warehouse/export-bom?area_id={ids['area_destino']}")
    assert r.status_code == 200
