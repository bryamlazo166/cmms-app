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
    # El indicador GLOBAL de planta abre cada lamina
    assert 'planta' in d and d['planta']['serie']
    for campo in ('disponibilidad', 'mtbf', 'mttr', 'confiabilidad'):
        assert campo in d['planta']['actual'], f'falta {campo} en planta'
    # Y el diagnostico mensual sigue vivo, con sus toneladas
    r2 = auth_admin.get(f"/api/diagnostico/data?month={hoy.strftime('%Y-%m')}")
    assert r2.status_code == 200 and 'produccion' in r2.json


def test_presentacion_semanal_acumula_y_cuadra_con_el_mes(auth_admin):
    """El informe se presenta cada semana: al cerrar la semana 3 se muestran
    S1, S2 y S3, cada una con su resultado y la linea del acumulado del mes.

    La regla que sostiene todo el modulo es que las semanas PARTICIONEN el
    mes: si un aviso cae en una semana no puede caer tambien en otra, y la
    suma de las cuatro (o cinco) tiene que dar exactamente el mes. Por eso
    se usan bloques de 7 dias desde el dia 1 y no semanas ISO, que se
    reparten entre dos meses.
    """
    mes = '2026-07'
    sem = auth_admin.get(f'/api/presentacion/data?month={mes}&vista=semana').json
    assert 'error' not in sem
    assert sem['meta']['vista'] == 'semana'
    periodos = sem['meta']['periodos']
    assert [p['label'] for p in periodos] == ['S1', 'S2', 'S3', 'S4', 'S5']
    # Julio tiene 31 dias: los bloques los cubren sin huecos ni solapes
    assert periodos[0]['desde'] == '2026-07-01'
    assert periodos[-1]['hasta'] == '2026-07-31'
    assert sum(p['dias'] for p in periodos) == 31
    for a, b in zip(periodos, periodos[1:]):
        assert a['hasta'] < b['desde'], 'las semanas se solapan'

    # Truncar a la semana 3: se ven S1, S2 y S3 y nada mas
    s3 = auth_admin.get(f'/api/presentacion/data?month={mes}&vista=semana&semana=3').json
    assert [p['label'] for p in s3['meta']['periodos']] == ['S1', 'S2', 'S3']
    assert len(s3['planta']['serie']) == 3
    # El acumulado va del dia 1 al cierre de cada semana
    acum = s3['planta']['acumulado']
    assert len(acum) == 3
    assert acum[0]['desde'] == acum[-1]['desde'] == '2026-07-01'
    assert acum[-1]['hasta'] == s3['meta']['periodos'][-1]['hasta']

    # Las semanas suman el mes, falla por falla y hora por hora
    mensual = auth_admin.get(f'/api/presentacion/data?month={mes}&vista=mes&meses=1').json
    fallas_mes = mensual['planta']['actual']['fallas']
    horas_mes = mensual['planta']['actual']['horas_paro']
    assert sum(s['fallas'] for s in sem['planta']['serie']) == fallas_mes
    assert abs(sum(s['horas_paro'] for s in sem['planta']['serie']) - horas_mes) < 0.05
    # Y el acumulado de la ultima semana ES el mes
    assert sem['planta']['acumulado'][-1]['fallas'] == fallas_mes

    # La disponibilidad requerida se prorratea: el porcentaje no cambia
    # (meta y capacidad escalan juntas) pero el presupuesto de horas si.
    req_mes = {r['area']: r for r in mensual['requerida']}
    for r in sem['requerida']:
        if r['area'] in req_mes:
            assert abs(r['requerida_pct'] - req_mes[r['area']]['requerida_pct']) < 0.2
            assert r['horas_periodo'] < req_mes[r['area']]['horas_periodo']

    # Sigue sin hablar de toneladas
    crudo = json.dumps(sem, ensure_ascii=False).replace('LANZAHARINA', '').lower()
    for prohibido in ('tonelada', 'sacos', 'monthly_target'):
        assert prohibido not in crudo


def test_cumplimiento_preventivo_incluye_lubricacion(auth_admin, app):
    """El programa preventivo no son solo las OTs.

    La lubricacion, las rutas de inspeccion y el monitoreo de condicion son
    mantenimiento preventivo y viven en sus propias tablas, sin pasar por
    WorkOrder. Contando solo OTs, julio 2026 mostraba 33 actividades cuando
    en realidad se habian hecho 396 lubricaciones: el indicador declaraba
    100 % de cumplimiento sobre el 8 % del trabajo.
    """
    from models import LubricationExecution, LubricationPoint, db

    with app.app_context():
        eq_id = None
        p = LubricationPoint(name='Punto de prueba', frequency_days=10,
                             equipment_id=eq_id, is_active=True,
                             quantity_unit='L')
        db.session.add(p)
        db.session.flush()
        # 3 servicios en la semana 1 de julio
        for dia in ('2026-07-02', '2026-07-04', '2026-07-06'):
            db.session.add(LubricationExecution(point_id=p.id, execution_date=dia,
                                                action_type='SERVICIO'))
        db.session.commit()

    d = auth_admin.get('/api/presentacion/data?month=2026-07&vista=mes&meses=1').json
    prev = d['cumplimiento']['preventivo'][-1]
    fuentes = {f['codigo']: f for f in prev['fuentes']}
    assert 'LUB' in fuentes, 'la lubricacion no entra al programa preventivo'
    lub = fuentes['LUB']
    assert lub['ejecutadas'] == 3
    # Plan teorico: 31 dias / 10 de frecuencia = 3,1 -> 3
    assert lub['programadas'] == 3
    assert lub['puntos'] == 1

    # El total suma todas las fuentes, y el indicador de solo OTs se conserva
    assert prev['programadas'] == sum(f['programadas'] for f in prev['fuentes'])
    assert prev['ejecutadas'] == sum(f['ejecutadas'] for f in prev['fuentes'])
    assert prev['solo_ot']['ejecutadas'] == fuentes['OT']['ejecutadas']

    # En vista semanal el plan se prorratea y las ejecuciones caen en su semana
    s = auth_admin.get('/api/presentacion/data?month=2026-07&vista=semana').json
    semanas = s['cumplimiento']['preventivo']
    lub_sem = [next(f for f in c['fuentes'] if f['codigo'] == 'LUB') for c in semanas]
    assert lub_sem[0]['ejecutadas'] == 3, 'las 3 lubricaciones son de la semana 1'
    assert sum(x['ejecutadas'] for x in lub_sem) == 3
    # 7 dias / 10 = 0,7 -> 1 servicio esperado por semana completa
    assert lub_sem[0]['programadas'] == 1


def test_programa_en_implementacion_no_baja_el_cumplimiento(auth_admin, app):
    """Que un programa este cargado no significa que este en vigor.

    Las rutas de inspeccion pueden tener sus rutas creadas y alguna ejecucion
    de prueba mientras se implantan; cobrarles el plan teorico hunde el
    cumplimiento con trabajo que todavia no se le exige a nadie. Y no hay dato
    que distinga «implementando» de «no se hizo» —una ejecucion suelta no lo
    dice—, asi que la jefatura lo declara y queda a la vista en la lamina.
    """
    from models import AppSetting, InspectionExecution, InspectionRoute, db

    with app.app_context():
        r = InspectionRoute(name='Ruta en implantacion', frequency_days=7,
                            is_active=True)
        db.session.add(r)
        db.session.flush()
        db.session.add(InspectionExecution(route_id=r.id,
                                           execution_date='2026-07-03'))
        db.session.commit()

    def fuentes(d):
        return {f['codigo']: f for f in d['cumplimiento']['preventivo'][-1]['fuentes']}

    # Por defecto solo OT y lubricacion estan en vigor
    d = auth_admin.get('/api/presentacion/data?month=2026-07&vista=mes&meses=1').json
    fs = fuentes(d)
    assert fs['OT']['activa'] is True
    assert fs['INS']['activa'] is False
    assert fs['INS']['programadas'] == 0 and fs['INS']['ejecutadas'] == 0
    # Pero su plan se sigue viendo: se lista, no se esconde
    assert fs['INS']['plan_teorico'] > 0
    total_sin = d['cumplimiento']['preventivo'][-1]
    assert total_sin['programadas'] == sum(f['programadas'] for f in fs.values() if f['activa'])
    assert {x['codigo'] for x in d['meta']['fuentes_disponibles']} >= {'OT', 'LUB', 'INS'}

    # Al declararlas en vigor, entran y el cumplimiento baja
    r = auth_admin.post('/api/presentacion/fuentes',
                        json={'fuentes': ['LUB', 'INS']})
    assert r.status_code == 200 and r.json['ok']
    assert r.json['fuentes'] == ['OT', 'LUB', 'INS']
    d2 = auth_admin.get('/api/presentacion/data?month=2026-07&vista=mes&meses=1').json
    fs2 = fuentes(d2)
    assert fs2['INS']['activa'] is True
    assert fs2['INS']['programadas'] > 0
    total_con = d2['cumplimiento']['preventivo'][-1]
    assert total_con['programadas'] > total_sin['programadas']
    assert total_con['pct'] <= total_sin['pct']

    # Las OTs siempre entran, aunque no se las mencione
    auth_admin.post('/api/presentacion/fuentes', json={'fuentes': []})
    d3 = auth_admin.get('/api/presentacion/data?month=2026-07&vista=mes&meses=1').json
    assert fuentes(d3)['OT']['activa'] is True
    assert fuentes(d3)['LUB']['activa'] is False

    # Basura en la peticion no rompe la configuracion
    malo = auth_admin.post('/api/presentacion/fuentes', json={'fuentes': 'LUB'})
    assert malo.status_code == 400
    ok = auth_admin.post('/api/presentacion/fuentes',
                         json={'fuentes': ['LUB', 'NO_EXISTE']})
    assert ok.json['fuentes'] == ['OT', 'LUB']
    with app.app_context():
        assert db.session.get(AppSetting, 'preventivo_fuentes').value == 'OT,LUB'


def test_produccion_usa_la_capacidad_real_y_no_el_rendimiento_manual(auth_admin):
    """Produccion vs Mantenimiento calculaba la disponibilidad requerida con
    el rendimiento y las horas cargados a mano en la meta.

    Como esa cifra es la misma para las tres areas, las tres pedian 98,8 %,
    mientras la presentacion —que divide por la capacidad instalada de cada
    etapa— pedia 86,5 / 84,9 / 70,8 %. Dos pantallas y dos respuestas para el
    mismo mes. Ahora ambas dividen por la capacidad real de los equipos en
    servicio, asi que el numero tiene que ser el MISMO.
    """
    p = auth_admin.get('/api/production/metrics?period=2026-07').json
    if 'error' in p or not p.get('areas'):
        return
    r = auth_admin.get('/api/presentacion/data'
                       '?month=2026-07&vista=mes&meses=1&modo=inherente').json
    req = {x['area']: x for x in r['requerida']}

    for a in p['areas']:
        if not a['capacidad_automatica']:
            continue
        assert a['area_capacity_tm_day'] > 0
        # La capacidad del area es la misma en los dos modulos
        q = req.get(a['area_name'])
        if not q:
            continue
        assert abs(a['area_capacity_tm_day'] - q['capacidad_dia']) < 0.05
        # Y por tanto la disponibilidad requerida tambien
        assert abs(a['required_availability'] - q['requerida_pct']) < 0.2, (
            f"{a['area_name']}: produccion pide {a['required_availability']} % "
            f"y la presentacion {q['requerida_pct']} %")
        # tons_per_hour sale de la capacidad, no del campo manual
        assert abs(a['tons_per_hour'] - a['area_capacity_tm_day'] / 24) < 0.01

    # La disponibilidad que muestra produccion es la OPERATIVA (la castiga
    # todo paro, que es lo que produccion realmente tuvo), no la inherente.
    op = auth_admin.get('/api/presentacion/data'
                        '?month=2026-07&vista=mes&meses=1&modo=operativa').json
    disp_op = {a['area']: a['actual']['disponibilidad'] for a in op['areas']}
    for a in p['areas']:
        if a['area_name'] in disp_op and a['capacidad_automatica']:
            assert abs(a['availability_actual'] - disp_op[a['area_name']]) < 1.5


def test_metodologia_explica_las_tres_etapas(auth_admin):
    """Cocción genera la harina y secado y molienda la procesan: son dos
    cuentas distintas, y el modulo tiene que mostrar las dos con ejemplos.
    Aplicar el rendimiento tambien a secadores y molinos subestimaba a la
    mitad la capacidad de las dos ultimas etapas."""
    d = auth_admin.get('/api/metodologia/data?month=2026-07').json
    if 'error' in d:
        return
    etapas = {e['etapa']: e for e in d['etapas']}
    assert etapas, 'no hay etapas de proceso'

    for et in d['etapas']:
        assert et['filas'], f"la etapa {et['etapa']} no lista sus equipos"
        # El total de la etapa es la suma de lo que aportan sus equipos
        assert abs(et['tm_dia'] - sum(f['tm_harina'] for f in et['filas'])) < 0.05
        for f in et['filas']:
            if not f['en_servicio']:
                assert f['tm_harina'] == 0.0, 'un equipo fuera de servicio no aporta'
                continue
            if et['aplica_rendimiento']:
                # Cocción: por lotes y con rendimiento aplicado una vez
                assert f['por_lotes'], 'la coccion se mide por llenadas'
                assert f['kg'] and f['llenadas']
                esperado = f['capacidad_cruda'] * d['meta']['rendimiento_pct'] / 100
                assert abs(f['tm_harina'] - esperado) < 0.05
            else:
                # Secado y molienda: la capacidad ya está en harina
                assert not f['por_lotes']
                assert abs(f['tm_harina'] - f['capacidad_cruda']) < 0.05, (
                    'a un secador o molino no se le vuelve a aplicar el rendimiento')

    # La planta es la etapa más corta, no la suma
    conc = [e['tm_dia'] for e in d['etapas'] if e['tm_dia'] > 0]
    if conc:
        assert abs(d['planta_tm_dia'] - min(conc)) < 0.05
        assert d['cuello'] in etapas


def test_presentacion_detalle_muestra_las_ordenes(auth_admin):
    """En pantalla van los indicadores globales; el detalle sale al hacer
    click. Es lo que se abre cuando en la reunion preguntan por que bajo un
    area, asi que tiene que traer los equipos y las OTs de ese periodo."""
    r = auth_admin.get('/api/presentacion/detalle'
                       '?area_id=0&desde=2026-07-01&hasta=2026-07-31&modo=inherente')
    assert r.status_code == 200
    d = r.json
    assert 'error' not in d
    assert d['dias'] == 31 and d['tep'] == 744
    for campo in ('disponibilidad', 'mtbf', 'mttr', 'confiabilidad', 'fallas'):
        assert campo in d['resumen'], f'falta {campo}'
    assert isinstance(d['equipos'], list) and isinstance(d['ots'], list)
    for e in d['equipos']:
        assert 0 <= e['disponibilidad'] <= 100
    for o in d['ots']:
        assert o['code'] and 'planificado' in o

    # El resumen del detalle es el MISMO numero que muestra la lamina: si
    # divergen, en la reunion el drill-down contradice al grafico.
    data = auth_admin.get('/api/presentacion/data?month=2026-07&vista=mes&meses=1').json
    assert abs(d['resumen']['disponibilidad']
               - data['planta']['actual']['disponibilidad']) < 0.01

    # Sin rango de fechas responde error, no una pantalla vacia
    malo = auth_admin.get('/api/presentacion/detalle?area_id=0')
    assert malo.status_code == 400 and 'error' in malo.json


def test_metodologia_reconstruye_el_numero_de_la_presentacion(auth_admin):
    """El modulo de metodologia existe para sentarse con la jefatura y cuadrar
    el numero a mano. Si el area que muestra la presentacion no se puede
    reconstruir equipo por equipo aqui, el indicador no sirve para presentarse
    — asi que el vinculo se prueba, no se confia.
    """
    r = auth_admin.get('/api/metodologia/data?month=2026-07&modo=inherente')
    assert r.status_code == 200
    d = r.json
    if 'error' in d:                      # base sin equipos de proceso cargados
        return

    m, e, p = d['meta'], d['ejemplo'], d['ponderacion']
    assert m['tep'] == m['dias'] * 24
    assert m['horizonte_h'] == 168

    # La base de tiempo tiene que cerrar: T = uptime + Pp + Pn
    assert abs(e['tep'] - (e['uptime'] + e['paro_planificado']
                           + e['paro_averia'])) < 0.02
    assert abs(e['base_inherente'] - (e['tep'] - e['paro_planificado'])) < 0.02
    # Y las dos disponibilidades tienen que salir de esa misma base
    assert abs(e['disp_operativa'] - e['uptime'] / e['tep'] * 100) < 0.02
    if e['base_inherente'] > 0:
        assert abs(e['disp_inherente']
                   - e['uptime'] / e['base_inherente'] * 100) < 0.02
    if e['fallas']:
        assert abs(e['mttr'] - e['paro_del_modo'] / e['fallas']) < 0.02
    else:
        assert e['confiabilidad'] == 100.0

    # La ponderacion es Σ(disp × cap) / Σcap, sumando las mismas filas
    assert abs(p['numerador']
               - sum(f['aporte'] for f in p['filas'] if f['pesa'])) < 0.05
    assert abs(p['denominador']
               - sum(f['capacidad'] for f in p['filas'] if f['pesa'])) < 0.05
    if p['denominador']:
        assert abs(p['resultado']
                   - p['numerador'] / p['denominador']) < 0.02

    # Y el resultado es EL MISMO que presenta la lamina de esa area
    pres = auth_admin.get('/api/presentacion/data'
                          '?month=2026-07&vista=mes&meses=1&modo=inherente').json
    lamina = next((a for a in pres['areas'] if a['area'] == p['area']), None)
    assert lamina is not None, f"la presentacion no tiene el area {p['area']}"
    assert abs(lamina['actual']['disponibilidad'] - p['resultado']) < 0.02, (
        'la metodologia no reconstruye el numero de la presentacion')


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
