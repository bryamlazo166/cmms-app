"""Separacion de disponibilidad OPERATIVA vs INHERENTE por tipo de paro.

Escenario: mes de 30 dias (T = 720 h) con dos OTs correctivas cerradas
con parada en el mismo equipo:
  - averia imprevista de 12 h (downtime_planned = NULL → derivado averia)
  - correctivo PROGRAMADO de 48 h (downtime_planned = True)

Formulas esperadas (Pp = paro planificado, Pn = averias):
  operativa = (T - Pp - Pn) / T        = 660/720 = 91.67 %
  inherente = (T - Pp - Pn) / (T - Pp) = 660/672 = 98.21 %
"""
import json

import pytest


START = '2026-06-01'
END = '2026-06-30'


@pytest.fixture
def kpi_env(app):
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment, WorkOrder
        area = Area(name='AREA DISP TEST')
        db.session.add(area); db.session.flush()
        line = Line(name='LINEA DISP TEST', area_id=area.id)
        db.session.add(line); db.session.flush()
        eq = Equipment(name='EQUIPO DISP TEST', tag='EQ-DISP', line_id=line.id)
        db.session.add(eq); db.session.flush()

        ot_averia = WorkOrder(
            code='OT-DISP-AVERIA', status='Cerrada', maintenance_type='Correctivo',
            description='Falla imprevista rodamiento',
            area_id=area.id, line_id=line.id, equipment_id=eq.id,
            scheduled_date='2026-06-10',
            caused_downtime=True, downtime_hours=12.0,
        )
        ot_programado = WorkOrder(
            code='OT-DISP-PROG', status='Cerrada', maintenance_type='Correctivo',
            description='Cambio de chumacera programado',
            area_id=area.id, line_id=line.id, equipment_id=eq.id,
            scheduled_date='2026-06-20',
            caused_downtime=True, downtime_hours=48.0,
            downtime_planned=True,
        )
        db.session.add_all([ot_averia, ot_programado])
        db.session.commit()
        env = {'area_id': area.id, 'line_id': line.id,
               'equipment_id': eq.id,
               'ot_ids': [ot_averia.id, ot_programado.id]}

    yield env

    with app.app_context():
        from database import db
        from models import Area, Line, Equipment, WorkOrder
        WorkOrder.query.filter(WorkOrder.id.in_(env['ot_ids'])).delete(synchronize_session=False)
        Equipment.query.filter_by(id=env['equipment_id']).delete()
        Line.query.filter_by(id=env['line_id']).delete()
        Area.query.filter_by(id=env['area_id']).delete()
        db.session.commit()


def _area_row(resp, area_id):
    assert resp.status_code == 200, resp.data
    return next(a for a in resp.json['areas'] if a['area_id'] == area_id)


def test_disponibilidad_operativa_descuenta_todo_el_paro(auth_admin, kpi_env):
    r = auth_admin.get(f'/api/indicators/areas?start_date={START}&end_date={END}&mode=operativa')
    row = _area_row(r, kpi_env['area_id'])

    # (720 - 48 - 12) / 720 = 91.67 %
    assert row['availability'] == pytest.approx(91.67, abs=0.01)
    assert row['availability_operativa'] == pytest.approx(91.67, abs=0.01)
    # La inherente viaja SIEMPRE en la respuesta: 660 / 672 = 98.21 %
    assert row['availability_inherente'] == pytest.approx(98.21, abs=0.01)
    # En operativa ambos paros cuentan como eventos
    assert row['failure_count'] == 2
    assert row['downtime_hours'] == pytest.approx(60.0)
    assert row['downtime_planned_hours'] == pytest.approx(48.0)
    assert row['downtime_unplanned_hours'] == pytest.approx(12.0)
    assert row['mttr'] == pytest.approx(30.0)


def test_disponibilidad_inherente_solo_castiga_averias(auth_admin, kpi_env):
    r = auth_admin.get(f'/api/indicators/areas?start_date={START}&end_date={END}&mode=inherente')
    row = _area_row(r, kpi_env['area_id'])

    # (720 - 48 - 12) / (720 - 48) = 98.21 %
    assert row['availability'] == pytest.approx(98.21, abs=0.01)
    assert row['availability_inherente'] == pytest.approx(98.21, abs=0.01)
    assert row['availability_operativa'] == pytest.approx(91.67, abs=0.01)
    # Solo la averia cuenta como falla
    assert row['failure_count'] == 1
    assert row['downtime_hours'] == pytest.approx(12.0)
    assert row['mttr'] == pytest.approx(12.0)
    # inherente >= operativa siempre
    assert row['availability_inherente'] >= row['availability_operativa']


def test_drilldown_equipo_expone_ambas_disponibilidades(auth_admin, kpi_env):
    eq_id = kpi_env['equipment_id']
    r = auth_admin.get(f'/api/indicators/equipment/{eq_id}/failures'
                       f'?start_date={START}&end_date={END}&mode=operativa')
    assert r.status_code == 200, r.data
    data = r.json
    assert data['availability_operativa'] == pytest.approx(91.67, abs=0.01)
    assert data['availability_inherente'] == pytest.approx(98.21, abs=0.01)
    # La clasificacion viaja en las fallas consolidadas
    clases = {f['code']: f['downtime_planned'] for f in data['failures']}
    assert clases['OT-DISP-AVERIA'] is False
    assert clases['OT-DISP-PROG'] is True


def test_patch_hours_acepta_downtime_planned(auth_admin, kpi_env, app):
    ot_id = kpi_env['ot_ids'][0]  # la averia (downtime_planned NULL)
    r = auth_admin.patch(f'/api/work-orders/{ot_id}/hours', data=json.dumps({
        'downtime_planned': True,
        'reason': 'Reclasificacion: el paro fue programado con produccion',
    }), content_type='application/json')
    assert r.status_code == 200, r.data
    assert r.json['downtime_planned'] is True

    # Reclasificada como planificada: la inherente del area sube a 100 %
    resp = auth_admin.get(f'/api/indicators/areas?start_date={START}&end_date={END}&mode=inherente')
    row = _area_row(resp, kpi_env['area_id'])
    assert row['failure_count'] == 0
    assert row['availability'] == pytest.approx(100.0, abs=0.01)

    # Revertir para no ensuciar otros asserts del fixture
    with app.app_context():
        from database import db
        from models import WorkOrder
        wo = WorkOrder.query.get(ot_id)
        wo.downtime_planned = None
        db.session.commit()
