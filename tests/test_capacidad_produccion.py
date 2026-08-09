"""Capacidad real de planta y toneladas no producidas.

Fija la metodologia que reemplazo al calculo por area: las TM que se dejan de
producir salen de la capacidad del equipo que paro, no del rendimiento de toda
la planta. Con el metodo anterior la parada de un solo digestor se valoraba
como si se hubiera detenido el area completa, y julio llegaba a reportar mas
toneladas perdidas de las que la planta produce en un mes.
"""
import datetime as dt
import json

from utils.kpi_helpers import (
    DEFAULT_BATCHES_PER_DAY, DEFAULT_FILL_PCT,
    eq_capacity_basis, eq_capacity_tm_day, eq_harina_tm_day, eq_input_tph,
    eq_is_batch, eq_produces, plant_capacity_tm_day, plant_harina_tm_day,
    plant_stages, plant_yield_factor, suggest_capacities,
    suggest_production_units,
)


class _Eq:
    """Equipo minimo para probar los helpers sin tocar la BD."""
    def __init__(self, **kw):
        self.id = kw.get('id', 1)
        self.tag = kw.get('tag')
        self.name = kw.get('name', '')
        self.line_id = kw.get('line_id', 1)
        self.batch_capacity_kg = kw.get('batch_capacity_kg')
        self.fill_pct = kw.get('fill_pct')
        self.batches_per_day = kw.get('batches_per_day')
        self.capacity_tm_day = kw.get('capacity_tm_day')
        self.capacity_tm = kw.get('capacity_tm')
        self.is_production_unit = kw.get('is_production_unit', False)
        self.shift_hours_per_day = kw.get('shift_hours_per_day', 24.0)
        self.work_days_per_week = kw.get('work_days_per_week', 7)
        self.yield_factor = kw.get('yield_factor', 1.0)
        self.include_in_kpi = kw.get('include_in_kpi', True)
        self.in_service = kw.get('in_service', True)


class _Line:
    def __init__(self, id, area_id):
        self.id, self.area_id = id, area_id


def _digestores():
    """La planta real: 9 digestores al 75% con 4 llenadas al dia. El #4 esta
    en overhaul, asi que no aporta capacidad."""
    kg = {'D1': 8000, 'D2': 8000, 'D3': 8000, 'D4': 6000, 'D5': 7000,
          'D6': 12000, 'D7': 12000, 'D8': 12000, 'D9': 12000}
    return [_Eq(id=i, tag=t, name=f'DIGESTOR #{t[1:]}', line_id=i,
                batch_capacity_kg=k, fill_pct=75, batches_per_day=4,
                yield_factor=0.7, in_service=(t != 'D4'))
            for i, (t, k) in enumerate(kg.items(), start=1)]


def test_capacidad_de_una_llenada():
    """8000 kg al 75% x 4 llenadas = 24 TM/dia = 1 TM/h."""
    d1 = _Eq(tag='D1', batch_capacity_kg=8000, fill_pct=75, batches_per_day=4)
    assert eq_is_batch(d1)
    assert eq_capacity_tm_day(d1) == 24.0
    assert eq_input_tph(d1) == 1.0

    d6 = _Eq(tag='D6', batch_capacity_kg=12000, fill_pct=75, batches_per_day=4)
    assert eq_capacity_tm_day(d6) == 36.0
    assert eq_input_tph(d6) == 1.5

    d5 = _Eq(tag='D5', batch_capacity_kg=7000, fill_pct=75, batches_per_day=4)
    assert eq_capacity_tm_day(d5) == 21.0


def test_regimen_por_defecto_de_planta():
    """Sin capturar el regimen se asume 75% de llenado y 4 llenadas al dia."""
    assert DEFAULT_FILL_PCT == 75.0 and DEFAULT_BATCHES_PER_DAY == 4.0
    d = _Eq(tag='D2', batch_capacity_kg=8000)
    assert eq_capacity_tm_day(d) == 24.0
    # El tag conocido tambien sirve de respaldo si aun no se capturo el kg
    assert eq_capacity_tm_day(_Eq(tag='D9')) == 36.0


def test_capacidad_de_planta_excluye_lo_que_esta_fuera_de_servicio():
    """D1-D3 (24) + D5 (21) + D6-D9 (36) = 237 TM/dia. El D4 esta en overhaul."""
    eqs = _digestores()
    assert plant_capacity_tm_day(eqs) == 237.0
    assert round(plant_yield_factor(eqs), 3) == 0.7

    # Al volver el D4 a servicio la capacidad sube en sus 18 TM/dia
    for e in eqs:
        if e.tag == 'D4':
            e.in_service = True
    assert plant_capacity_tm_day(eqs) == 255.0


def test_parada_de_un_digestor_no_vale_toda_la_planta():
    """Regresion del bug: 24 h del digestor #6 cuestan 36 TM de materia
    prima, no las 237 TM/dia de la planta entera."""
    eqs = _digestores()
    d6 = next(e for e in eqs if e.tag == 'D6')
    perdida_mp = 24 * eq_input_tph(d6)
    assert perdida_mp == 36.0
    assert perdida_mp < plant_capacity_tm_day(eqs)


def test_solo_los_equipos_que_transforman_restan_toneladas():
    """Los unicos que producen harina son los digestores, los secadores y los
    molinos. Un transportador que para no deja de producir por si mismo: si
    contara, se valoraria dos veces el mismo flujo."""
    th = _Eq(id=101, tag='TH1', name='TH1', line_id=1, capacity_tm_day=24)
    mol = _Eq(id=102, tag='MOL1', name='MOLINO', line_id=20,
              capacity_tm_day=94.8, is_production_unit=True)
    d1 = _Eq(id=1, tag='D1', batch_capacity_kg=8000, fill_pct=75, batches_per_day=4)

    # El transportador tiene capacidad guardada pero NO cuenta
    assert not eq_produces(th)
    assert eq_capacity_tm_day(th) == 0.0
    assert eq_input_tph(th) == 0.0
    # El molino si, y el digestor lo es por trabajar por lotes
    assert eq_produces(mol) and eq_capacity_tm_day(mol) == 94.8
    assert eq_produces(d1) and eq_capacity_tm_day(d1) == 24.0
    # Los auxiliares tampoco suman a la capacidad de planta
    assert plant_capacity_tm_day([d1, th]) == 24.0


def test_sugerencia_marca_secadores_y_molinos():
    """La sugerencia detecta que transforman producto y les da media planta
    (son 2 de cada, en paralelo). El resto queda auxiliar."""
    eqs = _digestores()
    lines = [_Line(i, 1) for i in range(1, 10)] + [_Line(20, 4), _Line(21, 4),
                                                   [_Line(22, 6), _Line(23, 6)][0], _Line(23, 6)]
    th1 = _Eq(id=101, tag='TH1', name='TH1', line_id=1)
    mol1 = _Eq(id=102, tag='MOL1', name='MOLINO', line_id=20)
    mol2 = _Eq(id=103, tag='MOL2', name='MOLINO', line_id=21)
    sec1 = _Eq(id=104, tag='SEC1', name='SECADOR', line_id=22)
    sec2 = _Eq(id=105, tag='SEC2', name='SECADOR', line_id=23)
    eqs += [th1, mol1, mol2, sec1, sec2]

    marcados = suggest_production_units(eqs)
    assert marcados == {102, 103, 104, 105}     # molinos y secadores, no el TH
    for e in eqs:
        if e.id in marcados:
            e.is_production_unit = True

    sug = suggest_capacities(eqs, lines)
    assert 101 not in sug                        # el auxiliar no recibe capacidad
    # La capacidad de secadores y molinos va en HARINA, porque procesan lo que
    # salio de coccion: 237 TM/dia de materia prima x 70% = 165.9, mitad c/u.
    assert sug[102] == sug[103] == 82.95         # media molienda cada molino
    assert sug[104] == sug[105] == 82.95         # medio secado cada secador


def _planta_completa():
    """Los digestores generan la harina; 2 secadores la secan y 2 molinos la
    muelen. Cada etapa puede con toda la harina de coccion."""
    eqs = _digestores()
    harina_coccion = sum(e.batch_capacity_kg * 0.75 * 4 / 1000 * 0.7
                         for e in eqs if e.tag != 'D4')          # 165.9
    sec = [_Eq(id=30 + i, tag=f'SEC{i}', name='SECADOR', line_id=30 + i,
               capacity_tm_day=harina_coccion / 2, is_production_unit=True)
           for i in (1, 2)]
    mol = [_Eq(id=40 + i, tag=f'MOL{i}', name='MOLINO', line_id=40 + i,
               capacity_tm_day=harina_coccion / 2, is_production_unit=True)
           for i in (1, 2)]
    return eqs + sec + mol, harina_coccion


def test_los_que_procesan_no_vuelven_a_aplicar_el_rendimiento():
    """Un digestor GENERA harina: a su materia prima se le aplica el
    rendimiento. Un molino PROCESA la harina que ya salio, asi que su
    capacidad ya esta en harina y no se multiplica otra vez."""
    eqs, harina_coccion = _planta_completa()
    rend = plant_yield_factor(eqs)

    d6 = next(e for e in eqs if e.tag == 'D6')
    assert eq_capacity_basis(d6) == 'MP'
    assert eq_capacity_tm_day(d6) == 36.0                    # materia prima
    assert eq_harina_tm_day(d6, rend) == 36.0 * 0.7          # con rendimiento

    mol = next(e for e in eqs if e.tag == 'MOL1')
    assert eq_capacity_basis(mol) == 'PRODUCTO'
    # Su capacidad YA es harina: no se le vuelve a aplicar el 70%
    assert eq_harina_tm_day(mol, rend) == eq_capacity_tm_day(mol)


def test_la_planta_produce_lo_que_permite_la_etapa_mas_limitada():
    """Coccion, secado y molienda van en SERIE: la planta saca lo que permita
    la etapa mas corta, no la suma de las tres."""
    eqs, harina_coccion = _planta_completa()
    etapas = plant_stages(eqs)
    assert set(etapas) == {'COCCION', 'SECADOR', 'MOLINO'}
    for st in etapas.values():
        assert round(st['tm_dia'], 2) == round(harina_coccion, 2)
    assert round(plant_harina_tm_day(eqs), 2) == round(harina_coccion, 2)


def test_un_molino_fuera_de_servicio_deja_la_planta_a_la_mitad():
    """Cuando falla el molino #1 se desactiva y solo trabaja el #2: la
    molienda queda a la mitad y con ella toda la planta, porque las etapas
    estan en serie."""
    eqs, harina_coccion = _planta_completa()
    assert round(plant_harina_tm_day(eqs), 2) == round(harina_coccion, 2)

    mol1 = next(e for e in eqs if e.tag == 'MOL1')
    mol1.in_service = False
    etapas = plant_stages(eqs)
    assert etapas['MOLINO']['operativos'] == 1
    assert round(etapas['MOLINO']['tm_dia'], 2) == round(harina_coccion / 2, 2)
    # La coccion sigue igual, pero la planta baja a la mitad
    assert round(etapas['COCCION']['tm_dia'], 2) == round(harina_coccion, 2)
    assert round(plant_harina_tm_day(eqs), 2) == round(harina_coccion / 2, 2)

    # Y lo mismo con un secador
    mol1.in_service = True
    next(e for e in eqs if e.tag == 'SEC2').in_service = False
    assert round(plant_harina_tm_day(eqs), 2) == round(harina_coccion / 2, 2)


def test_diagnostico_no_puede_perder_mas_que_la_capacidad(auth_admin, app):
    """El total del periodo tiene techo en la capacidad instalada: aunque las
    horas de parada registradas sean absurdas, no se puede dejar de producir
    mas de lo que la planta podia procesar."""
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment
        area = Area(name='AREA TECHO TEST')
        db.session.add(area); db.session.flush()
        line = Line(name='LINEA TECHO TEST', area_id=area.id)
        db.session.add(line); db.session.flush()
        eq = Equipment(name='DIGESTOR TECHO', tag='D-TECHO', line_id=line.id,
                       batch_capacity_kg=8000, fill_pct=75, batches_per_day=4,
                       yield_factor=1.0)
        db.session.add(eq); db.session.flush()
        eq_id = eq.id
        db.session.commit()

    hoy = dt.date.today()
    try:
        # Parada imposible: 5000 h en un mes que tiene menos de 750
        auth_admin.post('/api/work-orders', data=json.dumps({
            'description': 'Parada absurda', 'maintenance_type': 'Correctivo',
            'status': 'Cerrada', 'equipment_id': eq_id,
            'real_start_date': hoy.replace(day=1).isoformat(),
            'real_end_date': hoy.isoformat(),
            'caused_downtime': True, 'downtime_hours': 5000.0,
        }), content_type='application/json')

        r = auth_admin.get(f"/api/diagnostico/data?month={hoy.strftime('%Y-%m')}")
        prod = r.json['produccion']
        assert prod['disponible'] is True
        assert prod['tons_lost_mes'] <= prod['capacidad_periodo_tons']
        # Y la disponibilidad queda acotada a [0, 100], nunca negativa
        disp = r.json['kpis_mes']['disponibilidad_pct']
        assert 0 <= disp <= 100
        # La parada larga se reporta para que se corrija en vez de esconderla
        assert any(x['code'] for x in prod['paradas_largas'])
    finally:
        # La BD de tests es compartida: este equipo cambia la capacidad de
        # planta, asi que se retira para no contaminar los demas tests.
        with app.app_context():
            from database import db
            from models import Equipment, WorkOrder
            for ot in WorkOrder.query.filter_by(equipment_id=eq_id).all():
                db.session.delete(ot)
            eq = Equipment.query.get(eq_id)
            if eq:
                db.session.delete(eq)
            db.session.commit()


def test_diagnostico_acepta_rango_de_fechas(auth_admin):
    """El analisis no esta atado al mes: se puede pedir cualquier ventana."""
    hoy = dt.date.today()
    desde = (hoy - dt.timedelta(days=20)).isoformat()
    r = auth_admin.get(f'/api/diagnostico/data?desde={desde}&hasta={hoy.isoformat()}')
    assert r.status_code == 200
    meta = r.json['meta']
    assert meta['modo'] == 'rango'
    assert meta['desde'] == desde and meta['hasta'] == hoy.isoformat()
    assert meta['dias'] == 21
    # El periodo de comparacion es la ventana equivalente anterior
    assert r.json['kpis_prev']['dias_mes'] == 21
    # Y la portada resume el veredicto del rango
    assert r.json['portada']['veredicto']


def test_area_en_paralelo_no_se_queda_sin_produccion_teorica(auth_admin, app):
    """Un area con varios equipos en PARALELO no puede quedar en cero.

    Regresion: Produccion vs Mantenimiento restaba la SUMA de horas de parada
    de todos los equipos del area como si fuera una sola maquina en serie. En
    COCCION, con 9 digestores, esas horas superaban las del mes, el uptime
    daba 0 y el area aparecia sin produccion teorica en TODOS los graficos.
    """
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment, ProductionGoal, WorkOrder
        area = Area(name='AREA PARALELO TEST')
        db.session.add(area); db.session.flush()
        line = Line(name='LINEA PARALELO TEST', area_id=area.id)
        db.session.add(line); db.session.flush()
        # 4 equipos gemelos de 24 TM/dia: en paralelo, 96 TM/dia de area
        ids = []
        for i in range(4):
            e = Equipment(name=f'REACTOR {i}', tag=f'RX{i}', line_id=line.id,
                          capacity_tm_day=24.0, is_production_unit=True)
            db.session.add(e); db.session.flush()
            ids.append(e.id)
        mes = dt.date.today().strftime('%Y-%m')
        db.session.add(ProductionGoal(goal_period=mes, area_id=area.id,
                                      monthly_avg_yield_tons=720.0,
                                      monthly_target_tons=720.0,
                                      operating_hours_month=720.0))
        db.session.commit()
        area_id = area.id

    try:
        # Cada equipo para un tercio de las horas transcurridas: por separado
        # es perfectamente posible, pero SUMADAS superan las horas del periodo
        # — que es justo lo que pasa en COCCION con sus 9 digestores.
        hoy = dt.date.today()
        horas_periodo = hoy.day * 24
        paro_por_equipo = round(horas_periodo / 3, 1)
        ini = hoy.replace(day=1).isoformat()
        for eid in ids:
            auth_admin.post('/api/work-orders', data=json.dumps({
                'description': 'Parada paralela', 'maintenance_type': 'Correctivo',
                'status': 'Cerrada', 'equipment_id': eid,
                'real_start_date': ini, 'real_end_date': hoy.isoformat(),
                'caused_downtime': True, 'downtime_hours': paro_por_equipo,
            }), content_type='application/json')
        assert paro_por_equipo * 4 > horas_periodo, 'el escenario debe superar las horas del mes'

        r = auth_admin.get(f'/api/production/metrics?period={hoy.strftime("%Y-%m")}')
        assert r.status_code == 200
        a = next(x for x in r.json['areas'] if x['area_name'] == 'AREA PARALELO TEST')

        # Lo que fallaba: teorico 0 y disponibilidad 0 por sumar en serie
        assert a['tons_produced_theoretical'] > 0, 'el area quedo sin produccion teorica'
        assert 0 < a['availability_actual'] <= 100
        # Perdio un tercio de su capacidad: 4 equipos parados 1/3 del tiempo
        capacidad = 96.0 * hoy.day
        assert abs(a['availability_actual'] - 66.67) < 1.5
        assert a['tons_lost'] <= capacidad + 0.1
    finally:
        with app.app_context():
            from database import db
            from models import Equipment, WorkOrder
            for eid in ids:
                for ot in WorkOrder.query.filter_by(equipment_id=eid).all():
                    db.session.delete(ot)
                eq = Equipment.query.get(eid)
                if eq:
                    db.session.delete(eq)
            db.session.commit()


def test_narrativa_sobrevive_al_cambio_de_worker(auth_admin, app, monkeypatch):
    """El trabajo de la narrativa vive en la BD, no en memoria del proceso.

    Con gunicorn corriendo varios workers, el POST que crea el trabajo y el
    GET que consulta el resultado caen en procesos distintos: guardado en
    memoria, el que preguntaba nunca lo encontraba y el navegador se quedaba
    sondeando hasta rendirse con 'la IA tardo demasiado'.
    """
    import routes.diagnostico_routes as dr

    class _Resp:
        status_code = 200
        text = ''
        @staticmethod
        def json():
            return {'choices': [{'message': {'content': 'RESUMEN EJECUTIVO\nTodo bien.'}}]}

    monkeypatch.setattr(dr, 'DEEPSEEK_MODEL', 'test-model', raising=False)
    import requests
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp())
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test')

    hoy = dt.date.today()
    d = auth_admin.get(f"/api/diagnostico/data?month={hoy.strftime('%Y-%m')}").json
    r = auth_admin.post('/api/diagnostico/narrativa?forzar=1', data=json.dumps(d),
                        content_type='application/json')
    assert r.status_code == 200
    job_id = r.json['job_id']

    # El trabajo esta en la BD: cualquier worker lo encuentra
    with app.app_context():
        from models import NarrativeJob
        from database import db
        assert db.session.get(NarrativeJob, job_id) is not None

    # Y un cliente NUEVO (otra conexion) puede consultarlo
    otro = app.test_client()
    otro.post('/login', data={'username': 'admin', 'password': 'admin123'})
    st = otro.get(f'/api/diagnostico/narrativa/{job_id}')
    assert st.status_code == 200
    assert st.json['status'] in ('PENDIENTE', 'OK')

    # Un job_id inexistente sigue devolviendo JSON (no HTML), para que el
    # navegador pueda distinguir el error en vez de reintentar en silencio
    faltante = auth_admin.get('/api/diagnostico/narrativa/noexiste123')
    assert faltante.status_code == 404 and 'error' in faltante.json


def test_presentacion_mensual_no_habla_de_toneladas(auth_admin):
    """El modulo de Indicadores Mensuales corre en paralelo al Diagnostico y
    su regla es no mencionar toneladas: el unico dato de produccion que entra
    es la meta, y solo para despejar la disponibilidad requerida."""
    hoy = dt.date.today()
    r = auth_admin.get(f"/api/presentacion/data?month={hoy.strftime('%Y-%m')}&meses=4")
    assert r.status_code == 200
    d = r.json
    assert 'error' not in d

    crudo = json.dumps(d, ensure_ascii=False)
    # LANZAHARINA es un equipo, no una referencia a producto
    crudo = crudo.replace('LANZAHARINA', '')
    for prohibido in ('tons', 'tonelada', 'sacks', 'sacos', 'tm_dia',
                      'monthly_target', 'capacidad_periodo'):
        assert prohibido not in crudo.lower(), f'la presentacion expone {prohibido}'

    # Las 6 laminas del informe siguen ahi
    assert 'areas' in d and 'requerida' in d and 'cumplimiento' in d
    assert 'preventivo' in d['cumplimiento'] and 'correctivo' in d['cumplimiento']
    for a in d['areas']:
        for campo in ('disponibilidad', 'mtbf', 'mttr', 'confiabilidad', 'tep'):
            assert campo in a['actual'], f'falta {campo}'
    # Y el diagnostico mensual sigue vivo, con sus toneladas
    r2 = auth_admin.get(f"/api/diagnostico/data?month={hoy.strftime('%Y-%m')}")
    assert r2.status_code == 200 and 'produccion' in r2.json


def test_confiabilidad_sin_fallas_es_100(auth_admin, app):
    """Un equipo que no fallo en el periodo tiene 100% de confiabilidad.

    Antes se igualaba el MTBF a las horas del periodo y R(t) = e^(-T/T) daba
    siempre 36,79%: areas enteras sin una sola falla aparecian como poco
    confiables en la presentacion.
    """
    from routes.indicators_routes import _calc_indicators
    ind = _calc_indicators([], 744.0)
    assert ind['failure_count'] == 0
    assert ind['reliability'] == 100.0
    assert ind['availability'] == 100

    # Con una falla, R(t) se mide al horizonte estandar de 168 h
    ots = [{'id': 1, 'caused_downtime': True, 'downtime_hours': 24.0,
            'maintenance_type': 'Correctivo', 'equipment_id': 1}]
    ind2 = _calc_indicators(ots, 744.0, mode='operativa')
    assert ind2['failure_count'] == 1
    assert 0 < ind2['reliability'] < 100
    # MTTR = tiempo medio de reparacion = horas detenido / averias
    assert ind2['mttr'] == 24.0


def test_atajos_de_periodo(auth_admin):
    """El selector arranca en el ultimo mes con datos, no en el mes en curso
    (que suele tener dos dias cargados y no sirve para presentar)."""
    r = auth_admin.get('/api/diagnostico/periodos')
    assert r.status_code == 200
    p = r.json
    for k in ('mes_actual', 'ultimo_mes', 'ultimo_con_datos',
              'ultimos_30', 'ultimos_90', 'anio_actual'):
        assert k in p, f'falta el atajo {k}'
    assert p['ultimo_con_datos'] <= p['mes_actual']
    assert p['ultimos_30']['desde'] < p['ultimos_30']['hasta']
