"""Tests del modulo Pendientes.

Cubre las tres cosas que lo hacen util:
  - anotar de corrido y que salgan solos el plazo, la prioridad y el equipo;
  - que terminarlo NO lo borre: pasa a Hecho, sale de la lista activa y queda
    la bitacora de quien lo cerro, cuando y con que comentario;
  - que pueda vivir sin OT y, si amerita, convertirse en aviso.
"""
import json
from datetime import date, timedelta

import pytest

from utils.pending_helpers import parse_due_phrase, infer_priority, overdue_days


# ── Parseo del plazo escrito de corrido ──────────────────────────────────────

HOY = date(2026, 9, 3)   # jueves


@pytest.mark.parametrize("texto,esperado,limpio", [
    ("fabricar tripode para el D3 en 2 semanas", "2026-09-17", "fabricar tripode para el D3"),
    ("comprar reten del D5 manana", "2026-09-04", "comprar reten del D5"),
    ("revisar el TH1 hoy", "2026-09-03", "revisar el TH1"),
    ("cambiar faja en un mes", "2026-10-03", "cambiar faja"),
    ("entregar informe el viernes", "2026-09-04", "entregar informe"),
    ("reingresar a inspeccion 45d", "2026-10-18", "reingresar a inspeccion"),
    ("recibir eje 2026-06-15", "2026-06-15", "recibir eje"),
    ("pintar barandas de coccion", None, "pintar barandas de coccion"),
])
def test_parse_due_phrase(texto, esperado, limpio):
    due, clean = parse_due_phrase(texto, today=HOY)
    assert due == esperado
    assert clean == limpio


@pytest.mark.parametrize("texto,esperado", [
    ("urgente cambiar el reten", "Alta"),
    ("es critico, el D3 esta parado", "Alta"),
    ("comprar pernos cuando se pueda", "Baja"),
    ("revisar el motor", "Normal"),
])
def test_infer_priority(texto, esperado):
    assert infer_priority(texto) == esperado


def test_overdue_days():
    assert overdue_days('2026-09-01', HOY) == 2      # vencido hace 2 dias
    assert overdue_days('2026-09-03', HOY) == 0      # vence hoy
    assert overdue_days('2026-09-10', HOY) == -7     # faltan 7
    assert overdue_days(None, HOY) is None


# ── API ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def equipo(app):
    """Un equipo con componente para probar el anclaje al arbol."""
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment, System, Component
        eq = Equipment.query.filter_by(tag='PEND-EQ').first()
        if not eq:
            area = Area(name='AREA PENDIENTES')
            db.session.add(area)
            db.session.flush()
            line = Line(name='LINEA PENDIENTES', area_id=area.id)
            db.session.add(line)
            db.session.flush()
            eq = Equipment(name='EQUIPO DE PRUEBA', tag='PEND-EQ', line_id=line.id)
            db.session.add(eq)
            db.session.flush()
            sys_ = System(name='SISTEMA DE ACCIONAMIENTO', equipment_id=eq.id)
            db.session.add(sys_)
            db.session.flush()
            db.session.add(Component(name='CHUMACERA MOTRIZ', system_id=sys_.id))
            db.session.commit()
        return eq.id


def _crear(client, **body):
    return client.post('/api/pending-tasks', data=json.dumps(body),
                       content_type='application/json')


def test_crear_pendiente_minimo(auth_admin):
    r = _crear(auth_admin, description='pintar barandas del area de coccion')
    assert r.status_code == 201
    d = r.get_json()
    assert d['code'].startswith('PEND-')
    assert d['status'] == 'Pendiente'
    assert d['due_date'] is None          # sin plazo: no vence
    assert d['equipment_id'] is None      # sin equipo: es valido
    assert d['source'] == 'web'


def test_el_plazo_sale_del_texto(auth_admin):
    r = _crear(auth_admin, description='fabricar soporte en 2 semanas')
    d = r.get_json()
    esperado = (date.today() + timedelta(days=14)).isoformat()
    assert d['due_date'] == esperado
    assert d['description'] == 'fabricar soporte'   # el plazo no se repite


def test_fecha_explicita_manda_sobre_el_texto(auth_admin):
    r = _crear(auth_admin, description='revisar bomba manana', due_date='2026-12-25')
    d = r.get_json()
    assert d['due_date'] == '2026-12-25'


def test_prioridad_desde_el_texto(auth_admin):
    d = _crear(auth_admin, description='urgente cambiar el reten').get_json()
    assert d['priority'] == 'Alta'


def test_se_ancla_al_equipo_y_componente(auth_admin, equipo):
    d = _crear(auth_admin, description='revisar juego',
               equipment_tag='PEND-EQ', component_name='chumacera motriz').get_json()
    assert d['equipment_id'] == equipo
    assert d['equipment_tag'] == 'PEND-EQ'
    assert d['component_name'] == 'CHUMACERA MOTRIZ'
    assert 'AREA PENDIENTES' in (d['location_path'] or '')


def test_descripcion_obligatoria(auth_admin):
    assert _crear(auth_admin, description='   ').status_code == 400


# ── Terminar sin borrar: la bitacora ────────────────────────────────────────

def test_marcar_hecho_conserva_la_bitacora(auth_admin):
    tid = _crear(auth_admin, description='fabricar tripode').get_json()['id']

    r = auth_admin.post(f'/api/pending-tasks/{tid}/done',
                        data=json.dumps({'comment': 'se fabrico e instalo',
                                         'done_by': 'Marcos Campos'}),
                        content_type='application/json')
    assert r.status_code == 200
    d = r.get_json()
    assert d['status'] == 'Hecho'
    assert d['done_by'] == 'Marcos Campos'
    assert d['done_comment'] == 'se fabrico e instalo'
    assert d['done_date'] == date.today().isoformat()

    # Sale de la lista activa...
    abiertos = auth_admin.get('/api/pending-tasks?status=Pendiente').get_json()['rows']
    assert tid not in [x['id'] for x in abiertos]
    # ...pero sigue existiendo con su historia.
    hechos = auth_admin.get('/api/pending-tasks?status=Hecho').get_json()['rows']
    guardado = next(x for x in hechos if x['id'] == tid)
    assert guardado['done_comment'] == 'se fabrico e instalo'


def test_anular_tambien_deja_rastro(auth_admin):
    tid = _crear(auth_admin, description='comprar valvula').get_json()['id']
    d = auth_admin.post(f'/api/pending-tasks/{tid}/cancel',
                        data=json.dumps({'comment': 'ya no aplica, se cambio el diseno'}),
                        content_type='application/json').get_json()
    assert d['status'] == 'Anulado'
    assert 'ya no aplica' in d['done_comment']


def test_delete_no_borra_anula(auth_admin):
    """DELETE existe por comodidad del front, pero nunca borra la fila."""
    tid = _crear(auth_admin, description='algo que se descarta').get_json()['id']
    auth_admin.delete(f'/api/pending-tasks/{tid}?reason=duplicado')
    todos = auth_admin.get('/api/pending-tasks?status=todos').get_json()['rows']
    fila = next(x for x in todos if x['id'] == tid)
    assert fila['status'] == 'Anulado'
    assert fila['done_comment'] == 'duplicado'


def test_reabrir_limpia_el_cierre(auth_admin):
    tid = _crear(auth_admin, description='revisar filtros').get_json()['id']
    auth_admin.post(f'/api/pending-tasks/{tid}/done',
                    data=json.dumps({'comment': 'listo'}), content_type='application/json')
    d = auth_admin.post(f'/api/pending-tasks/{tid}/reopen').get_json()
    assert d['status'] == 'Pendiente'
    assert d['done_by'] is None and d['done_comment'] is None and d['done_date'] is None


# ── Listado y resumen ───────────────────────────────────────────────────────

def test_listado_marca_vencidos_y_resume(auth_admin):
    ayer = (date.today() - timedelta(days=3)).isoformat()
    _crear(auth_admin, description='pendiente vencido', due_date=ayer)
    _crear(auth_admin, description='pendiente de hoy', due_date=date.today().isoformat())
    _crear(auth_admin, description='pendiente sin fecha')

    j = auth_admin.get('/api/pending-tasks?status=Pendiente').get_json()
    venc = next(r for r in j['rows'] if r['description'] == 'pendiente vencido')
    assert venc['due_status'] == 'VENCIDO' and venc['overdue_days'] == 3
    hoy = next(r for r in j['rows'] if r['description'] == 'pendiente de hoy')
    assert hoy['due_status'] == 'HOY'
    assert j['summary']['vencidos'] >= 1
    assert j['summary']['hoy'] >= 1
    assert j['summary']['sin_fecha'] >= 1


def test_busqueda_por_texto(auth_admin):
    _crear(auth_admin, description='comprar empaquetadura grafitada')
    rows = auth_admin.get('/api/pending-tasks?q=grafitada').get_json()['rows']
    assert any('grafitada' in r['description'] for r in rows)


# ── Convertir en aviso ──────────────────────────────────────────────────────

def test_convertir_en_aviso(auth_admin, equipo):
    tid = _crear(auth_admin, description='cambiar chumacera gastada',
                 equipment_tag='PEND-EQ').get_json()['id']
    r = auth_admin.post(f'/api/pending-tasks/{tid}/to-notice',
                        data=json.dumps({}), content_type='application/json')
    assert r.status_code == 201
    j = r.get_json()
    assert j['notice_code'].startswith('AV-')
    # El pendiente sigue abierto pero ya apunta al aviso: no se pierde el rastro
    assert j['task']['notice_id'] == j['notice_id']
    assert j['task']['status'] == 'Pendiente'

    # No se puede convertir dos veces
    r2 = auth_admin.post(f'/api/pending-tasks/{tid}/to-notice',
                         data=json.dumps({}), content_type='application/json')
    assert r2.status_code == 400


def test_pagina_carga(auth_admin):
    r = auth_admin.get('/pendientes')
    assert r.status_code == 200
    assert b'Pendientes' in r.data


def test_requiere_login(client):
    client.get('/logout')
    r = client.get('/api/pending-tasks')
    assert r.status_code in (302, 401)


# ── Bot: /p, /listo, /pendientes ────────────────────────────────────────────

@pytest.fixture
def equipos_th(app):
    """Dos equipos que comparten el fragmento 'TH1' en el tag: el caso que
    obliga a desambiguar con el resto de la frase."""
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment, System, Component
        if not Equipment.query.filter_by(tag='SEC2-TH1').first():
            area = Area(name='AREA SECADO')
            db.session.add(area)
            db.session.flush()
            l1 = Line(name='SECADOR #2', area_id=area.id)
            l2 = Line(name='LINEA DIGESTOR #1', area_id=area.id)
            db.session.add_all([l1, l2])
            db.session.flush()
            th_sec = Equipment(name='TH1', tag='SEC2-TH1', line_id=l1.id)
            th_dig = Equipment(name='TH1', tag='TH1', line_id=l2.id)
            db.session.add_all([th_sec, th_dig])
            db.session.flush()
            for eq in (th_sec, th_dig):
                s1 = System(name='TORNILLO SINFIN', equipment_id=eq.id)
                s2 = System(name='SISTEMA ELECTRICO', equipment_id=eq.id)
                db.session.add_all([s1, s2])
                db.session.flush()
                db.session.add_all([
                    Component(name='HELICE', system_id=s1.id),
                    Component(name='TUBO CENTRAL', system_id=s1.id),
                    Component(name='RELE TERMICO', system_id=s2.id),
                ])
            db.session.commit()


def test_bot_anota_pendiente_con_plazo_y_prioridad(app):
    from bot.actions.pending import create_pending
    task, ambiguos, err = create_pending(
        app, 'urgente fabricar tripode en 2 semanas', 'Jasson Lazo')
    assert err is None
    assert task['code'].startswith('PEND-')
    assert task['description'] == 'urgente fabricar tripode'
    assert task['due_date'] == (date.today() + timedelta(days=14)).isoformat()
    assert task['priority'] == 'Alta'
    assert task['source'] == 'telegram'
    assert task['created_by'] == 'Jasson Lazo'
    assert not ambiguos


def test_bot_ancla_al_equipo_por_tag_exacto(app, equipos_th):
    from bot.actions.pending import create_pending
    task, ambiguos, err = create_pending(app, 'revisar el SEC2-TH1 el viernes', 'Tester')
    assert err is None and not ambiguos
    assert task['equipment_tag'] == 'SEC2-TH1'


def test_bot_desambigua_con_el_resto_de_la_frase(app, equipos_th):
    """'TH1' existe en dos lineas: 'del secador 2' decide cual."""
    from bot.actions.pending import create_pending
    task, ambiguos, err = create_pending(
        app, 'cambiar el tubo central del TH1 del secador 2', 'Tester')
    assert err is None
    assert task['equipment_tag'] == 'SEC2-TH1'
    assert not ambiguos


def test_bot_tag_exacto_desempata_si_no_hay_mas_contexto(app, equipos_th):
    """'TH1' a secas, existiendo un equipo con ese tag exacto, cae ahi."""
    from bot.actions.pending import create_pending
    task, ambiguos, err = create_pending(app, 'revisar el TH1', 'Tester')
    assert err is None and not ambiguos
    assert task['equipment_tag'] == 'TH1'


def test_bot_prefiere_no_anclar_antes_que_equivocarse(app):
    """Dos equipos comparten el fragmento y ninguno tiene ese tag exacto: no
    inventa, deja el pendiente sin equipo y devuelve los candidatos."""
    from bot.actions.pending import create_pending
    with app.app_context():
        from database import db
        from models import Area, Line, Equipment
        if not Equipment.query.filter_by(tag='ENF1-TH9').first():
            area = Area(name='AREA ENFRIADO')
            db.session.add(area)
            db.session.flush()
            l1 = Line(name='ENFRIADOR #1', area_id=area.id)
            l2 = Line(name='ENFRIADOR #2', area_id=area.id)
            db.session.add_all([l1, l2])
            db.session.flush()
            db.session.add_all([
                Equipment(name='TH9', tag='ENF1-TH9', line_id=l1.id),
                Equipment(name='TH9', tag='ENF2-TH9', line_id=l2.id),
            ])
            db.session.commit()
    task, ambiguos, err = create_pending(app, 'revisar el TH9', 'Tester')
    assert err is None
    assert task['equipment_id'] is None
    assert {t for _i, t, _n in ambiguos} == {'ENF1-TH9', 'ENF2-TH9'}


def test_bot_aplica_las_reglas_de_th_al_anotar(app, equipos_th):
    """El pendiente hereda la taxonomia correcta: 'tornillo helicoidal' es el
    tubo central, no la helice."""
    from bot.actions.pending import create_pending
    task, _amb, err = create_pending(
        app, 'reparar el tornillo helicoidal del SEC2-TH1', 'Tester')
    assert err is None
    assert task['component_name'] == 'TUBO CENTRAL'


def test_bot_cierra_y_deja_bitacora(app):
    from bot.actions.pending import create_pending, close_pending
    task, _a, _e = create_pending(app, 'comprar empaquetadura', 'Tester')
    cerrado, err = close_pending(app, task['code'], 'Marcos Campos', 'se compro y se instalo')
    assert err is None
    assert cerrado['status'] == 'Hecho'
    assert cerrado['done_by'] == 'Marcos Campos'
    assert cerrado['done_comment'] == 'se compro y se instalo'


def test_bot_no_cierra_dos_veces_ni_codigos_raros(app):
    from bot.actions.pending import create_pending, close_pending
    task, _a, _e = create_pending(app, 'revisar valvula', 'Tester')
    close_pending(app, task['code'], 'Tester', 'ok')
    _, err = close_pending(app, task['code'], 'Tester', 'otra vez')
    assert err and 'hecho' in err.lower()
    _, err2 = close_pending(app, 'OT-0001', 'Tester', None)
    assert err2 and 'PEND-' in err2


def test_bot_lista_vencidos_primero(app):
    from bot.actions.pending import create_pending, list_pending
    create_pending(app, 'tarea sin fecha para el listado', 'Tester')
    create_pending(app, 'tarea vencida del listado 30d', 'Tester')
    with app.app_context():
        from database import db
        from models import PendingTask
        t = PendingTask.query.filter(
            PendingTask.description.like('tarea vencida del listado%')).first()
        t.due_date = (date.today() - timedelta(days=5)).isoformat()
        db.session.commit()
    rows, total = list_pending(app, limit=50)
    assert total >= 2
    assert rows[0]['overdue_days'] is not None and rows[0]['overdue_days'] > 0


def test_bot_ordena_vencidos_luego_proximos_y_sin_fecha_al_final(app):
    """El orden de /pendientes: lo que ya vencio, lo que vence pronto, y al
    final lo que no tiene fecha."""
    from bot.actions.pending import create_pending, list_pending
    from database import db
    from models import PendingTask

    marcas = {}
    for txt in ('orden sin fecha', 'orden proximo', 'orden vencido'):
        t, _a, _e = create_pending(app, txt, 'Tester')
        marcas[txt] = t['id']
    with app.app_context():
        db.session.get(PendingTask, marcas['orden proximo']).due_date = (
            date.today() + timedelta(days=5)).isoformat()
        db.session.get(PendingTask, marcas['orden vencido']).due_date = (
            date.today() - timedelta(days=2)).isoformat()
        db.session.commit()

    rows, _total = list_pending(app, limit=100)
    pos = {r['id']: i for i, r in enumerate(rows)}
    assert pos[marcas['orden vencido']] < pos[marcas['orden proximo']]
    assert pos[marcas['orden proximo']] < pos[marcas['orden sin fecha']]
