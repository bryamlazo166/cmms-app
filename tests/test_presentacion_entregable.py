"""Tests del entregable: la presentacion mensual fuera del CMMS.

Es un libro de Excel que tiene que sostenerse solo cuando ya no haya sistema:
el historico cargado, las formulas de cada indicador y una lamina por grafico.
Lo que se prueba aqui es justamente eso — que los indicadores sean FORMULAS y
no valores pegados, que los rangos alcancen a los meses que se agreguen
despues, y que las columnas que el visor HTML busca por nombre esten donde
las espera.
"""
import io

import pytest
from openpyxl import load_workbook

from utils.presentacion_excel import (
    COL, FILA1, FILA_MAX, LAMINAS, MESES_FUTUROS,
    build_presentation_workbook, _con_futuros,
)


@pytest.fixture
def datos():
    """Historico minimo, con las magnitudes crudas de las que sale todo."""
    return {
        'meta': {'generado': '2026-09-06 10:00', 'desde': 'Julio 2026', 'hasta': 'Agosto 2026'},
        'meses': [('2026-07', 'Julio 2026'), ('2026-08', 'Agosto 2026')],
        'areas': ['COCCION', 'SECADO'],
        'filas': [
            # Dos lineas de COCCION: una parada larga y otra intacta. Es el caso
            # que obliga a ponderar en vez de sumar horas — sumadas darian 18,9%.
            {'mes': '2026-07', 'periodo': 'Julio 2026', 'area': 'COCCION',
             'linea': 'LINEA DIGESTOR #6', 'detiene_area': False, 'dias': 31,
             'tep': 744, 'capacidad': 20.2, 'paro_plan': 0.0, 'paro_no_plan': 530.0,
             'averias': 1, 'ots': 2},
            {'mes': '2026-07', 'periodo': 'Julio 2026', 'area': 'COCCION',
             'linea': 'LINEA DIGESTOR #7', 'detiene_area': False, 'dias': 31,
             'tep': 744, 'capacidad': 20.2, 'paro_plan': 12.0, 'paro_no_plan': 24.0,
             'averias': 3, 'ots': 7},
            {'mes': '2026-07', 'periodo': 'Julio 2026', 'area': 'SECADO',
             'linea': 'SECADOR #2', 'detiene_area': False, 'dias': 31,
             'tep': 744, 'capacidad': 144.0, 'paro_plan': 0.0, 'paro_no_plan': 30.0,
             'averias': 6, 'ots': 11},
            {'mes': '2026-08', 'periodo': 'Agosto 2026', 'area': 'COCCION',
             'linea': 'LINEA DIGESTOR #6', 'detiene_area': False, 'dias': 31,
             'tep': 744, 'capacidad': 20.2, 'paro_plan': 0.0, 'paro_no_plan': 18.4,
             'averias': 5, 'ots': 12},
            {'mes': '2026-08', 'periodo': 'Agosto 2026', 'area': 'SECADO',
             'linea': 'SECADOR #2', 'detiene_area': True, 'dias': 31,
             'tep': 744, 'capacidad': 144.0, 'paro_plan': 0.0, 'paro_no_plan': 56.7,
             'averias': 14, 'ots': 24},
        ],
        'cumplimiento': [
            {'periodo': 'Julio 2026', 'prev_plan': 600, 'prev_ejec': 300,
             'corr_plan': 80, 'corr_ejec': 70},
            {'periodo': 'Agosto 2026', 'prev_plan': 680, 'prev_ejec': 342,
             'corr_plan': 98, 'corr_ejec': 93},
        ],
        'ordenes': [
            {'code': 'OT-0429', 'fecha': '2026-08-09', 'mes': '2026-08', 'area': 'SECADO',
             'equipo': 'SECADOR 2', 'tipo': 'Correctivo', 'modo': 'ROTURA', 'paro': True,
             'horas': 17.93, 'planificado': False, 'descripcion': 'Cambio de chumacera'},
        ],
    }


@pytest.fixture
def libro(datos):
    return load_workbook(io.BytesIO(build_presentation_workbook(datos).read()))


def test_estructura_del_libro(libro):
    assert libro.sheetnames == ['LEEME', 'DATOS', '01 Disponibilidad', '02 MTBF',
                                '03 MTTR', '04 Confiabilidad', '05 Cumplimiento', 'ORDENES']


def test_los_datos_crudos_se_escriben_tal_cual(libro):
    ws = libro['DATOS']
    assert ws['A4'].value == '2026-07'
    assert ws['C4'].value == 'COCCION'
    assert ws['D4'].value == 'LINEA DIGESTOR #6'    # la fila es una LINEA
    assert ws['E4'].value == 'NO'                   # no detiene el area
    assert ws[f'{COL["TEP h"]}4'].value == 744
    assert ws[f'{COL["Paro no planificado h"]}4'].value == 530.0
    assert ws[f'{COL["Averias"]}4'].value == 1


def test_los_indicadores_son_formulas_no_valores(libro):
    """Lo que hace vivo al entregable: si fueran valores, pegar un mes nuevo
    no recalcularia nada."""
    ws = libro['DATOS']
    for col in ('Uptime h', 'Disp. operativa %', 'Disp. inherente %',
                'MTBF h', 'MTTR h', 'Confiabilidad %'):
        valor = ws[f'{COL[col]}4'].value
        assert isinstance(valor, str) and valor.startswith('='), f'{col} no es formula'


def test_las_formulas_usan_las_columnas_correctas(libro):
    ws = libro['DATOS']
    tep, pp, pn = COL['TEP h'], COL['Paro planificado h'], COL['Paro no planificado h']
    av, up, mtbf = COL['Averias'], COL['Uptime h'], COL['MTBF h']
    assert ws[f'{up}4'].value == f'=MAX(0,{tep}4-{pp}4-{pn}4)'
    assert ws[f'{COL["Disp. inherente %"]}4'].value == f'=IFERROR({up}4/({tep}4-{pp}4)*100,"")'
    assert ws[f'{COL["MTTR h"]}4'].value == f'=IFERROR(IF({av}4=0,0,{pn}4/{av}4),"")'
    # La confiabilidad se apoya en el MTBF ya calculado, no lo recalcula
    assert f'EXP(-168/{mtbf}4)' in ws[f'{COL["Confiabilidad %"]}4'].value


def test_division_por_cero_no_rompe_la_lamina(libro):
    """Un area sin averias es lo normal en un mes bueno: MTBF cae al tiempo
    disponible y la confiabilidad a 100, sin #DIV/0."""
    ws = libro['DATOS']
    av = COL['Averias']
    assert 'IFERROR' in ws[f'{COL["MTBF h"]}4'].value
    assert f'IF({av}4=0' in ws[f'{COL["MTBF h"]}4'].value
    assert f'IF({av}4=0,100' in ws[f'{COL["Confiabilidad %"]}4'].value


def test_las_laminas_leen_de_datos_y_alcanzan_meses_futuros(libro):
    ws = libro['01 Disponibilidad']
    formula = ws['B5'].value
    col = COL['Disp. inherente %']
    assert 'SUMPRODUCT' in formula                       # ponderado, no promedio
    assert f'DATOS!${col}${FILA1}:${col}${FILA_MAX}' in formula
    assert '"2026-07"' in formula and '"COCCION"' in formula


def test_la_planta_se_pondera_por_capacidad(libro):
    ws = libro['01 Disponibilidad']
    planta = ws.cell(row=5, column=4).value        # tras las 2 areas
    cap = COL['Capacidad TM/dia']
    assert 'SUMPRODUCT' in planta
    assert f'DATOS!${cap}${FILA1}:${cap}${FILA_MAX}' in planta
    # y si nadie cargo capacidades, promedio simple en vez de division por cero
    assert 'AVERAGEIFS' in planta


def test_cada_lamina_trae_meses_preparados_por_delante(libro):
    """Al cerrar el mes siguiente basta pegar la fila en DATOS: la lamina ya
    tiene su renglon esperando."""
    ws = libro['01 Disponibilidad']
    etiquetas = [ws.cell(row=5 + i, column=1).value for i in range(2 + MESES_FUTUROS)]
    assert etiquetas[:2] == ['Julio 2026', 'Agosto 2026']
    assert etiquetas[2] == 'Setiembre 2026'
    assert etiquetas[3] == 'Octubre 2026'
    assert etiquetas[-1] == 'Agosto 2027'          # 12 meses por delante
    # y la fila del mes que aun no llego ya trae su formula puesta
    futura = ws.cell(row=7, column=2).value
    assert futura.startswith('=IFERROR(') and '"2026-09"' in futura


def test_con_futuros_cruza_el_fin_de_anio():
    salida = _con_futuros([('2026-11', 'Noviembre 2026')])
    assert salida[1] == ('2026-12', 'Diciembre 2026')
    assert salida[2] == ('2027-01', 'Enero 2027')
    assert len(salida) == 1 + MESES_FUTUROS


def test_cada_lamina_tiene_su_grafico(libro):
    for titulo, _col, _fmt, _sub, _modo in LAMINAS:
        assert len(libro[titulo]._charts) == 1, f'{titulo} sin grafico'
    assert len(libro['05 Cumplimiento']._charts) == 1


def test_cumplimiento_calcula_los_porcentajes(libro):
    ws = libro['05 Cumplimiento']
    assert ws['B5'].value == 600 and ws['C5'].value == 300
    assert ws['D5'].value == '=IFERROR(C5/B5*100,"")'
    assert ws['G5'].value == '=IFERROR(F5/E5*100,"")'


def test_las_ordenes_quedan_como_respaldo(libro):
    ws = libro['ORDENES']
    assert ws['A4'].value == 'OT-0429'
    assert ws['I4'].value == 17.93
    assert ws['H4'].value == 'SI'          # causo paro
    assert ws['J4'].value == 'NO'          # no planificado


def test_los_encabezados_son_los_que_busca_el_visor_html(libro):
    """El HTML lee las columnas por NOMBRE. Si alguien las renombra aqui, el
    visor deja de encontrarlas: este test lo caza."""
    ws = libro['DATOS']
    encabezados = [ws.cell(row=3, column=c).value for c in range(1, 13)]
    assert encabezados == ['Mes', 'Periodo', 'Area', 'Linea', 'Detiene el area', 'Dias',
                           'TEP h', 'Capacidad TM/dia', 'Paro planificado h',
                           'Paro no planificado h', 'Averias', 'OT cerradas']
    cump = [libro['05 Cumplimiento'].cell(row=4, column=c).value for c in range(1, 8)]
    assert cump == ['Periodo', 'Prev. programado', 'Prev. ejecutado', 'Prev. %',
                    'Corr. programado', 'Corr. ejecutado', 'Corr. %']


def test_el_leeme_explica_las_formulas(libro):
    texto = ' '.join(str(c.value or '') for row in libro['LEEME'].iter_rows() for c in row)
    for esperado in ('TEP - paro planificado', 'uptime / averias', 'EXP(-168 / MTBF)',
                     'presentacion_indicadores.html', 'DATOS'):
        assert esperado in texto, f'el LEEME no explica: {esperado}'


def test_libro_vacio_no_revienta():
    """Una planta que recien arranca no tiene historico todavia."""
    wb = load_workbook(io.BytesIO(build_presentation_workbook({
        'meta': {}, 'meses': [], 'areas': [], 'filas': [],
        'cumplimiento': [], 'ordenes': [],
    }).read()))
    assert 'DATOS' in wb.sheetnames
    assert wb['DATOS'].max_row >= 3


# ── El endpoint ─────────────────────────────────────────────────────────────

def test_endpoint_descarga_el_libro(auth_admin):
    r = auth_admin.get('/api/presentacion/export-excel?month=2026-08&meses=2')
    assert r.status_code == 200
    assert 'spreadsheetml' in r.headers['Content-Type']
    assert 'Indicadores_Mantenimiento_2026-08.xlsx' in r.headers['Content-Disposition']
    wb = load_workbook(io.BytesIO(r.data))
    assert 'DATOS' in wb.sheetnames


def test_endpoint_json_trae_magnitudes_crudas(auth_admin):
    """El export NO manda disponibilidades ya calculadas: manda las horas y
    los eventos, que es lo que permite recalcular fuera del CMMS."""
    d = auth_admin.get('/api/presentacion/export-datos?month=2026-08&meses=2').get_json()
    assert set(d) == {'meta', 'meses', 'areas', 'filas', 'cumplimiento', 'ordenes'}
    if d['filas']:
        fila = d['filas'][0]
        assert set(fila) == {'mes', 'periodo', 'area', 'linea', 'detiene_area', 'dias',
                             'tep', 'capacidad', 'paro_plan', 'paro_no_plan',
                             'averias', 'ots'}
        assert 'disponibilidad' not in fila


def test_el_visor_html_existe_y_se_sirve(client):
    r = client.get('/static/presentacion_offline.html')
    assert r.status_code == 200
    html = r.data.decode('utf-8')
    assert 'DATOS' in html and 'xlsx' in html and 'echarts' in html


def test_una_linea_parada_no_hunde_el_area(libro):
    """El Digestor #6 estuvo 530 h fuera en julio, pero los otros digestores
    siguieron. Sumar sus horas daria 18,9% de disponibilidad para COCCION; el
    ponderado por capacidad da 87%, que es lo que muestra el CMMS y lo que
    realmente paso en planta."""
    ws = libro['01 Disponibilidad']
    formula = ws['B5'].value                       # julio, COCCION
    assert 'SUMPRODUCT' in formula
    assert COL['Capacidad TM/dia'] in formula      # pondera por capacidad
    # y no es una suma de horas disfrazada
    assert 'SUMIFS(DATOS!$' + COL['Paro no planificado h'] not in formula


def test_el_mttr_del_area_es_horas_entre_averias(libro):
    """Un promedio de MTTR de lineas no significa nada: el MTTR de un area es
    el total de horas de averia dividido entre el total de averias."""
    ws = libro['03 MTTR']
    formula = ws['B5'].value
    assert 'SUMIFS' in formula and 'SUMPRODUCT' not in formula
    assert COL['Paro no planificado h'] in formula
    assert COL['Averias'] in formula


def test_las_lineas_que_detienen_el_area_quedan_marcadas(libro):
    """El CMMS las compone en serie; el libro no puede, asi que al menos tienen
    que poder filtrarse."""
    ws = libro['DATOS']
    assert ws['E4'].value == 'NO'
    assert ws['E8'].value == 'SI'         # SECADOR #2 en agosto
