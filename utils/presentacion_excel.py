"""Presentacion mensual de indicadores en Excel, amarrada a sus datos.

Pensado como entregable: el libro se vale por si mismo, sin el CMMS. Trae el
historico ya cargado y, cada mes, quien quede solo pega una fila por area en
la hoja DATOS — los indicadores y las laminas se recalculan solos, porque
todo lo demas son formulas de Excel, no valores pegados.

Estructura del libro:

  LEEME              como se usa y que formula hay detras de cada indicador
  DATOS              la unica hoja que se escribe a mano (una fila por mes/area)
  01..04             una lamina por indicador: tabla mes x area + grafico
  05 Cumplimiento    preventivo y correctivo programado
  ORDENES            detalle de las OT cerradas del historico (auditoria)

Criterio de calculo (ISO 14224, el mismo del CMMS):

    uptime            = TEP - paro planificado - paro no planificado
    disp. operativa   = uptime / TEP
    disp. inherente   = uptime / (TEP - paro planificado)
    MTBF              = uptime / averias
    MTTR              = paro no planificado / averias
    confiabilidad     = EXP(-168 / MTBF)

La disponibilidad de PLANTA se pondera por capacidad de cada area
(SUMPRODUCT), que es como la calcula el CMMS entre lineas en paralelo.
"""

from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = '1F3864'
CYAN = '0A84FF'
GRIS = 'F2F6FC'
AMBAR = 'FFF3CD'

HEADER_FILL = PatternFill('solid', fgColor=NAVY)
HEADER_FONT = Font(color='FFFFFF', bold=True, size=10)
TITULO = Font(color=NAVY, bold=True, size=15)
SUBTITULO = Font(color='555555', size=10)
NEGRITA = Font(bold=True, size=10)
CALC_FILL = PatternFill('solid', fgColor=GRIS)          # columnas con formula
PEGAR_FILL = PatternFill('solid', fgColor=AMBAR)        # columnas que se pegan
BORDE = Border(*[Side(style='thin', color='D6DEE8')] * 4)

# Hoja DATOS: (encabezado, ancho, tipo). tipo 'pegar' = se escribe a mano.
COLUMNAS = [
    ('Mes',                     10, 'pegar'),
    ('Periodo',                 12, 'pegar'),
    ('Area',                    22, 'pegar'),
    ('Dias',                     7, 'pegar'),
    ('TEP h',                   10, 'pegar'),
    ('Capacidad TM/dia',        16, 'pegar'),
    ('Paro planificado h',      17, 'pegar'),
    ('Paro no planificado h',   19, 'pegar'),
    ('Averias',                  9, 'pegar'),
    ('OT cerradas',             12, 'pegar'),
    ('Uptime h',                11, 'calc'),
    ('Disp. operativa %',       16, 'calc'),
    ('Disp. inherente %',       16, 'calc'),
    ('MTBF h',                  10, 'calc'),
    ('MTTR h',                  10, 'calc'),
    ('Confiabilidad %',         15, 'calc'),
]
COL = {nombre: get_column_letter(i) for i, (nombre, _w, _t) in enumerate(COLUMNAS, start=1)}
FILA1 = 4                                    # primera fila de datos en DATOS
# Hasta donde miran las formulas de las laminas: deja sitio para ~40 anios de
# historico con varias areas, para que agregar meses no obligue a tocar rangos.
FILA_MAX = 2000
MESES_FUTUROS = 12                           # filas ya preparadas en cada lamina

# Laminas de indicadores: (titulo, columna origen en DATOS, formato, decimales)
LAMINAS = [
    ('01 Disponibilidad', 'Disp. inherente %', '0.0', 'Disponibilidad inherente (%)'),
    ('02 MTBF', 'MTBF h', '0.0', 'Tiempo medio entre fallas (h)'),
    ('03 MTTR', 'MTTR h', '0.00', 'Tiempo medio de reparacion (h)'),
    ('04 Confiabilidad', 'Confiabilidad %', '0.0', 'Confiabilidad a 168 h (%)'),
]


def _encabezado(ws, fila, textos, anchos=None, fill=HEADER_FILL):
    for c, texto in enumerate(textos, start=1):
        cell = ws.cell(row=fila, column=c, value=texto)
        cell.fill = fill
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = BORDE
    if anchos:
        for c, ancho in enumerate(anchos, start=1):
            ws.column_dimensions[get_column_letter(c)].width = ancho
    ws.row_dimensions[fila].height = 30


def _titulo(ws, texto, sub=None):
    ws['A1'] = texto
    ws['A1'].font = TITULO
    if sub:
        ws['A2'] = sub
        ws['A2'].font = SUBTITULO


# ── LEEME ───────────────────────────────────────────────────────────────────

def _hoja_leeme(wb, meta):
    ws = wb.active
    ws.title = 'LEEME'
    ws.column_dimensions['A'].width = 3
    ws.column_dimensions['B'].width = 118
    ws.sheet_view.showGridLines = False

    lineas = [
        ('t', 'Indicadores de Mantenimiento — presentacion mensual'),
        ('s', f"Generado desde el CMMS el {meta.get('generado', '')} · "
              f"historico {meta.get('desde', '')} a {meta.get('hasta', '')}"),
        ('b', ''),
        ('h', 'Como se usa cada mes'),
        ('p', '1. Abre la hoja DATOS. Cada fila es un mes y un area.'),
        ('p', '2. Copia debajo de la ultima fila una linea por cada area del mes que cierras, '
              'y llena SOLO las columnas ambar (Mes, Periodo, Area, Dias, TEP, Capacidad, '
              'Paro planificado, Paro no planificado, Averias, OT cerradas).'),
        ('p', '3. Arrastra hacia abajo las columnas grises (Uptime, Disponibilidad, MTBF, MTTR, '
              'Confiabilidad): son formulas y se calculan solas.'),
        ('p', '4. Las laminas 01 a 05 y sus graficos se actualizan solos. No se toca nada mas.'),
        ('b', ''),
        ('h', 'De donde sale cada dato de la hoja DATOS'),
        ('p', 'TEP h = dias del mes x 24. Es el tiempo calendario del periodo.'),
        ('p', 'Paro planificado h = horas de parada por mantenimiento programado (paradas de planta, '
              'preventivos que detuvieron el equipo).'),
        ('p', 'Paro no planificado h = horas que el area estuvo detenida por averia. Es la suma de las '
              'horas de las OT correctivas que declararon paro; si varias OT se hicieron en la MISMA '
              'parada, esa hora se cuenta UNA sola vez.'),
        ('p', 'Averias = cuantos eventos de paro no planificado hubo (no cuantas OT: una parada con '
              'cinco trabajos es UNA averia).'),
        ('p', 'Capacidad TM/dia = capacidad de produccion del area. Solo se usa para ponderar la '
              'planta; si no la tienes, deja 1 en todas y la planta sera el promedio simple.'),
        ('b', ''),
        ('h', 'Formulas (las mismas del CMMS, ISO 14224)'),
        ('p', 'Uptime          = TEP - paro planificado - paro no planificado'),
        ('p', 'Disp. operativa = uptime / TEP x 100                 -> lo que produccion tuvo disponible'),
        ('p', 'Disp. inherente = uptime / (TEP - paro planificado) x 100  -> salud del activo; el '
              'mantenimiento programado sale de la base, por eso es la que se presenta'),
        ('p', 'MTBF            = uptime / averias'),
        ('p', 'MTTR            = paro no planificado / averias'),
        ('p', 'Confiabilidad   = EXP(-168 / MTBF) x 100             -> probabilidad de operar una '
              'semana sin fallar'),
        ('b', ''),
        ('h', 'Una diferencia que conviene saber'),
        ('p', 'El CMMS calcula la disponibilidad del area ponderando por capacidad las lineas que van '
              'en paralelo y componiendo en serie las que detienen toda el area. Este libro usa la '
              'formula directa sobre las horas del area, que es la que se puede sostener a mano. '
              'Los numeros quedan muy proximos, pero pueden no ser identicos al decimal.'),
        ('b', ''),
        ('h', 'Que hay en cada hoja'),
        ('p', 'DATOS            unica hoja que se escribe. Ambar = se pega; gris = formula.'),
        ('p', '01 a 04          una lamina por indicador: tabla mes x area y su grafico.'),
        ('p', '05 Cumplimiento  preventivo y correctivo programado del mes.'),
        ('p', 'ORDENES          detalle de las OT cerradas del historico, para auditar cualquier cifra.'),
        ('b', ''),
        ('h', 'Version en navegador'),
        ('p', 'El archivo presentacion_indicadores.html abre este mismo libro y muestra las laminas a '
              'pantalla completa para proyectar. Se abre con doble click, elige el .xlsx y listo.'),
    ]
    fila = 2
    for tipo, texto in lineas:
        c = ws.cell(row=fila, column=2, value=texto)
        if tipo == 't':
            c.font = TITULO
        elif tipo == 's':
            c.font = SUBTITULO
        elif tipo == 'h':
            c.font = Font(color=NAVY, bold=True, size=11)
        else:
            c.font = Font(size=10)
            c.alignment = Alignment(wrap_text=True, vertical='top')
            ws.row_dimensions[fila].height = 15 if len(texto) < 100 else 30
        fila += 1
    return ws


# ── DATOS ───────────────────────────────────────────────────────────────────

def _hoja_datos(wb, filas):
    ws = wb.create_sheet('DATOS')
    _titulo(ws, 'DATOS — la unica hoja que se escribe a mano',
            'Ambar: se pega cada mes.  Gris: formula, no se toca.')
    _encabezado(ws, 3, [n for n, _w, _t in COLUMNAS], [w for _n, w, _t in COLUMNAS])
    for c, (_n, _w, tipo) in enumerate(COLUMNAS, start=1):
        ws.cell(row=3, column=c).fill = HEADER_FILL

    for i, f in enumerate(filas):
        r = FILA1 + i
        valores = [f['mes'], f['periodo'], f['area'], f['dias'], f['tep'],
                   f['capacidad'], f['paro_plan'], f['paro_no_plan'],
                   f['averias'], f['ots']]
        for c, v in enumerate(valores, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.fill = PEGAR_FILL
            cell.border = BORDE
            if c >= 4:
                cell.number_format = '0.0' if c in (5, 6, 7, 8) else '0'
        _formulas_fila(ws, r)

    ws.freeze_panes = 'D4'
    ws.auto_filter.ref = f"A3:{COL['Confiabilidad %']}{max(FILA1, FILA1 + len(filas) - 1)}"
    return ws


def _formulas_fila(ws, r):
    """Las columnas calculadas de una fila de DATOS."""
    tep, pp, pn, av = COL['TEP h'], COL['Paro planificado h'], COL['Paro no planificado h'], COL['Averias']
    up, mtbf = COL['Uptime h'], COL['MTBF h']
    formulas = {
        'Uptime h':        f'=MAX(0,{tep}{r}-{pp}{r}-{pn}{r})',
        'Disp. operativa %': f'=IFERROR({up}{r}/{tep}{r}*100,"")',
        'Disp. inherente %': f'=IFERROR({up}{r}/({tep}{r}-{pp}{r})*100,"")',
        'MTBF h':          f'=IFERROR(IF({av}{r}=0,{tep}{r}-{pp}{r},{up}{r}/{av}{r}),"")',
        'MTTR h':          f'=IFERROR(IF({av}{r}=0,0,{pn}{r}/{av}{r}),"")',
        'Confiabilidad %': f'=IFERROR(IF({av}{r}=0,100,EXP(-168/{mtbf}{r})*100),"")',
    }
    formatos = {'Uptime h': '0.0', 'Disp. operativa %': '0.0', 'Disp. inherente %': '0.0',
                'MTBF h': '0.0', 'MTTR h': '0.00', 'Confiabilidad %': '0.0'}
    for nombre, formula in formulas.items():
        cell = ws[f'{COL[nombre]}{r}']
        cell.value = formula
        cell.fill = CALC_FILL
        cell.border = BORDE
        cell.number_format = formatos[nombre]


# ── Laminas de indicador ────────────────────────────────────────────────────

def _con_futuros(meses):
    """El historico mas MESES_FUTUROS periodos por delante, ya preparados.

    Asi, cuando se cierre el mes que viene, basta pegar la fila en DATOS: la
    lamina y el grafico ya tienen su sitio esperando.
    """
    salida = list(meses)
    if not salida:
        return salida
    y, m = int(salida[-1][0][:4]), int(salida[-1][0][5:7])
    for _ in range(MESES_FUTUROS):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        salida.append((f'{y}-{m:02d}', f'{MES_NOMBRE[m]} {y}'))
    return salida


MES_NOMBRE = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
              7: 'Julio', 8: 'Agosto', 9: 'Setiembre', 10: 'Octubre', 11: 'Noviembre',
              12: 'Diciembre'}


def _hoja_indicador(wb, titulo, columna, formato, subtitulo, meses, areas, n_filas):
    """Tabla mes x area con AVERAGEIFS sobre DATOS, mas el grafico.

    Los rangos llegan hasta FILA_MAX y la tabla trae 12 meses por delante ya
    preparados: al pegar el mes que cierra en DATOS, la lamina y su grafico se
    llenan solos, sin tocar formulas ni rangos.
    """
    ws = wb.create_sheet(titulo)
    _titulo(ws, f'{titulo[3:]} — mensual por area', subtitulo)
    ws.sheet_view.showGridLines = False

    col_area = f"DATOS!$C${FILA1}:$C${FILA_MAX}"
    col_val = f"DATOS!${COL[columna]}${FILA1}:${COL[columna]}${FILA_MAX}"
    col_mes = f"DATOS!$A${FILA1}:$A${FILA_MAX}"

    cabecera = ['Periodo'] + areas + ['PLANTA (ponderado)']
    _encabezado(ws, 4, cabecera, [16] + [15] * (len(areas) + 1))

    cap = f"DATOS!${COL['Capacidad TM/dia']}${FILA1}:${COL['Capacidad TM/dia']}${FILA_MAX}"
    for i, (mes, etiqueta) in enumerate(_con_futuros(meses)):
        r = 5 + i
        futuro = i >= len(meses)
        celda_mes = ws.cell(row=r, column=1, value=etiqueta)
        celda_mes.font = SUBTITULO if futuro else NEGRITA
        celda_mes.border = BORDE
        for j, area in enumerate(areas):
            cell = ws.cell(row=r, column=2 + j)
            cell.value = (f'=IFERROR(AVERAGEIFS({col_val},{col_mes},"{mes}",'
                          f'{col_area},"{area}"),"")')
            cell.number_format = formato
            cell.border = BORDE
        # Planta: promedio ponderado por capacidad, como el CMMS entre lineas.
        # Si no hay capacidades cargadas cae al promedio simple.
        planta = ws.cell(row=r, column=2 + len(areas))
        planta.value = (
            f'=IFERROR(IF(SUMIFS({cap},{col_mes},"{mes}")=0,'
            f'AVERAGEIFS({col_val},{col_mes},"{mes}"),'
            f'SUMPRODUCT(({col_mes}="{mes}")*{col_val}*{cap})'
            f'/SUMPRODUCT(({col_mes}="{mes}")*{cap})),"")')
        planta.number_format = formato
        planta.font = NEGRITA
        planta.border = BORDE

    ws.freeze_panes = 'B5'
    ws.cell(row=5 + len(meses) + MESES_FUTUROS + 1, column=1,
            value='Los periodos en gris todavia no tienen datos: se llenan solos '
                  'al pegar el mes en la hoja DATOS.').font = SUBTITULO
    _grafico_lineas(ws, titulo[3:], subtitulo, len(meses) + MESES_FUTUROS, len(areas) + 1)
    return ws


def _grafico_lineas(ws, titulo, eje_y, n_meses, n_series, ancla='B{}'):
    ch = LineChart()
    ch.title = titulo
    ch.y_axis.title = eje_y
    ch.x_axis.title = 'Periodo'
    ch.height, ch.width = 11, 30
    ch.style = 2
    datos = Reference(ws, min_col=2, max_col=1 + n_series, min_row=4, max_row=4 + max(n_meses, 1))
    cats = Reference(ws, min_col=1, min_row=5, max_row=4 + max(n_meses, 1))
    ch.add_data(datos, titles_from_data=True)
    ch.set_categories(cats)
    for s in ch.series:
        s.smooth = False
    ws.add_chart(ch, ancla.format(7 + max(n_meses, 1)))


# ── Cumplimiento ────────────────────────────────────────────────────────────

def _hoja_cumplimiento(wb, cumplimiento):
    ws = wb.create_sheet('05 Cumplimiento')
    _titulo(ws, 'Cumplimiento del programa — mensual (planta)',
            'Preventivo: lo que el programa exigia vs lo ejecutado. '
            'Correctivo programado: OT correctivas planificadas vs cerradas.')
    ws.sheet_view.showGridLines = False
    cab = ['Periodo', 'Prev. programado', 'Prev. ejecutado', 'Prev. %',
           'Corr. programado', 'Corr. ejecutado', 'Corr. %']
    _encabezado(ws, 4, cab, [14, 17, 16, 11, 17, 16, 11])

    for i, c in enumerate(cumplimiento):
        r = 5 + i
        ws.cell(row=r, column=1, value=c['periodo']).font = NEGRITA
        for col, key in ((2, 'prev_plan'), (3, 'prev_ejec'), (5, 'corr_plan'), (6, 'corr_ejec')):
            cell = ws.cell(row=r, column=col, value=c[key])
            cell.number_format = '0.0'
            cell.fill = PEGAR_FILL
            cell.border = BORDE
        for col, (a, b) in ((4, ('B', 'C')), (7, ('E', 'F'))):
            cell = ws.cell(row=r, column=col, value=f'=IFERROR({b}{r}/{a}{r}*100,"")')
            cell.number_format = '0.0'
            cell.fill = CALC_FILL
            cell.border = BORDE

    n = len(cumplimiento)
    ch = BarChart()
    ch.type, ch.style = 'col', 10
    ch.title = 'Cumplimiento del programa (%)'
    ch.y_axis.title = '%'
    ch.x_axis.title = 'Periodo'
    ch.height, ch.width = 11, 30
    datos = Reference(ws, min_col=4, max_col=4, min_row=4, max_row=4 + max(n, 1))
    datos2 = Reference(ws, min_col=7, max_col=7, min_row=4, max_row=4 + max(n, 1))
    ch.add_data(datos, titles_from_data=True)
    ch.add_data(datos2, titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + max(n, 1)))
    ws.add_chart(ch, f'B{7 + max(n, 1)}')
    return ws


# ── Ordenes (auditoria) ─────────────────────────────────────────────────────

def _hoja_ordenes(wb, ordenes):
    ws = wb.create_sheet('ORDENES')
    _titulo(ws, 'Ordenes cerradas del historico',
            'El respaldo de cada cifra: de aqui salen las horas de paro y las averias.')
    cab = ['Codigo', 'Fecha cierre', 'Mes', 'Area', 'Equipo', 'Tipo', 'Modo de falla',
           'Causo paro', 'Horas de paro', 'Paro planificado', 'Descripcion']
    _encabezado(ws, 3, cab, [11, 13, 10, 20, 26, 14, 18, 11, 13, 16, 60])
    for i, o in enumerate(ordenes):
        r = 4 + i
        vals = [o['code'], o['fecha'], o['mes'], o['area'], o['equipo'], o['tipo'],
                o['modo'], 'SI' if o['paro'] else 'NO', o['horas'],
                'SI' if o['planificado'] else 'NO', o['descripcion']]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = BORDE
            if c == 9:
                cell.number_format = '0.00'
            if i % 2:
                cell.fill = PatternFill('solid', fgColor=GRIS)
    ws.freeze_panes = 'A4'
    if ordenes:
        ws.auto_filter.ref = f'A3:K{3 + len(ordenes)}'
    return ws


# ── Ensamblado ──────────────────────────────────────────────────────────────

def build_presentation_workbook(datos):
    """Arma el libro. `datos` viene de presentacion_routes._export_historico()."""
    wb = Workbook()
    _hoja_leeme(wb, datos.get('meta', {}))
    filas = datos.get('filas', [])
    _hoja_datos(wb, filas)

    meses = datos.get('meses', [])
    areas = datos.get('areas', [])
    for titulo, columna, formato, sub in LAMINAS:
        _hoja_indicador(wb, titulo, columna, formato, sub, meses, areas, len(filas))

    _hoja_cumplimiento(wb, datos.get('cumplimiento', []))
    _hoja_ordenes(wb, datos.get('ordenes', []))

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio
