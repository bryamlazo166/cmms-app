"""Tests del predictivo de espesores (tasa de desgaste, vida remanente, reemplazos)."""
import pytest

from routes.thickness_predictive import compute_point_forecast


# ── Unidad: compute_point_forecast ─────────────────────────────────────────

def test_tasa_y_vida_remanente_basica():
    # 20.0 → 14.0 mm en 6 meses = ~12 mm/año; a 14 mm quedan 6 mm para el retiro (8)
    fc = compute_point_forecast(
        [('2026-01-01', 20.0), ('2026-07-01', 14.0)], alarm=10.0, scrap=8.0)
    assert fc['rate_mm_yr'] == pytest.approx(12.0, abs=0.5)
    assert fc['months_to_scrap'] == pytest.approx(6.0, abs=0.5)
    assert fc['months_to_alarm'] == pytest.approx(4.0, abs=0.5)
    assert fc['status'] == 'ROJO'          # < 6 meses
    assert fc['scrap_date'].startswith('2026-12') or fc['scrap_date'].startswith('2027-01')


def test_deteccion_de_reemplazo_reinicia_tendencia():
    # Caso real D9: desgastada (3.4), reparada (8.4), reemplazada (25.4), midiendo de nuevo
    fc = compute_point_forecast([
        ('2026-01-19', 3.4), ('2026-04-14', 8.4),
        ('2026-05-02', 25.4), ('2026-07-01', 24.2),
    ], alarm=10.0, scrap=8.0)
    assert len(fc['interventions']) == 2           # dos subidas de espesor
    assert fc['interventions'][-1]['date'] == '2026-05-02'
    assert fc['n_segment'] == 2                    # tendencia solo desde el reemplazo
    assert fc['current'] == 24.2
    # tasa del segmento nuevo: 1.2 mm en ~60 dias ≈ 7.3 mm/año → >18 meses → VERDE
    assert fc['rate_mm_yr'] == pytest.approx(7.3, abs=0.5)
    assert fc['status'] == 'VERDE'


def test_bajo_espesor_de_retiro_es_critico():
    fc = compute_point_forecast(
        [('2026-01-01', 9.0), ('2026-06-01', 3.4)], alarm=10.0, scrap=8.0)
    assert fc['status'] == 'CRITICO'


def test_una_sola_medicion_sin_tendencia():
    fc = compute_point_forecast([('2026-05-01', 22.0)], alarm=10.0, scrap=8.0)
    assert fc['status'] == 'SIN_TENDENCIA'
    assert fc['rate_mm_yr'] is None


def test_punto_estable_sin_desgaste():
    fc = compute_point_forecast(
        [('2026-01-01', 20.0), ('2026-06-01', 20.0)], alarm=10.0, scrap=8.0)
    assert fc['status'] == 'ESTABLE'


def test_reemplazo_reciente_sin_segunda_medicion():
    fc = compute_point_forecast(
        [('2026-01-01', 9.5), ('2026-05-01', 25.4)], alarm=10.0, scrap=8.0)
    assert len(fc['interventions']) == 1
    assert fc['status'] == 'SIN_TENDENCIA'   # el segmento nuevo tiene 1 sola medición


def test_sin_lecturas_devuelve_none():
    assert compute_point_forecast([], alarm=10, scrap=8) is None


def test_lecturas_imposibles_se_descartan():
    # Caso real D7: campaña cargada con 25.0 en puntos de nominal 13.49 —
    # físicamente imposible medir más que el nominal (+10% tolerancia).
    fc = compute_point_forecast(
        [('2026-04-01', 25.0), ('2026-07-03', 13.49)],
        alarm=10.0, scrap=8.0, nominal=13.49)
    assert fc['discarded'] == 1
    assert fc['n_total'] == 1
    assert fc['status'] == 'SIN_TENDENCIA'   # queda 1 sola lectura válida
    assert fc['rate_mm_yr'] is None          # NO proyecta con el dato basura


def test_todas_las_lecturas_imposibles_marca_dato_dudoso():
    fc = compute_point_forecast(
        [('2026-04-01', 25.0), ('2026-07-03', 17.48)],
        alarm=10.0, scrap=8.0, nominal=13.49)
    assert fc['status'] == 'DATO_DUDOSO'
    assert fc['discarded'] == 2


def test_lectura_igual_al_nominal_es_valida():
    # Una pieza nueva mide ≈ nominal: eso SÍ es válido
    fc = compute_point_forecast(
        [('2026-01-01', 25.4), ('2026-07-01', 20.0)],
        alarm=10.0, scrap=8.0, nominal=25.4)
    assert fc['discarded'] == 0
    assert fc['rate_mm_yr'] is not None
    assert fc['status'] in ('VERDE', 'AMBAR')


# ── Endpoints ──────────────────────────────────────────────────────────────

@pytest.fixture
def thk_env(app):
    """Equipo con 2 puntos: uno con desgaste ROJO y otro sin mediciones."""
    from database import db
    from models import (Area, Line, Equipment, ThicknessPoint,
                        ThicknessInspection, ThicknessReading)
    with app.app_context():
        existing = Equipment.query.filter_by(tag='DPRED').first()
        if existing:
            return {'eq_id': existing.id}
        area = Area(name='ZONA TEST THK')
        db.session.add(area); db.session.flush()
        line = Line(name='LINEA THK', area_id=area.id)
        db.session.add(line); db.session.flush()
        eq = Equipment(name='DIGESTOR PRED TEST', tag='DPRED', line_id=line.id)
        db.session.add(eq); db.session.flush()

        p1 = ThicknessPoint(equipment_id=eq.id, group_name='CHAQUETA', section=1,
                            position='A', nominal_thickness=25.4,
                            alarm_thickness=10.0, scrap_thickness=8.0)
        p2 = ThicknessPoint(equipment_id=eq.id, group_name='TAPA_MOTRIZ',
                            position='P1', nominal_thickness=25.4,
                            alarm_thickness=10.0, scrap_thickness=8.0)
        db.session.add_all([p1, p2]); db.session.flush()

        i1 = ThicknessInspection(equipment_id=eq.id, inspection_date='2026-01-01',
                                 status='COMPLETA', frequency_days=60)
        i2 = ThicknessInspection(equipment_id=eq.id, inspection_date='2026-07-01',
                                 status='COMPLETA', frequency_days=60)
        db.session.add_all([i1, i2]); db.session.flush()
        db.session.add_all([
            ThicknessReading(inspection_id=i1.id, point_id=p1.id, value_mm=20.0),
            ThicknessReading(inspection_id=i2.id, point_id=p1.id, value_mm=14.0),
        ])
        db.session.commit()
        return {'eq_id': eq.id}


def test_summary_endpoint(auth_admin, thk_env):
    r = auth_admin.get('/api/thickness/predictive/summary')
    assert r.status_code == 200
    data = r.get_json()
    mine = [e for e in data if e['tag'] == 'DPRED']
    assert mine, 'el equipo de prueba debe aparecer en el resumen'
    eq = mine[0]
    assert eq['campaigns'] == 2
    assert eq['points_total'] == 2
    assert eq['points_with_rate'] == 1
    assert eq['semaforo'] == 'ROJO'
    assert eq['worst']['group_name'] == 'CHAQUETA'
    assert eq['worst']['months_to_scrap'] == pytest.approx(6.0, abs=0.5)


def test_detail_endpoint(auth_admin, thk_env):
    r = auth_admin.get(f"/api/thickness/predictive/{thk_env['eq_id']}")
    assert r.status_code == 200
    d = r.get_json()
    assert d['tag'] == 'DPRED'
    groups = {z['group_name'] for z in d['zones']}
    assert groups == {'CHAQUETA', 'TAPA_MOTRIZ'}
    # La zona con desgaste va primero (peor severidad)
    assert d['zones'][0]['group_name'] == 'CHAQUETA'
    pt = d['zones'][0]['points'][0]
    assert pt['status'] == 'ROJO'
    assert pt['rate_mm_yr'] == pytest.approx(12.0, abs=0.5)
    # El punto sin mediciones existe pero sin estado
    tapa = [z for z in d['zones'] if z['group_name'] == 'TAPA_MOTRIZ'][0]
    assert tapa['points'][0]['status'] is None


def test_narrative_sin_api_key_da_503(auth_admin, thk_env, monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    r = auth_admin.post(f"/api/thickness/predictive/{thk_env['eq_id']}/narrative")
    assert r.status_code == 503


def test_page_requires_login(client):
    r = client.get('/espesores/predictivo')
    assert r.status_code in (301, 302)  # redirect a login
