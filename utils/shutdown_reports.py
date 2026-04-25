"""Generación de reportes ejecutivos de paradas de planta (PDF + Excel).

Separado de routes/shutdown_routes.py para mantener el blueprint enfocado
en CRUD y delegar la generación de archivos a un módulo especializado.
"""
from io import BytesIO


# ── Payload builder ──────────────────────────────────────────────────────────

def build_payload(
    shutdown_id, *,
    Shutdown, WorkOrder, Area, Line, Equipment,
    OTMaterial, WarehouseItem, SparePart,
):
    """Arma toda la información que necesitan los reportes PDF y Excel."""
    sh = Shutdown.query.get_or_404(shutdown_id)
    ots = WorkOrder.query.filter_by(shutdown_id=shutdown_id).all()

    area_map = {a.id: a.name for a in Area.query.all()}
    line_map = {l.id: l for l in Line.query.all()}
    equip_map = {e.id: e for e in Equipment.query.all()}
    # Componentes para enriquecer cada OT
    try:
        from models import Component
        comp_map = {c.id: c for c in Component.query.all()}
    except Exception:
        comp_map = {}

    # Repuestos por OT
    ot_ids = [o.id for o in ots]
    mats_by_ot = {}
    if ot_ids:
        all_mats = OTMaterial.query.filter(OTMaterial.work_order_id.in_(ot_ids)).all()
        wh_ids = {m.item_id for m in all_mats if m.item_type == 'warehouse'}
        sp_ids = {m.item_id for m in all_mats if m.item_type == 'spare_part'}
        wh_map = {w.id: w for w in WarehouseItem.query.filter(WarehouseItem.id.in_(wh_ids)).all()} if wh_ids else {}
        sp_map = {s.id: s for s in SparePart.query.filter(SparePart.id.in_(sp_ids)).all()} if sp_ids else {}
        for m in all_mats:
            # Las herramientas se asignan a OTs pero no son repuestos
            # consumibles - excluir de los reportes de repuestos.
            if m.item_type == 'tool' or (m.subtype or '').lower() == 'herramienta':
                continue
            name = m.item_name_free or ''
            code = '-'
            if m.item_type == 'warehouse' and m.item_id in wh_map:
                wi = wh_map[m.item_id]
                name = name or wi.name
                code = wi.code or '-'
            elif m.item_type == 'spare_part' and m.item_id in sp_map:
                sp = sp_map[m.item_id]
                name = name or sp.name
                code = sp.code or '-'
            mats_by_ot.setdefault(m.work_order_id, []).append({
                'code': code,
                'name': name or '(sin descripción)',
                'quantity': m.quantity,
                'unit': m.unit or '',
            })

    ot_rows = []
    for ot in ots:
        eq = equip_map.get(ot.equipment_id)
        ln = line_map.get(ot.line_id)
        cp = comp_map.get(getattr(ot, 'component_id', None))
        aname = area_map.get(ot.area_id, '-') if ot.area_id else (area_map.get(ln.area_id, '-') if ln else '-')
        ot_rows.append({
            'code': ot.code or f'OT-{ot.id}',
            'area': aname,
            'line': ln.name if ln else '-',
            'equipment': f"{eq.tag} — {eq.name}" if eq else '-',
            'component': cp.name if cp else '-',
            'description': ot.description or '-',
            'type': ot.maintenance_type or '-',
            'status': ot.status or '-',
            'estimated_h': ot.estimated_duration or 0,
            'real_h': ot.real_duration or 0,
            'failure_mode': ot.failure_mode or '-',
            'materials': mats_by_ot.get(ot.id, []),
        })
    ot_rows.sort(key=lambda r: (r['area'].upper(), r['line'].upper(), r['equipment'].upper(), r['code']))

    est_total = sum(r['estimated_h'] for r in ot_rows)
    real_total = sum(r['real_h'] for r in ot_rows)
    closed = sum(1 for r in ot_rows if r['status'] == 'Cerrada')
    compliance = round((closed / len(ot_rows) * 100) if ot_rows else 0, 1)

    return {
        'shutdown': sh,
        'areas': [sa.area.name for sa in sh.areas if sa.area],
        'ot_rows': ot_rows,
        'kpis': {
            'ot_count': len(ot_rows),
            'ot_closed': closed,
            'compliance': compliance,
            'estimated_hours': round(est_total, 2),
            'real_hours': round(real_total, 2),
            'deviation_hours': round(real_total - est_total, 2),
            'deviation_pct': round(((real_total - est_total) / est_total * 100) if est_total else 0, 1),
        },
    }


# ── Excel ────────────────────────────────────────────────────────────────────

def generate_excel(payload):
    """Retorna BytesIO con el reporte Excel (3 hojas)."""
    import pandas as pd
    sh = payload['shutdown']
    k = payload['kpis']
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine='openpyxl') as writer:
        pd.DataFrame([{
            'Código': sh.code or '-',
            'Parada': sh.name,
            'Fecha': sh.shutdown_date,
            'Horario': f"{sh.start_time} — {sh.end_time}",
            'Tipo': sh.shutdown_type,
            'Áreas': ', '.join(payload['areas']) if payload['areas'] else 'TODAS',
            'Estado': sh.status,
            'OTs Total': k['ot_count'],
            'OTs Cerradas': k['ot_closed'],
            'Cumplimiento %': k['compliance'],
            'Horas Estimadas': k['estimated_hours'],
            'Horas Reales': k['real_hours'],
            'Desviación h': k['deviation_hours'],
            'Desviación %': k['deviation_pct'],
            'Requerimientos Prod.': sh.production_requirements or '-',
            'Observaciones': sh.observations or '-',
        }]).to_excel(writer, sheet_name='Resumen', index=False)

        pd.DataFrame([{
            'Código OT': r['code'],
            'Área': r['area'],
            'Línea': r['line'],
            'Equipo': r['equipment'],
            'Componente': r.get('component') or '-',
            'Tipo': r['type'],
            'Descripción': r['description'],
            'Modo de falla': r['failure_mode'],
            'Horas Est.': r['estimated_h'],
            'Horas Reales': r['real_h'],
            'Estado': r['status'],
        } for r in payload['ot_rows']]).to_excel(writer, sheet_name='OTs', index=False)

        rep_rows = []
        for r in payload['ot_rows']:
            for m in r['materials']:
                rep_rows.append({
                    'OT': r['code'],
                    'Área': r['area'],
                    'Equipo': r['equipment'],
                    'Componente': r.get('component') or '-',
                    'Código Repuesto': m['code'],
                    'Descripción': m['name'],
                    'Cantidad': m['quantity'],
                    'Unidad': m['unit'],
                })
        if rep_rows:
            pd.DataFrame(rep_rows).to_excel(writer, sheet_name='Repuestos por OT', index=False)

    bio.seek(0)
    return bio


# ── PDF ──────────────────────────────────────────────────────────────────────

def generate_pdf(payload):
    """Retorna BytesIO con el reporte ejecutivo en PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    sh = payload['shutdown']
    k = payload['kpis']

    bio = BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Reporte Parada {sh.code or sh.id}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#FF9F0A'), alignment=1)
    subtitle_style = ParagraphStyle('s', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#5a6570'), alignment=1)
    section_style = ParagraphStyle('sec', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0a84ff'), spaceBefore=10)
    body_style = ParagraphStyle('b', parent=styles['Normal'], fontSize=9)
    cell_style = ParagraphStyle('cell', parent=styles['Normal'], fontSize=7, leading=9)
    cell_bold = ParagraphStyle('cellb', parent=styles['Normal'], fontSize=7, leading=9, fontName='Helvetica-Bold')

    story = []

    # Cabecera
    story.append(Paragraph("REPORTE EJECUTIVO DE PARADA DE PLANTA", title_style))
    story.append(Paragraph(f"<b>{sh.code or ''}</b> — {sh.name}", subtitle_style))
    story.append(Spacer(1, 4 * mm))

    info_data = [
        ['Fecha', sh.shutdown_date, 'Horario', f"{sh.start_time} — {sh.end_time}"],
        ['Tipo', sh.shutdown_type, 'Estado', sh.status],
        ['Áreas', ', '.join(payload['areas']) if payload['areas'] else 'TODAS', 'Responsable', sh.created_by or '-'],
    ]
    info_table = Table(info_data, colWidths=[30 * mm, 90 * mm, 30 * mm, 90 * mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e7f1fd')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#e7f1fd')),
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
        ('FONT', (0, 0), (0, -1), 'Helvetica-Bold', 9),
        ('FONT', (2, 0), (2, -1), 'Helvetica-Bold', 9),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5 * mm))

    # KPIs
    story.append(Paragraph("INDICADORES CLAVE", section_style))
    kpi_data = [
        ['OTs Total', 'Cerradas', 'Cumplimiento', 'Horas Est.', 'Horas Reales', 'Desviación'],
        [str(k['ot_count']), str(k['ot_closed']), f"{k['compliance']}%",
         f"{k['estimated_hours']}h", f"{k['real_hours']}h",
         f"{k['deviation_hours']:+.1f}h ({k['deviation_pct']:+.1f}%)"],
    ]
    kpi_table = Table(kpi_data, colWidths=[45 * mm] * 6)
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a84ff')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 10),
        ('FONT', (0, 1), (-1, -1), 'Helvetica-Bold', 14),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (2, 1), (2, 1),
            colors.HexColor('#30a14e') if k['compliance'] >= 80 else colors.HexColor('#d93b3b')),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 5 * mm))

    if sh.production_requirements:
        story.append(Paragraph("REQUERIMIENTOS A PRODUCCIÓN", section_style))
        story.append(Paragraph(sh.production_requirements.replace('\n', '<br/>'), body_style))
        story.append(Spacer(1, 4 * mm))

    # Detalle OTs (celdas con Paragraph → auto-wrap). Despues de cada
    # OT con repuestos se inserta una sub-fila que abarca todas las
    # columnas mostrando la lista de repuestos de esa OT.
    story.append(Paragraph("DETALLE DE ÓRDENES DE TRABAJO", section_style))
    cell_mat = ParagraphStyle(
        'cellmat', parent=cell_style, fontSize=7, leading=9,
        textColor=colors.HexColor('#2c5282'),
    )
    ot_header = ['OT', 'Área', 'Línea', 'Equipo', 'Componente',
                 'Descripción', 'Tipo', 'Hrs Est.', 'Hrs Real', 'Estado']
    ot_table_data = [ot_header]
    # Indices de filas que son sub-filas de repuestos (para aplicar SPAN
    # y un fondo distinto)
    spare_rows_idx = []
    for r in payload['ot_rows']:
        ot_table_data.append([
            Paragraph(r['code'], cell_bold),
            Paragraph(r['area'] or '-', cell_style),
            Paragraph(r['line'] or '-', cell_style),
            Paragraph(r['equipment'] or '-', cell_style),
            Paragraph(r.get('component') or '-', cell_style),
            Paragraph((r['description'] or '-')[:300], cell_style),
            Paragraph(r['type'] or '-', cell_style),
            f"{r['estimated_h']}h",
            f"{r['real_h']}h",
            Paragraph(r['status'] or '-', cell_style),
        ])
        if r.get('materials'):
            mat_lines = []
            for m in r['materials']:
                code = m.get('code') or '-'
                name = m.get('name') or '-'
                qty = m.get('quantity') or '-'
                unit = m.get('unit') or ''
                mat_lines.append(f"&bull; <b>{code}</b> · {name} <i>({qty} {unit})</i>")
            mat_html = "<b>Repuestos:</b> " + "<br/>".join(mat_lines)
            spare_rows_idx.append(len(ot_table_data))  # indice de la sub-fila
            ot_table_data.append([Paragraph(mat_html, cell_mat)] + [''] * 9)

    # 10 columnas en total. Ancho A4 landscape util ~277mm.
    ot_table = Table(
        ot_table_data,
        colWidths=[16 * mm, 24 * mm, 26 * mm, 35 * mm, 28 * mm,
                   65 * mm, 18 * mm, 13 * mm, 13 * mm, 22 * mm],
        repeatRows=1,
    )
    table_style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a84ff')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8),
        ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 4),
    ]
    # Aplicar SPAN y fondo claro azulado a las sub-filas de repuestos
    for ridx in spare_rows_idx:
        table_style_cmds.append(('SPAN', (0, ridx), (-1, ridx)))
        table_style_cmds.append(('BACKGROUND', (0, ridx), (-1, ridx), colors.HexColor('#eef5fc')))
        table_style_cmds.append(('LEFTPADDING', (0, ridx), (-1, ridx), 14))
    ot_table.setStyle(TableStyle(table_style_cmds))
    story.append(ot_table)
    story.append(Spacer(1, 5 * mm))

    # Repuestos
    rep_rows = [(r, m) for r in payload['ot_rows'] for m in r['materials']]
    if rep_rows:
        story.append(PageBreak())
        story.append(Paragraph("REPUESTOS REQUERIDOS POR OT", section_style))
        rep_data = [['OT', 'Equipo', 'Código', 'Descripción', 'Cant.', 'Unidad']]
        for r, m in rep_rows:
            rep_data.append([
                Paragraph(r['code'], cell_bold),
                Paragraph(r['equipment'] or '-', cell_style),
                Paragraph(m['code'] or '-', cell_style),
                Paragraph((m['name'] or '-')[:200], cell_style),
                str(m['quantity']),
                m['unit'] or '-',
            ])
        rep_table = Table(
            rep_data,
            colWidths=[22 * mm, 55 * mm, 28 * mm, 130 * mm, 15 * mm, 20 * mm],
            repeatRows=1,
        )
        rep_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#30d158')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8),
            ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(rep_table)

    if sh.observations:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("OBSERVACIONES / LECCIONES APRENDIDAS", section_style))
        story.append(Paragraph(sh.observations.replace('\n', '<br/>'), body_style))

    doc.build(story)
    bio.seek(0)
    return bio
