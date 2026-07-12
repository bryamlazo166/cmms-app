"""Tests: corte semanal configurable, catalogo de modos de falla,
Pareto de fallas y seguimiento predictivo de activos rotativos."""
import json


def test_settings_default_week_start(auth_admin):
    r = auth_admin.get('/api/settings')
    assert r.status_code == 200
    assert int(r.json['week_start_day']) in range(7)


def test_settings_update_week_start_admin(auth_admin):
    # Viernes (4) -> el reporte semanal debe empezar en viernes
    r = auth_admin.put('/api/settings', data=json.dumps({'week_start_day': 4}),
                       content_type='application/json')
    assert r.status_code == 200
    assert r.json['changed']['week_start_day'] == '4'

    import datetime as dt
    r2 = auth_admin.get('/api/reports/weekly-plan?window=current_week')
    assert r2.status_code == 200
    start = dt.date.fromisoformat(r2.json['meta']['start_date'])
    end = dt.date.fromisoformat(r2.json['meta']['end_date'])
    assert start.weekday() == 4  # viernes
    assert (end - start).days == 6  # viernes a jueves

    # Restaurar default (lunes) para no afectar otros tests
    auth_admin.put('/api/settings', data=json.dumps({'week_start_day': 0}),
                   content_type='application/json')


def test_settings_update_rejected_for_viewer(auth_viewer):
    r = auth_viewer.put('/api/settings', data=json.dumps({'week_start_day': 4}),
                        content_type='application/json')
    assert r.status_code == 403


def test_weekly_plan_includes_smrp_kpis(auth_admin):
    r = auth_admin.get('/api/reports/weekly-plan?window=current_week')
    assert r.status_code == 200
    smrp = r.json.get('smrp')
    assert smrp is not None
    for key in ('schedule_compliance_pct', 'proactive_pct', 'reactive_pct',
                'backlog_ots', 'backlog_weeks', 'benchmark'):
        assert key in smrp


def test_failure_mode_suggestions_and_track(auth_admin):
    # Crear una OT con modo de falla y verificar que aparece en sugerencias
    auth_admin.post('/api/work-orders', data=json.dumps({
        'description': 'Falla de prueba', 'maintenance_type': 'Correctivo',
        'status': 'Abierta', 'failure_mode': 'DESGASTE DE PRUEBA XYZ',
    }), content_type='application/json')

    r = auth_admin.get('/api/failure-modes/suggestions')
    assert r.status_code == 200
    modes = [i['mode'] for i in r.json]
    assert 'DESGASTE DE PRUEBA XYZ' in modes

    # track: modo nuevo se agrega al catalogo como SIN_CLASIFICAR
    r2 = auth_admin.post('/api/failure-modes/track', data=json.dumps({
        'mode': 'modo nuevo de prueba'}), content_type='application/json')
    assert r2.status_code == 200
    assert r2.json['failure_mode'] == 'MODO NUEVO DE PRUEBA'
    assert r2.json['usage_count'] == 1

    # track repetido incrementa
    r3 = auth_admin.post('/api/failure-modes/track', data=json.dumps({
        'mode': 'MODO NUEVO DE PRUEBA'}), content_type='application/json')
    assert r3.json['usage_count'] == 2


def test_pareto_fallas(auth_admin):
    import datetime as dt
    today = dt.date.today().isoformat()
    # OTs correctivas cerradas hoy con modos conocidos
    for modo in ('ROTURA', 'ROTURA', 'FUGA'):
        auth_admin.post('/api/work-orders', data=json.dumps({
            'description': f'Pareto test {modo}', 'maintenance_type': 'Correctivo',
            'status': 'Cerrada', 'failure_mode': modo, 'real_end_date': today,
        }), content_type='application/json')

    r = auth_admin.get('/api/indicators/pareto-fallas?group=mode')
    assert r.status_code == 200
    data = r.json
    assert data['total'] >= 3
    labels = [i['label'] for i in data['items']]
    assert 'ROTURA' in labels and 'FUGA' in labels
    # % acumulado del ultimo item = 100
    assert abs(data['items'][-1]['cum_pct'] - 100.0) < 0.2


def test_predictive_tracking(auth_admin, app):
    # Crear un activo rotativo categoria BOMBA sin medidas -> sin_medidas
    r = auth_admin.post('/api/rotative-assets', data=json.dumps({
        'name': 'BOMBA TEST PREDICTIVO', 'category': 'BOMBA CENTRIFUGA',
    }), content_type='application/json')
    assert r.status_code in (200, 201)

    r2 = auth_admin.get('/api/rotative-assets/predictive-tracking')
    assert r2.status_code == 200
    data = r2.json
    assert data['summary']['total'] >= 1
    nombres = [a['name'] for a in data['assets']]
    assert 'BOMBA TEST PREDICTIVO' in nombres
    bomba = next(a for a in data['assets'] if a['name'] == 'BOMBA TEST PREDICTIVO')
    assert bomba['overall'] is None  # sin medidas configuradas


def test_diagnostico_data(auth_admin):
    """El diagnostico mensual devuelve todas las secciones del informe."""
    import datetime as dt
    mes = dt.date.today().strftime('%Y-%m')
    r = auth_admin.get(f'/api/diagnostico/data?month={mes}')
    assert r.status_code == 200, r.json
    data = r.json
    for key in ('meta', 'kpis_mes', 'kpis_prev', 'pareto_mes', 'pareto_6m',
                'top_equipos', 'trend', 'backlog', 'rutinas', 'predictivo',
                'almacen', 'informes', 'programa', 'programa_actual'):
        assert key in data, f"falta {key}"
    assert data['meta']['month'] == mes
    assert data['meta']['en_curso'] is True
    # Consolidado de 12 meses con indicadores de confiabilidad
    assert len(data['trend']) == 12
    for key in ('mtbf_h', 'disponibilidad_pct', 'confiabilidad_pct', 'mttr_h'):
        assert key in data['trend'][-1], f"falta {key} en trend"
    assert key in data['kpis_mes']
    # Mes en curso: KPIs parciales con dias transcurridos
    assert data['kpis_mes']['dias_efectivos'] == dt.date.today().day
    # Programa del resto del mes en curso + mes siguiente
    pa = data['programa_actual']
    assert pa is not None and pa['parcial'] is True
    prog = data['programa']
    assert 'capacidad' in prog and 'rutinas_semana' in prog
    assert len(prog['rutinas_semana']['lubricacion']) == 5  # 5 semanas del mes


def test_diagnostico_semanas(auth_admin):
    """El diagnostico incluye indicadores por semana del mes."""
    import datetime as dt
    mes = dt.date.today().strftime('%Y-%m')
    r = auth_admin.get(f'/api/diagnostico/data?month={mes}')
    assert r.status_code == 200
    semanas = r.json['semanas']
    assert len(semanas) >= 4  # todo mes tiene al menos 4 semanas
    s1 = semanas[0]
    for key in ('semana', 'rango', 'closed_total', 'correctivas', 'proactivas',
                'downtime_h', 'cumplimiento_pct', 'disponibilidad_pct', 'futura'):
        assert key in s1, f"falta {key}"
    assert s1['semana'] == 'Sem 1'


def test_pf_analysis(auth_admin, app):
    """Modulo P-F: equipos con datos, timeline y precursores."""
    import datetime as dt
    today = dt.date.today()

    # Equipo con punto de monitoreo, lectura fuera de rango y falla posterior
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment
        area = Area(name='AREA PF TEST')
        db.session.add(area); db.session.flush()
        line = Line(name='LINEA PF TEST', area_id=area.id)
        db.session.add(line); db.session.flush()
        eq = Equipment(name='EQUIPO PF TEST', tag='EQ-PF', line_id=line.id)
        db.session.add(eq); db.session.commit()
        eq_id = eq.id

    r = auth_admin.post('/api/monitoring/points', data=json.dumps({
        'name': 'VIB PF TEST', 'measurement_type': 'VIBRACION',
        'equipment_id': eq_id, 'frequency_days': 7,
        'normal_max': 4.5, 'alarm_max': 7.1,
    }), content_type='application/json')
    point_id = r.json['id']

    # Lectura fuera de rango 10 dias antes de la falla (senal previa)
    fecha_senal = (today - dt.timedelta(days=10)).isoformat()
    r2 = auth_admin.post('/api/monitoring/readings', data=json.dumps({
        'point_id': point_id, 'reading_date': fecha_senal, 'value': 8.0,
    }), content_type='application/json')
    assert r2.status_code in (200, 201), r2.json

    # Falla correctiva cerrada hoy en el mismo equipo
    auth_admin.post('/api/work-orders', data=json.dumps({
        'description': 'Falla PF test', 'maintenance_type': 'Correctivo',
        'status': 'Cerrada', 'equipment_id': eq_id,
        'failure_mode': 'VIBRACION EXCESIVA', 'real_end_date': today.isoformat(),
    }), content_type='application/json')

    # Equipos con datos
    r3 = auth_admin.get('/api/pf/equipos')
    assert r3.status_code == 200
    assert any(e['id'] == eq_id for e in r3.json)

    # Timeline del equipo
    r4 = auth_admin.get(f'/api/pf/timeline?equipment_id={eq_id}&months=6')
    assert r4.status_code == 200
    t = r4.json
    assert len(t['monitoring_series']) == 1
    assert len(t['monitoring_series'][0]['readings']) == 1
    assert len(t['fallas']) == 1

    # Precursores: la falla debe tener senal previa con ~10 dias de anticipacion
    r5 = auth_admin.get('/api/pf/precursores?months=6')
    assert r5.status_code == 200
    fila = next(f for f in r5.json['fallas'] if f['equipment_id'] == eq_id)
    assert fila['senal_previa'] is True
    assert fila['anticipacion_dias'] == 10
    assert r5.json['resumen']['fallas_analizadas'] >= 1


def test_diagnostico_ots_detail(auth_admin):
    """Drill-down: OTs detras de un modo de falla del Pareto."""
    import datetime as dt
    today = dt.date.today().isoformat()
    auth_admin.post('/api/work-orders', data=json.dumps({
        'description': 'Drill test', 'maintenance_type': 'Correctivo',
        'status': 'Cerrada', 'failure_mode': 'MODO DRILL TEST',
        'real_end_date': today,
    }), content_type='application/json')
    r = auth_admin.get('/api/diagnostico/ots-detail?window=6m&failure_mode=MODO DRILL TEST')
    assert r.status_code == 200
    assert r.json['total'] >= 1
    assert any(row['modo'] == 'MODO DRILL TEST' for row in r.json['rows'])


def test_diagnostico_narrativa_sin_api_key(auth_admin):
    """Sin DEEPSEEK_API_KEY el endpoint responde 501 con mensaje claro."""
    r = auth_admin.post('/api/diagnostico/narrativa', data=json.dumps({
        'meta': {'label': 'Test'}, 'kpis_mes': {}, 'kpis_prev': {},
    }), content_type='application/json')
    assert r.status_code in (501, 502)
    assert 'error' in r.json


def test_monitoring_point_accepts_rotative_asset(auth_admin):
    # El punto de monitoreo acepta rotative_asset_id (sigue al activo)
    r = auth_admin.post('/api/rotative-assets', data=json.dumps({
        'name': 'MOTOR TEST MON', 'category': 'MOTOR ELECTRICO',
    }), content_type='application/json')
    asset_id = r.json['id']

    r2 = auth_admin.post('/api/monitoring/points', data=json.dumps({
        'name': 'VIBRACION MOTOR TEST', 'measurement_type': 'VIBRACION',
        'frequency_days': 30, 'rotative_asset_id': asset_id,
    }), content_type='application/json')
    assert r2.status_code in (200, 201), r2.json
    assert r2.json.get('rotative_asset_id') == asset_id

    # Y el seguimiento predictivo lo refleja como medida del activo
    r3 = auth_admin.get('/api/rotative-assets/predictive-tracking')
    motor = next(a for a in r3.json['assets'] if a['name'] == 'MOTOR TEST MON')
    tipos = [m['tipo'] for m in motor['measures']]
    assert 'VIBRACION' in tipos
