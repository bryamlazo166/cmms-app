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


def _esc(value):
    """Escapa <, >, & en strings para uso seguro dentro de un Paragraph
    cuando se va a interpolar en HTML controlado por nosotros."""
    s = '' if value is None else str(value)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _equip_paragraph(tag, name, style=None):
    """Devuelve un Paragraph con '[TAG]' en negrita en la primera linea
    y el nombre del equipo abajo. Escapa los valores de usuario pero
    mantiene los tags de formato (<b>, <br/>)."""
    safe_tag = _esc(tag) if tag else '-'
    safe_name = _esc(name) if name else '-'
    html = f"<b>[{safe_tag}]</b><br/>{safe_name}"
    return Paragraph(html, style or _cell_style)


def _short_date(value):
    """Convierte una fecha (str ISO YYYY-MM-DD o datetime/date) a 'DD-mmm'
    en español. Ej: 2026-04-15 -> '15-abr'. Si no se puede parsear,
    devuelve el valor original o '-'."""
    if not value:
        return '-'
    months_es = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
    try:
        if hasattr(value, 'month') and hasattr(value, 'day'):
            d = value
        else:
            s = str(value)[:10]  # YYYY-MM-DD
            from datetime import date as _date
            parts = s.split('-')
            d = _date(int(parts[0]), int(parts[1]), int(parts[2]))
        return f"{d.day:02d}-{months_es[d.month - 1]}"
    except Exception:
        return str(value)


def _short_tech_name(name):
    """Devuelve 'Primer-nombre Primer-apellido' a partir de un nombre
    completo. Si recibe None o '-', devuelve '-'."""
    if not name or name == '-':
        return '-'
    parts = str(name).strip().split()
    if len(parts) <= 2:
        return ' '.join(parts)
    # 'Carlos Andres Luque Ccolque' -> 'Carlos Luque'
    return f"{parts[0]} {parts[2] if len(parts) >= 3 else parts[1]}"


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


_SPECIALTY_BADGE = {
    'MECANICO': ('MEC', colors.HexColor('#0A84FF')),
    'ELECTRICO': ('ELE', colors.HexColor('#FF9F0A')),
    'MIXTO': ('MIX', colors.HexColor('#AF52DE')),
    'SIN CLASIF': ('S/C', colors.HexColor('#8E8E93')),
    'SIN ASIGNAR': ('S/C', colors.HexColor('#8E8E93')),
}


def _spec_paragraph(spec):
    label, color = _SPECIALTY_BADGE.get((spec or '').upper(), ('-', colors.grey))
    style = ParagraphStyle('spec', parent=_cell_bold, textColor=color, alignment=1)
    return Paragraph(label, style)


def build_ots_table(ots):
    """ots: lista de dicts con campos: code, equipment_name, equipment_tag,
       area_name, line_name, system_name, component_name, maintenance_type,
       status, priority, criticality, scheduled_date, technician_name,
       description, specialty"""
    headers = ['#', 'Codigo', 'Esp.', 'Area', 'Linea', 'Equipo', 'Sistema',
               'Componente', 'Tipo', 'Estado', 'Fecha Prog', 'Descripcion']
    data = [[_p(h, _cell_bold) for h in headers]]

    for i, ot in enumerate(ots, 1):
        # Equipo en 2 lineas: [TAG] arriba, nombre del equipo abajo.
        row = [
            _p(str(i)),
            _p(ot.get('code') or '-', _cell_bold),
            _spec_paragraph(ot.get('specialty')),
            _p(ot.get('area_name') or '-'),
            _p(ot.get('line_name') or '-'),
            _equip_paragraph(ot.get('equipment_tag'), ot.get('equipment_name')),
            _p(ot.get('system_name') or '-'),
            _p(ot.get('component_name') or '-'),
            _p(ot.get('maintenance_type') or '-'),
            _p(ot.get('status') or '-'),
            _p(_short_date(ot.get('scheduled_date'))),
            _p(ot.get('description') or '-'),
        ]
        data.append(row)

    # Anchos en mm: total ~277 (A4 landscape sin margenes ~277mm)
    # # Codigo Esp Area Linea Equipo Sistema Componente Tipo Estado Fecha Desc
    col_widths = [7*mm, 17*mm, 10*mm, 22*mm, 20*mm, 28*mm, 22*mm, 24*mm,
                  14*mm, 14*mm, 13*mm, 86*mm]

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
    """notices: lista de dicts con campos: code, equipment_name, equipment_tag,
       area_name, line_name, system_name, component_name, failure_mode,
       criticality, priority, status, created_date, reporter, description,
       blockage_object, specialty"""
    headers = ['#', 'Codigo', 'Esp.', 'Area', 'Linea', 'Equipo', 'Sistema',
               'Componente', 'Modo Falla', 'Crit', 'Estado', 'Fecha', 'Descripcion']
    data = [[_p(h, _cell_bold) for h in headers]]

    for i, n in enumerate(notices, 1):
        row = [
            _p(str(i)),
            _p(n.get('code') or n.get('id_str') or '-', _cell_bold),
            _spec_paragraph(n.get('specialty')),
            _p(n.get('area_name') or '-'),
            _p(n.get('line_name') or '-'),
            _equip_paragraph(n.get('equipment_tag'), n.get('equipment_name')),
            _p(n.get('system_name') or '-'),
            _p(n.get('component_name') or '-'),
            _p(n.get('failure_mode') or '-'),
            _p(n.get('criticality') or '-'),
            _p(n.get('status') or '-'),
            _p(_short_date(n.get('created_date'))),
            _p(n.get('description') or '-'),
        ]
        data.append(row)

    # # Codigo Esp Area Linea Equipo Sistema Componente Modo Crit Estado Fecha Desc
    col_widths = [7*mm, 17*mm, 10*mm, 22*mm, 20*mm, 28*mm, 22*mm, 24*mm,
                  21*mm, 11*mm, 15*mm, 13*mm, 67*mm]

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


def _is_unclassified(spec):
    return (spec or '').upper().strip() in ('', 'SIN CLASIF', 'SIN ASIGNAR', 'SIN_CLASIF')


# ── Sorting helpers para el layout agrupado por area ──────────────────────────

def _natural_key(s):
    """Sort natural: 'TH2' < 'TH10' en lugar de 'TH10' < 'TH2'."""
    import re as _re
    return [int(t) if t.isdigit() else (t or '').lower()
            for t in _re.split(r'(\d+)', str(s or ''))]


def _ot_status_rank(status):
    s = (status or '').lower()
    return {'en progreso': 0, 'programada': 1, 'abierta': 2}.get(s, 3)


def _crit_rank(crit):
    c = (crit or '').lower()
    return {'alta': 0, 'emergencia': 0, 'critica': 0, 'media': 1, 'baja': 2}.get(c, 3)


def _is_urgent_ot(ot):
    """OT urgente = En Progreso (lo que se trabaja HOY)."""
    return (ot.get('status') or '').lower() == 'en progreso'


def _is_urgent_notice(n):
    """Aviso urgente = criticidad Alta."""
    return _crit_rank(n.get('criticality')) == 0


def _sort_ots(items):
    return sorted(items, key=lambda o: (
        _ot_status_rank(o.get('status')),
        _natural_key(o.get('line_name')),
        _natural_key(o.get('equipment_tag') or o.get('equipment_name')),
        _natural_key(o.get('system_name')),
        _natural_key(o.get('component_name')),
        str(o.get('code') or ''),
    ))


def _sort_notices(items):
    return sorted(items, key=lambda n: (
        _crit_rank(n.get('criticality')),
        _natural_key(n.get('line_name')),
        _natural_key(n.get('equipment_tag') or n.get('equipment_name')),
        _natural_key(n.get('system_name')),
        _natural_key(n.get('component_name')),
        str(n.get('code') or ''),
    ))


def _group_by_area(ots, notices):
    """Agrupa OTs y Avisos por area_name. Devuelve lista de tuplas
    (area_name, process_order, ots_de_area, notices_de_area) ordenadas por
    process_order asc (NULL al final) y luego por nombre.
    """
    groups = {}
    for it in ots:
        key = it.get('area_name') or '(SIN AREA)'
        slot = groups.setdefault(key, {'po': it.get('area_process_order'), 'ots': [], 'notices': []})
        slot['ots'].append(it)
        if slot['po'] is None and it.get('area_process_order') is not None:
            slot['po'] = it.get('area_process_order')
    for it in notices:
        key = it.get('area_name') or '(SIN AREA)'
        slot = groups.setdefault(key, {'po': it.get('area_process_order'), 'ots': [], 'notices': []})
        slot['notices'].append(it)
        if slot['po'] is None and it.get('area_process_order') is not None:
            slot['po'] = it.get('area_process_order')
    # Orden: process_order asc (None al final), luego nombre alfabetico
    return sorted(
        ((name, d['po'], _sort_ots(d['ots']), _sort_notices(d['notices']))
         for name, d in groups.items()),
        key=lambda x: (x[1] is None, x[1] if x[1] is not None else 0, x[0])
    )


def _area_band(area_name, n_ots, n_notices, color_hex='#0A84FF'):
    """Banda de seccion de area con subtotal en una sola fila estilizada."""
    style = ParagraphStyle(
        'area_band', parent=_styles['Heading3'],
        fontName='Helvetica-Bold', fontSize=11,
        textColor=colors.white, backColor=colors.HexColor(color_hex),
        leftIndent=4, rightIndent=4, spaceBefore=8, spaceAfter=2,
        borderPadding=(4, 6, 4, 6),
    )
    return Paragraph(
        f"&nbsp;&nbsp;{_esc(area_name)} &nbsp;&middot;&nbsp; "
        f"{n_ots} OT{'s' if n_ots != 1 else ''}, "
        f"{n_notices} aviso{'s' if n_notices != 1 else ''}",
        style,
    )


def _urgent_band(n_ots, n_notices):
    style = ParagraphStyle(
        'urgent_band', parent=_styles['Heading2'],
        fontName='Helvetica-Bold', fontSize=12,
        textColor=colors.white, backColor=colors.HexColor('#FF453A'),
        leftIndent=4, rightIndent=4, spaceBefore=4, spaceAfter=4,
        borderPadding=(5, 6, 5, 6),
    )
    return Paragraph(
        f"&nbsp;&nbsp;EN EJECUCION HOY &middot; {n_ots} OT(s) En Progreso "
        f"+ {n_notices} aviso(s) de Alta criticidad",
        style,
    )


def generate_daily_coordination_pdf(ots, notices, title='Hoja de Coordinacion Diaria',
                                    subtitle=None, specialty_filter=None):
    """Genera el PDF y devuelve un BytesIO listo para enviar.

    Si `specialty_filter` se provee ('MECANICO' / 'ELECTRICO'), las secciones
    principales muestran solo items de esa especialidad (MIXTO entra en ambas).
    Los items SIN CLASIF se listan al final en una seccion separada con un
    aviso para forzar su clasificacion.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=10*mm, bottomMargin=15*mm,
        title=title,
    )
    elements = []

    # Particionar por especialidad
    wanted = (specialty_filter or '').upper().strip().replace('_', ' ') or None

    def _spec_match(spec):
        if not wanted:
            return True
        s = (spec or '').upper().strip()
        if s == wanted:
            return True
        if s == 'MIXTO' and wanted in ('MECANICO', 'ELECTRICO'):
            return True
        return False

    ots_in = [o for o in ots if _spec_match(o.get('specialty')) and not _is_unclassified(o.get('specialty'))]
    notices_in = [n for n in notices if _spec_match(n.get('specialty')) and not _is_unclassified(n.get('specialty'))]
    ots_uncls = [o for o in ots if _is_unclassified(o.get('specialty'))]
    notices_uncls = [n for n in notices if _is_unclassified(n.get('specialty'))]

    # Particionar en URGENTE (En Progreso + Alta criticidad) vs el RESTO
    urgent_ots = [o for o in ots_in if _is_urgent_ot(o)]
    urgent_notices = [n for n in notices_in if _is_urgent_notice(n)]
    rest_ots = [o for o in ots_in if not _is_urgent_ot(o)]
    rest_notices = [n for n in notices_in if not _is_urgent_notice(n)]

    elements.append(_p(title, _title_style))
    meta_lines = [
        f"Fecha de impresion: <b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</b>",
        f"OTs en seccion: <b>{len(ots_in)}</b> | Avisos en seccion: <b>{len(notices_in)}</b>"
        + (f" | Sin clasificar: <b>{len(ots_uncls) + len(notices_uncls)}</b>" if (ots_uncls or notices_uncls) else ''),
    ]
    if subtitle:
        meta_lines.insert(0, subtitle)
    for ml in meta_lines:
        elements.append(Paragraph(ml, _meta_style))
    elements.append(Spacer(1, 4*mm))

    # ── SECCION 1: EN EJECUCION HOY (urgentes) ────────────────────────────────
    if urgent_ots or urgent_notices:
        elements.append(_urgent_band(len(urgent_ots), len(urgent_notices)))
        if urgent_ots:
            elements.append(_p(f"OTs En Progreso ({len(urgent_ots)})", _section_style))
            elements.append(build_ots_table(_sort_ots(urgent_ots)))
            elements.append(Spacer(1, 3*mm))
        if urgent_notices:
            elements.append(_p(f"Avisos Alta criticidad ({len(urgent_notices)})", _section_style))
            elements.append(build_notices_table(_sort_notices(urgent_notices)))
        elements.append(Spacer(1, 6*mm))

    # ── SECCION 2: AGRUPADO POR AREA (orden de proceso) ───────────────────────
    if rest_ots or rest_notices:
        elements.append(_p("Resto por area (orden de proceso de planta)", _section_style))
        groups = _group_by_area(rest_ots, rest_notices)
        for area_name, _po, area_ots, area_notices in groups:
            elements.append(_area_band(area_name, len(area_ots), len(area_notices)))
            if area_ots:
                elements.append(build_ots_table(area_ots))
                elements.append(Spacer(1, 2*mm))
            if area_notices:
                elements.append(build_notices_table(area_notices))
            elements.append(Spacer(1, 4*mm))
    elif not (urgent_ots or urgent_notices):
        # No habia nada en absoluto
        elements.append(_p("Sin OTs ni avisos en esta especialidad.", _meta_style))

    # Seccion SIN CLASIFICAR (al final, con aviso)
    if ots_uncls or notices_uncls:
        elements.append(Spacer(1, 8*mm))
        warn_style = ParagraphStyle(
            'warn', parent=_section_style,
            textColor=colors.HexColor('#FF453A')
        )
        elements.append(Paragraph(
            f"⚠ SIN CLASIFICAR — REVISAR Y ASIGNAR ESPECIALIDAD "
            f"({len(ots_uncls)} OTs, {len(notices_uncls)} Avisos)",
            warn_style,
        ))
        elements.append(_p(
            "Los items abajo no tienen especialidad asignada manualmente ni se pudo inferir. "
            "Editar el aviso/OT y marcar especialidad antes del siguiente cierre del turno.",
            _meta_style,
        ))
        elements.append(Spacer(1, 2*mm))
        if ots_uncls:
            elements.append(Paragraph(f"OTs sin clasificar ({len(ots_uncls)})", _section_style))
            elements.append(build_ots_table(ots_uncls))
            elements.append(Spacer(1, 4*mm))
        if notices_uncls:
            elements.append(Paragraph(f"Avisos sin clasificar ({len(notices_uncls)})", _section_style))
            elements.append(build_notices_table(notices_uncls))

    # Espacio para firmas/notas
    elements.append(Spacer(1, 8*mm))
    elements.append(_p("_________________________            _________________________", _meta_style))
    elements.append(_p("Tecnico                                                                 Supervisor", _meta_style))

    doc.build(elements, onFirstPage=_make_footer, onLaterPages=_make_footer)
    buf.seek(0)
    return buf
