"""Helpers para generar PDFs del CMMS usando ReportLab.

Hoja de coordinacion diaria: tabla con OTs activas + Avisos pendientes
para imprimir y revisar con el supervisor.
"""
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
)


# Estilos compartidos
_styles = getSampleStyleSheet()
_cell_style = ParagraphStyle(
    'cell', parent=_styles['Normal'],
    fontName='Helvetica', fontSize=8, leading=10, wordWrap='CJK'
)
_cell_bold = ParagraphStyle(
    'cellb', parent=_cell_style, fontName='Helvetica-Bold'
)
_title_style = ParagraphStyle(
    'title', parent=_styles['Title'],
    fontName='Helvetica-Bold', fontSize=14, alignment=0, spaceAfter=6
)
_section_style = ParagraphStyle(
    'section', parent=_styles['Heading2'],
    fontName='Helvetica-Bold', fontSize=11,
    textColor=colors.HexColor('#0A84FF'), spaceBefore=10, spaceAfter=4
)
_meta_style = ParagraphStyle(
    'meta', parent=_styles['Normal'],
    fontName='Helvetica', fontSize=8, textColor=colors.grey
)


def _p(txt, style=None):
    """Crea Paragraph escapando HTML basico."""
    s = '' if txt is None else str(txt)
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return Paragraph(s, style or _cell_style)


def _criticality_color(crit):
    c = (crit or '').lower()
    if c in ('alta', 'emergencia', 'critica'):
        return colors.HexColor('#FFEEEE')
    if c == 'media':
        return colors.HexColor('#FFF7E6')
    return colors.HexColor('#F0F8FF')


def _status_color(status):
    s = (status or '').lower()
    if s == 'en progreso':
        return colors.HexColor('#FFF3E0')
    if s == 'programada':
        return colors.HexColor('#E8F5E9')
    if s in ('cerrada', 'cerrado'):
        return colors.HexColor('#EEEEEE')
    return colors.HexColor('#FFFFFF')


def build_ots_table(ots):
    """ots: lista de dicts con campos: code, equipment_name, equipment_tag, area_name,
       component_name, maintenance_type, status, priority, criticality,
       scheduled_date, technician_name, description"""
    headers = ['#', 'Codigo', 'Equipo', 'Componente', 'Area', 'Tipo', 'Estado',
               'Prio', 'Fecha Prog', 'Tecnico', 'Descripcion']
    data = [[_p(h, _cell_bold) for h in headers]]

    for i, ot in enumerate(ots, 1):
        equip = f"[{ot.get('equipment_tag') or '-'}] {ot.get('equipment_name') or '-'}"
        row = [
            _p(str(i)),
            _p(ot.get('code') or '-', _cell_bold),
            _p(equip),
            _p(ot.get('component_name') or '-'),
            _p(ot.get('area_name') or '-'),
            _p(ot.get('maintenance_type') or '-'),
            _p(ot.get('status') or '-'),
            _p(ot.get('priority') or '-'),
            _p(ot.get('scheduled_date') or '-'),
            _p(ot.get('technician_name') or ot.get('provider_name') or '-'),
            _p(ot.get('description') or '-'),
        ]
        data.append(row)

    # Anchos en mm: total ~277 (A4 landscape sin margenes ~277mm)
    col_widths = [8*mm, 18*mm, 35*mm, 25*mm, 20*mm, 16*mm, 16*mm,
                  10*mm, 16*mm, 25*mm, 88*mm]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0A84FF')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ])
    # Color de fila por estado
    for idx, ot in enumerate(ots, 1):
        bg = _status_color(ot.get('status'))
        style.add('BACKGROUND', (0, idx), (-1, idx), bg)
    table.setStyle(style)
    return table


def build_notices_table(notices):
    """notices: lista de dicts con campos: code, equipment_name, equipment_tag, area_name,
       component_name, failure_mode, criticality, priority, status,
       created_date, reporter, description, blockage_object"""
    headers = ['#', 'Codigo', 'Equipo', 'Componente', 'Area', 'Modo Falla',
               'Bloqueo', 'Crit', 'Estado', 'Fecha', 'Reportado', 'Descripcion']
    data = [[_p(h, _cell_bold) for h in headers]]

    for i, n in enumerate(notices, 1):
        equip = f"[{n.get('equipment_tag') or '-'}] {n.get('equipment_name') or '-'}"
        row = [
            _p(str(i)),
            _p(n.get('code') or n.get('id_str') or '-', _cell_bold),
            _p(equip),
            _p(n.get('component_name') or '-'),
            _p(n.get('area_name') or '-'),
            _p(n.get('failure_mode') or '-'),
            _p(n.get('blockage_object') or '-'),
            _p(n.get('criticality') or '-'),
            _p(n.get('status') or '-'),
            _p(n.get('created_date') or '-'),
            _p(n.get('reporter') or '-'),
            _p(n.get('description') or '-'),
        ]
        data.append(row)

    col_widths = [8*mm, 18*mm, 35*mm, 22*mm, 20*mm, 22*mm, 16*mm,
                  12*mm, 16*mm, 16*mm, 22*mm, 70*mm]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9F0A')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ])
    for idx, n in enumerate(notices, 1):
        bg = _criticality_color(n.get('criticality'))
        style.add('BACKGROUND', (0, idx), (-1, idx), bg)
    table.setStyle(style)
    return table


def _make_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(
        doc.pagesize[0] - 10*mm, 8*mm,
        f"Pagina {doc.page}  —  Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    canvas.drawString(10*mm, 8*mm, "CMMS Industrial — Hoja de Coordinacion Diaria")
    canvas.restoreState()


def generate_daily_coordination_pdf(ots, notices, title='Hoja de Coordinacion Diaria',
                                    subtitle=None):
    """Genera el PDF y devuelve un BytesIO listo para enviar."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=10*mm, bottomMargin=15*mm,
        title=title,
    )
    elements = []

    elements.append(_p(title, _title_style))
    meta_lines = [
        f"Fecha de impresion: <b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</b>",
        f"Total OTs activas: <b>{len(ots)}</b> | Total Avisos pendientes: <b>{len(notices)}</b>",
    ]
    if subtitle:
        meta_lines.insert(0, subtitle)
    for ml in meta_lines:
        elements.append(Paragraph(ml, _meta_style))
    elements.append(Spacer(1, 4*mm))

    # Seccion OTs
    elements.append(Paragraph(f"ORDENES DE TRABAJO ACTIVAS ({len(ots)})", _section_style))
    if ots:
        elements.append(build_ots_table(ots))
    else:
        elements.append(_p("Sin OTs activas en el filtro actual.", _meta_style))

    elements.append(Spacer(1, 6*mm))

    # Seccion Avisos
    elements.append(Paragraph(f"AVISOS PENDIENTES ({len(notices)})", _section_style))
    if notices:
        elements.append(build_notices_table(notices))
    else:
        elements.append(_p("Sin avisos pendientes en el filtro actual.", _meta_style))

    # Espacio para firmas/notas
    elements.append(Spacer(1, 8*mm))
    elements.append(_p("_________________________            _________________________", _meta_style))
    elements.append(_p("Tecnico                                                                 Supervisor", _meta_style))

    doc.build(elements, onFirstPage=_make_footer, onLaterPages=_make_footer)
    buf.seek(0)
    return buf
