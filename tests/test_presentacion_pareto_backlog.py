"""Presentacion para gerencia: backlog, pareto de modos de falla y nombres.

Tres reglas que se decidieron mirando los datos de planta y que es facil
romper sin darse cuenta:

  · el backlog se divide entre los tecnicos que EJECUTAN (mecanicos y
    electricistas de alta), no entre los 23 nombres del maestro;
  · el pareto de modos de falla suma horas con el mismo criterio de averia
    que la lamina de disponibilidad, para que los dos numeros hablen de lo
    mismo delante de la gerencia;
  · en pantalla van nombres de equipo, no tags: "DIGESTOR #6", no "D6".
"""
import pytest

from routes.presentacion_routes import (HORAS_SEMANA_TECNICO, _descripcion,
                                        _legible, _modo, es_ejecutor)


# ── Nombres y textos: lo que lee la gerencia ─────────────────────────────

def test_el_equipo_se_nombra_sin_tag_y_sin_ambiguedad():
    # El nombre solo alcanza cuando ya es unico
    assert _legible('DIGESTOR #6', 'LINEA DIGESTOR #6', 'D6') == 'DIGESTOR #6'
    # ...pero hay siete equipos llamados "SECADOR" o "TH1": los distingue la linea
    assert _legible('SECADOR', 'SECADOR #2', 'SECA-SECA2') == 'SECADOR #2'
    assert _legible('TH1', 'LINEA ENFRIADOR #2', 'TH1-ENF2') == 'TH1 — ENFRIADOR #2'
    # Sin nombre cargado se cae a la linea, y en ultimo caso al tag
    assert _legible('', 'LINEA MOLINO #1', 'MOL1') == 'MOLINO #1'
    assert _legible('', '', 'MOL1') == 'MOL1'
    # Nunca se devuelve el tag cuando hay con que nombrarlo
    assert 'D6' not in _legible('DIGESTOR #6', 'LINEA DIGESTOR #6', 'D6')


def test_la_descripcion_pierde_el_metadato_del_formulario():
    crudo = ('Rotura del eje de ataque de la caja reductora del Digestor #6 '
             '| [Modo de falla: Rotura] | [Tipo: Mecanica]')
    limpia = _descripcion(crudo)
    assert limpia.startswith('Rotura del eje de ataque')
    assert '[' not in limpia and 'Modo de falla' not in limpia
    assert _descripcion(None) == '—'


def test_el_modo_de_falla_se_rescata_de_la_descripcion_si_falta_el_campo():
    # El campo manda
    assert _modo({'failure_mode': 'Rotura', 'description': 'x'}) == 'ROTURA'
    # Si no se lleno, se rescata del metadato que quedo escrito en el texto
    assert _modo({'failure_mode': None,
                  'description': 'Fuga | [Modo de falla: Aflojamiento] | [Tipo: Mecanica]'}) \
        == 'AFLOJAMIENTO'
    assert _modo({'failure_mode': '', 'description': 'sin metadato'}) == ''


def test_solo_mecanicos_y_electricistas_cuentan_como_ejecutores():
    assert es_ejecutor('MECANICO') and es_ejecutor('ELECTRICO')
    assert es_ejecutor('ELECTRICISTA') and es_ejecutor('MECANICA')
    assert not es_ejecutor('MULTIDISCIPLINARIO')
    assert not es_ejecutor('SUPERVISOR')
    assert not es_ejecutor(None)


# ── Backlog y pareto contra el endpoint ──────────────────────────────────

@pytest.fixture
def planta_de_prueba(app):
    """Un area con una linea, un equipo y ordenes cerradas y abiertas."""
    from database import db
    from models import Area, Equipment, Line, Technician, WorkOrder

    creado = {}
    with app.app_context():
        area = Area(name='PARETO PRUEBA', include_in_kpi=True)
        db.session.add(area)
        db.session.flush()
        linea = Line(name='LINEA PARETO', area_id=area.id)
        db.session.add(linea)
        db.session.flush()
        eq = Equipment(name='MOLINO', tag='MOLPRU', line_id=linea.id,
                       is_production_unit=True, capacity_tm_day=24.0,
                       include_in_kpi=True, in_service=True)
        db.session.add(eq)
        db.session.flush()

        tecnicos = [
            Technician(name='Mecanico de alta', specialty='MECANICO', is_active=True),
            Technician(name='Electricista de alta', specialty='ELECTRICO', is_active=True),
            # No ejecutan: uno de baja y un perfil que no va a campo
            Technician(name='Mecanico de baja', specialty='MECANICO', is_active=False),
            Technician(name='Planificador', specialty='MULTIDISCIPLINARIO', is_active=True),
        ]
        db.session.add_all(tecnicos)

        ots = [
            # Averia con paro: entra al pareto con horas
            WorkOrder(code='OT-PAR-1', status='Cerrada', equipment_id=eq.id,
                      maintenance_type='Correctivo', failure_mode='ROTURA DE EJE',
                      caused_downtime=True, downtime_hours=20.0,
                      downtime_planned=False, real_end_date='2026-07-10',
                      description='Rotura del eje | [Modo de falla: Rotura] | [Tipo: Mecanica]'),
            # Averia mas chica del mismo mes, otro modo
            WorkOrder(code='OT-PAR-2', status='Cerrada', equipment_id=eq.id,
                      maintenance_type='Correctivo', failure_mode='FUGA',
                      caused_downtime=True, downtime_hours=5.0,
                      downtime_planned=False, real_end_date='2026-07-12'),
            # Correctivo con paro PLANIFICADO: cuenta como evento, no como hora
            WorkOrder(code='OT-PAR-3', status='Cerrada', equipment_id=eq.id,
                      maintenance_type='Correctivo', failure_mode='DESGASTE',
                      caused_downtime=True, downtime_hours=40.0,
                      downtime_planned=True, real_end_date='2026-07-15'),
            # Mes anterior: solo debe aparecer en el consolidado de 6 meses
            WorkOrder(code='OT-PAR-4', status='Cerrada', equipment_id=eq.id,
                      maintenance_type='Correctivo', failure_mode='FUGA',
                      caused_downtime=True, downtime_hours=8.0,
                      downtime_planned=False, real_end_date='2026-06-11'),
            # Backlog: dos abiertas con estimado y una sin el
            WorkOrder(code='OT-PAR-5', status='Abierta', equipment_id=eq.id,
                      maintenance_type='Correctivo', estimated_duration=10.0,
                      scheduled_date='2026-07-20'),
            WorkOrder(code='OT-PAR-6', status='Programada', equipment_id=eq.id,
                      maintenance_type='Preventivo', estimated_duration=6.0,
                      scheduled_date='2026-07-25'),
            WorkOrder(code='OT-PAR-7', status='Abierta', equipment_id=eq.id,
                      maintenance_type='Correctivo'),
            # Anulada: no es backlog, nadie la va a ejecutar
            WorkOrder(code='OT-PAR-8', status='Anulada', equipment_id=eq.id,
                      maintenance_type='Correctivo', estimated_duration=99.0),
        ]
        db.session.add_all(ots)
        db.session.commit()
        creado = {'area': area.id, 'linea': linea.id, 'equipo': eq.id,
                  'tecnicos': [t.id for t in tecnicos],
                  'ots': [o.id for o in ots]}

    yield creado

    with app.app_context():
        from models import Area, Equipment, Line, Technician, WorkOrder
        WorkOrder.query.filter(WorkOrder.id.in_(creado['ots'])).delete(
            synchronize_session=False)
        Technician.query.filter(Technician.id.in_(creado['tecnicos'])).delete(
            synchronize_session=False)
        db.session.delete(db.session.get(Equipment, creado['equipo']))
        db.session.delete(db.session.get(Line, creado['linea']))
        db.session.delete(db.session.get(Area, creado['area']))
        db.session.commit()


def test_el_backlog_se_divide_entre_los_que_ejecutan(app, auth_admin, planta_de_prueba):
    d = auth_admin.get('/api/presentacion/data'
                       '?month=2026-07&vista=mes&meses=1&modo=inherente').json
    carga = d['carga'][-1]
    cuad, bl = carga['cuadrilla'], carga['backlog']

    with app.app_context():
        from models import Technician
        activos = Technician.query.filter_by(is_active=True).all()
        esperados = sum(1 for t in activos if es_ejecutor(t.specialty))

    # El maestro tiene mas nombres de los que toman una herramienta
    assert cuad['ejecutores'] == esperados
    assert cuad['ejecutores'] < cuad['registrados']
    assert {e['especialidad'] for e in cuad['detalle']} <= {'MECANICO', 'ELECTRICO'}
    assert cuad['horas_semana'] == HORAS_SEMANA_TECNICO
    assert cuad['capacidad_semana_h'] == cuad['ejecutores'] * HORAS_SEMANA_TECNICO

    # Las tres abiertas entran; la anulada no
    codigos = {o['code'] for o in bl['mas_antiguas']}
    assert 'OT-PAR-8' not in codigos
    assert bl['ots'] >= 3 and bl['ots_con_estimado'] >= 2

    # Las que no tienen estimado se valorizan con el promedio de las que si,
    # nunca como cero: si no, el backlog saldria mas sano de lo que es.
    assert bl['horas_estimadas'] >= bl['horas_registradas']
    assert bl['semanas'] == pytest.approx(
        bl['horas_estimadas'] / bl['capacidad_semana_h'], abs=0.05)


def test_el_backlog_no_se_calcula_sobre_el_maestro_completo(app, auth_admin,
                                                            planta_de_prueba):
    """Con 23 nombres en vez de 6 tecnicos, el backlog sale casi cuatro veces
    mas sano. Es el error que esta prueba cuida."""
    d = auth_admin.get('/api/presentacion/data'
                       '?month=2026-07&vista=mes&meses=1&modo=inherente').json
    bl = d['carga'][-1]['backlog']
    cuad = d['carga'][-1]['cuadrilla']
    con_maestro = bl['horas_estimadas'] / (cuad['registrados'] * HORAS_SEMANA_TECNICO)
    assert bl['semanas'] > con_maestro


def test_el_pareto_ordena_por_horas_y_separa_el_paro_planificado(auth_admin,
                                                                 planta_de_prueba):
    d = auth_admin.get('/api/presentacion/pareto?month=2026-07&meses=6').json
    modos = {m['modo']: m for m in d['mes']['modos']}

    # La averia mas cara del mes encabeza
    assert d['mes']['modos'][0]['horas'] >= d['mes']['modos'][-1]['horas']
    assert modos['ROTURA DE EJE']['horas'] >= 20.0
    assert modos['ROTURA DE EJE']['eventos'] >= 1

    # Un correctivo ejecutado en parada planificada cuenta como evento —
    # consumio cuadrilla— pero sus horas NO son averia, que es el criterio
    # con el que se mide la disponibilidad inherente en la lamina 02.
    assert modos['DESGASTE']['eventos'] >= 1
    assert modos['DESGASTE']['horas'] == 0.0
    assert modos['DESGASTE']['horas_planificadas'] >= 40.0


def test_el_consolidado_de_seis_meses_ve_lo_que_el_mes_no(auth_admin,
                                                          planta_de_prueba):
    d = auth_admin.get('/api/presentacion/pareto?month=2026-07&meses=6').json
    mes = {m['modo']: m for m in d['mes']['modos']}
    his = {m['modo']: m for m in d['historico']['modos']}

    # La fuga de junio no esta en el mes, pero si en la ventana larga: es
    # justo lo que distingue un evento aislado de un problema de fondo.
    assert his['FUGA']['horas'] > mes['FUGA']['horas']
    assert his['FUGA']['eventos'] > mes['FUGA']['eventos']
    assert d['historico']['desde'] < d['mes']['desde']
    assert d['historico']['hasta'] == d['mes']['hasta']


def test_el_ranking_de_equipos_usa_nombres_y_no_tags(auth_admin, planta_de_prueba):
    d = auth_admin.get('/api/presentacion/pareto?month=2026-07&meses=6').json
    nombres = [e['equipo'] for e in d['mes']['equipos']]
    assert nombres, 'ningun equipo con parada en el mes de prueba'
    assert 'MOLINO — PARETO' in nombres or 'MOLINO' in ' '.join(nombres)
    assert 'MOLPRU' not in ' '.join(nombres), 'se esta mostrando el tag'


def test_las_ordenes_del_detalle_llegan_sin_tag_y_con_modo_de_falla(
        auth_admin, planta_de_prueba):
    # El area de prueba no es de proceso, asi que se pide por su id: con
    # area_id=0 el detalle responde solo por coccion, secado y molino.
    aid = planta_de_prueba['area']
    d = auth_admin.get(f'/api/presentacion/detalle?area_id={aid}'
                       '&desde=2026-07-01&hasta=2026-07-31&modo=inherente').json
    ots = {o['code']: o for o in d['ots']}
    o = ots.get('OT-PAR-1')
    assert o is not None, 'la orden de prueba no llego al detalle'
    assert o['modo_falla'] == 'ROTURA DE EJE'
    assert '[' not in o['descripcion'], 'la descripcion trae el metadato del formulario'
    assert 'MOLPRU' not in o['equipo'], 'se esta mostrando el tag del equipo'
