"""Rutas para gestión de paradas de planta (domingos de mantenimiento)."""
from flask import jsonify, request
from datetime import datetime


def register_shutdown_routes(
    app, db, logger,
    Shutdown, ShutdownArea, WorkOrder, Area, Equipment, Line,
    OTPersonnel, Technician,
):

    def _generate_shutdown_code(shutdown_date):
        """Genera código automático PP-YYYY-MM-NNN con correlativo mensual."""
        try:
            year_month = shutdown_date[:7]  # 'YYYY-MM'
            prefix = f"PP-{year_month}-"
            existing = Shutdown.query.filter(
                Shutdown.code.like(f"{prefix}%")
            ).all()
            max_n = 0
            for s in existing:
                try:
                    n = int((s.code or '').rsplit('-', 1)[-1])
                    max_n = max(max_n, n)
                except Exception:
                    pass
            return f"{prefix}{max_n + 1:03d}"
        except Exception:
            return f"PP-{datetime.utcnow().strftime('%Y-%m')}-001"

    @app.route('/api/shutdowns', methods=['GET', 'POST'])
    def handle_shutdowns():
        if request.method == 'POST':
            try:
                data = request.json or {}
                from flask_login import current_user
                shutdown = Shutdown(
                    name=data.get('name', ''),
                    shutdown_date=data['shutdown_date'],
                    shutdown_type=data.get('shutdown_type', 'TOTAL'),
                    start_time=data.get('start_time', '07:00'),
                    end_time=data.get('end_time', '19:00'),
                    overtime=data.get('overtime', False),
                    status='PLANIFICADA',
                    production_requirements=data.get('production_requirements'),
                    observations=data.get('observations'),
                    created_by=current_user.full_name if hasattr(current_user, 'full_name') else None,
                )
                db.session.add(shutdown)
                db.session.flush()

                # Generar código automático PP-YYYY-MM-NNN
                shutdown.code = _generate_shutdown_code(shutdown.shutdown_date)

                # Agregar áreas seleccionadas
                area_ids = data.get('area_ids', [])
                for aid in area_ids:
                    sa = ShutdownArea(shutdown_id=shutdown.id, area_id=int(aid))
                    db.session.add(sa)

                # Auto-generar nombre si vacío
                if not shutdown.name:
                    area_names = []
                    for aid in area_ids:
                        a = Area.query.get(int(aid))
                        if a:
                            area_names.append(a.name)
                    type_label = 'Parada Total' if shutdown.shutdown_type == 'TOTAL' else 'Parada Parcial'
                    if area_names and shutdown.shutdown_type == 'PARCIAL':
                        type_label += f' ({", ".join(area_names)})'
                    shutdown.name = f"{type_label} — {shutdown.shutdown_date}"

                db.session.commit()
                return jsonify(shutdown.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creando parada: {e}")
                return jsonify({"error": str(e)}), 500

        # GET
        year = request.args.get('year', type=int)
        status = request.args.get('status')
        q = Shutdown.query
        if year:
            q = q.filter(Shutdown.shutdown_date.like(f'{year}-%'))
        if status:
            q = q.filter_by(status=status)
        shutdowns = q.order_by(Shutdown.shutdown_date.desc()).limit(50).all()
        # Enriquecer con conteo de OTs
        result = []
        for s in shutdowns:
            d = s.to_dict()
            ot_count = WorkOrder.query.filter_by(shutdown_id=s.id).count()
            ot_closed = WorkOrder.query.filter_by(shutdown_id=s.id, status='Cerrada').count()
            d['ot_count'] = ot_count
            d['ot_closed'] = ot_closed
            d['compliance'] = round((ot_closed / ot_count * 100) if ot_count else 0, 1)
            # Horas estimadas
            from sqlalchemy import func
            total_hrs = db.session.query(func.coalesce(func.sum(WorkOrder.estimated_duration), 0)) \
                .filter(WorkOrder.shutdown_id == s.id).scalar()
            d['total_hours'] = float(total_hrs or 0)
            result.append(d)
        return jsonify(result)

    @app.route('/api/shutdowns/<int:shutdown_id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_shutdown_detail(shutdown_id):
        shutdown = Shutdown.query.get_or_404(shutdown_id)

        if request.method == 'DELETE':
            try:
                # Desvincular OTs
                WorkOrder.query.filter_by(shutdown_id=shutdown_id).update({"shutdown_id": None})
                ShutdownArea.query.filter_by(shutdown_id=shutdown_id).delete()
                db.session.delete(shutdown)
                db.session.commit()
                return jsonify({"message": "Parada eliminada"})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        if request.method == 'PUT':
            try:
                data = request.json or {}
                for key in ('name', 'shutdown_date', 'shutdown_type', 'start_time', 'end_time',
                            'status', 'production_requirements', 'observations', 'overtime'):
                    if key in data:
                        setattr(shutdown, key, data[key])
                # Actualizar áreas si vienen
                if 'area_ids' in data:
                    ShutdownArea.query.filter_by(shutdown_id=shutdown_id).delete()
                    for aid in data['area_ids']:
                        db.session.add(ShutdownArea(shutdown_id=shutdown_id, area_id=int(aid)))
                db.session.commit()
                return jsonify(shutdown.to_dict())
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET — detalle completo con OTs agrupadas por área
        d = shutdown.to_dict()
        ots = WorkOrder.query.filter_by(shutdown_id=shutdown_id).all()
        # Resolver nombres
        area_map = {a.id: a.name for a in Area.query.all()}
        line_map = {l.id: l for l in Line.query.all()}
        equip_map = {e.id: e for e in Equipment.query.all()}
        tech_map = {str(t.id): t.name for t in Technician.query.all()}

        # Repuestos por OT (ot_materials con info de almacén)
        from models import OTMaterial, WarehouseItem, SparePart
        ot_ids = [ot.id for ot in ots]
        materials_by_ot = {}
        if ot_ids:
            all_materials = OTMaterial.query.filter(OTMaterial.work_order_id.in_(ot_ids)).all()
            # Resolver nombres de items
            wh_item_ids = {m.item_id for m in all_materials if m.item_type == 'warehouse'}
            sp_item_ids = {m.item_id for m in all_materials if m.item_type == 'spare_part'}
            wh_map = {}
            if wh_item_ids:
                wh_map = {w.id: w for w in WarehouseItem.query.filter(WarehouseItem.id.in_(wh_item_ids)).all()}
            sp_map = {}
            if sp_item_ids:
                sp_map = {s.id: s for s in SparePart.query.filter(SparePart.id.in_(sp_item_ids)).all()}
            for m in all_materials:
                name = m.item_name_free or ''
                code = '-'
                stock = None
                if m.item_type == 'warehouse' and m.item_id in wh_map:
                    wi = wh_map[m.item_id]
                    name = name or wi.name
                    code = wi.code or '-'
                    stock = wi.stock
                elif m.item_type == 'spare_part' and m.item_id in sp_map:
                    sp = sp_map[m.item_id]
                    name = name or sp.name
                    code = sp.code or '-'
                    stock = sp.quantity
                materials_by_ot.setdefault(m.work_order_id, []).append({
                    'id': m.id,
                    'item_type': m.item_type,
                    'item_id': m.item_id,
                    'code': code,
                    'name': name or '(sin descripción)',
                    'quantity': m.quantity,
                    'unit': m.unit,
                    'subtype': m.subtype,
                    'stock': stock,
                    'sufficient': (stock is not None and stock >= (m.quantity or 0)),
                    'is_installed': m.is_installed,
                })

        ot_list = []
        for ot in ots:
            od = ot.to_dict()
            od['area_name'] = area_map.get(ot.area_id, '-')
            eq = equip_map.get(ot.equipment_id)
            od['equipment_name'] = eq.name if eq else '-'
            od['equipment_tag'] = eq.tag if eq else '-'
            ln = line_map.get(ot.line_id)
            od['line_name'] = ln.name if ln else '-'
            if not od.get('area_name') or od['area_name'] == '-':
                if ln:
                    od['area_name'] = area_map.get(ln.area_id, '-')
            od['technician_name'] = tech_map.get(str(ot.technician_id), ot.technician_id or '-')
            # Personal asignado
            personnel = OTPersonnel.query.filter_by(work_order_id=ot.id).all()
            od['personnel'] = [{'name': tech_map.get(str(p.technician_id), '-'), 'hours': p.hours_assigned}
                               for p in personnel]
            # Repuestos de esta OT
            od['materials'] = materials_by_ot.get(ot.id, [])
            ot_list.append(od)

        # Ordenar por Área → Línea → Equipo → código OT
        ot_list.sort(key=lambda o: (
            (o.get('area_name') or 'ZZZ').upper(),
            (o.get('line_name') or 'ZZZ').upper(),
            (o.get('equipment_tag') or 'ZZZ').upper(),
            o.get('code') or '',
        ))

        # Agrupar por área (preservando orden)
        by_area = {}
        for ot in ot_list:
            area = ot.get('area_name', 'Sin Área')
            if area not in by_area:
                by_area[area] = []
            by_area[area].append(ot)

        d['work_orders'] = ot_list
        d['by_area'] = by_area
        d['ot_count'] = len(ot_list)
        d['ot_closed'] = sum(1 for o in ot_list if o.get('status') == 'Cerrada')
        d['compliance'] = round((d['ot_closed'] / d['ot_count'] * 100) if d['ot_count'] else 0, 1)
        from sqlalchemy import func
        d['total_hours'] = float(db.session.query(
            func.coalesce(func.sum(WorkOrder.estimated_duration), 0)
        ).filter(WorkOrder.shutdown_id == shutdown_id).scalar() or 0)
        d['total_real_hours'] = float(db.session.query(
            func.coalesce(func.sum(WorkOrder.real_duration), 0)
        ).filter(WorkOrder.shutdown_id == shutdown_id).scalar() or 0)
        # Conteo técnicos
        tech_ids = set()
        for ot in ots:
            if ot.technician_id:
                tech_ids.add(ot.technician_id)
            for p in OTPersonnel.query.filter_by(work_order_id=ot.id).all():
                if p.technician_id:
                    tech_ids.add(str(p.technician_id))
        d['technician_count'] = len(tech_ids)
        # Contar OTs con repuestos insuficientes en stock (para alerta)
        d['ots_with_materials'] = sum(1 for o in ot_list if o.get('materials'))
        d['materials_shortage'] = sum(
            1 for o in ot_list for m in o.get('materials', [])
            if m.get('stock') is not None and not m.get('sufficient')
        )
        return jsonify(d)

    @app.route('/api/shutdowns/<int:shutdown_id>/work-orders', methods=['POST'])
    def create_ot_in_shutdown(shutdown_id):
        """Crear una OT NUEVA directamente dentro de una parada (no requiere aviso).

        Uso tipico: planificador arma una parada con varios trabajos
        aprovechados (cambio de tapa, chaqueta, etc.) sin que haya una
        falla concreta que los origine.

        Si se pasan source_type y source_id, la OT queda vinculada a un
        punto preventivo (lubricacion, inspeccion, monitoreo) y al
        cerrarla se actualiza automaticamente la proxima fecha del punto.
        """
        try:
            data = request.json or {}
            # Validar que la parada existe
            from models import Shutdown
            sh = Shutdown.query.get_or_404(shutdown_id)

            # Campos obligatorios
            description = (data.get('description') or '').strip()
            if not description:
                return jsonify({"error": "Falta descripcion"}), 400

            # Normalizar source_type / source_id
            source_type = data.get('source_type') or None
            source_id_raw = data.get('source_id')
            try:
                source_id = int(source_id_raw) if source_id_raw not in (None, '', 0) else None
            except Exception:
                source_id = None

            # Si viene de un plan preventivo, forzar tipo = Preventivo
            maint_type = data.get('maintenance_type') or 'Correctivo'
            if source_type in ('lubrication', 'inspection', 'monitoring'):
                maint_type = 'Preventivo'

            # Sanitizar y construir
            clean = {
                'description': description,
                'maintenance_type': maint_type,
                'status': data.get('status') or 'Programada',
                'scheduled_date': data.get('scheduled_date') or sh.shutdown_date,
                'estimated_duration': data.get('estimated_duration') or 0,
                'tech_count': data.get('tech_count') or 1,
                'failure_mode': data.get('failure_mode'),
                'technician_id': data.get('technician_id'),
                'provider_id': data.get('provider_id'),
                'area_id': data.get('area_id'),
                'line_id': data.get('line_id'),
                'equipment_id': data.get('equipment_id'),
                'system_id': data.get('system_id'),
                'component_id': data.get('component_id'),
                'source_type': source_type if source_id else None,
                'source_id': source_id,
                'shutdown_id': shutdown_id,
            }
            # Convertir '' a None
            for k, v in list(clean.items()):
                if isinstance(v, str) and v.strip() == '':
                    clean[k] = None

            wo = WorkOrder(**clean)
            db.session.add(wo)
            db.session.flush()
            wo.code = f"OT-{wo.id:04d}"
            db.session.commit()

            # Indexar para RAG (opcional, no bloqueante)
            try:
                from bot.telegram_bot import _index_entity_async
                _index_entity_async(app, 'work_order', wo.id)
            except Exception:
                pass

            return jsonify(wo.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/add-ot', methods=['POST'])
    def add_ot_to_shutdown(shutdown_id):
        """Vincular OT(s) existentes a una parada."""
        try:
            data = request.json or {}
            ot_ids = data.get('ot_ids', [])
            if not ot_ids:
                return jsonify({"error": "ot_ids requeridos"}), 400
            count = 0
            for oid in ot_ids:
                ot = WorkOrder.query.get(int(oid))
                if ot:
                    ot.shutdown_id = shutdown_id
                    count += 1
            db.session.commit()
            return jsonify({"message": f"{count} OTs vinculadas"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/remove-ot/<int:ot_id>', methods=['DELETE'])
    def remove_ot_from_shutdown(shutdown_id, ot_id):
        """Desvincular OT de una parada."""
        try:
            ot = WorkOrder.query.get_or_404(ot_id)
            if ot.shutdown_id == shutdown_id:
                ot.shutdown_id = None
                db.session.commit()
            return jsonify({"message": "OT desvinculada"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    def _build_report_payload(shutdown_id):
        """Arma el payload completo del reporte ejecutivo de una parada."""
        sh = Shutdown.query.get_or_404(shutdown_id)
        # Reutilizamos el endpoint de detalle
        with app.test_request_context():
            pass
        ots = WorkOrder.query.filter_by(shutdown_id=shutdown_id).all()
        area_map = {a.id: a.name for a in Area.query.all()}
        line_map = {l.id: l for l in Line.query.all()}
        equip_map = {e.id: e for e in Equipment.query.all()}

        from models import OTMaterial, WarehouseItem, SparePart
        ot_ids = [o.id for o in ots]
        mats_by_ot = {}
        if ot_ids:
            all_mats = OTMaterial.query.filter(OTMaterial.work_order_id.in_(ot_ids)).all()
            wh_ids = {m.item_id for m in all_mats if m.item_type == 'warehouse'}
            sp_ids = {m.item_id for m in all_mats if m.item_type == 'spare_part'}
            wh_map = {w.id: w for w in WarehouseItem.query.filter(WarehouseItem.id.in_(wh_ids)).all()} if wh_ids else {}
            sp_map = {s.id: s for s in SparePart.query.filter(SparePart.id.in_(sp_ids)).all()} if sp_ids else {}
            for m in all_mats:
                name = m.item_name_free or ''
                code = '-'
                if m.item_type == 'warehouse' and m.item_id in wh_map:
                    wi = wh_map[m.item_id]; name = name or wi.name; code = wi.code or '-'
                elif m.item_type == 'spare_part' and m.item_id in sp_map:
                    sp = sp_map[m.item_id]; name = name or sp.name; code = sp.code or '-'
                mats_by_ot.setdefault(m.work_order_id, []).append({
                    'code': code, 'name': name or '(sin descripción)',
                    'quantity': m.quantity, 'unit': m.unit or '',
                })

        ot_rows = []
        for ot in ots:
            eq = equip_map.get(ot.equipment_id)
            ln = line_map.get(ot.line_id)
            aname = area_map.get(ot.area_id, '-') if ot.area_id else (area_map.get(ln.area_id, '-') if ln else '-')
            ot_rows.append({
                'code': ot.code or f'OT-{ot.id}',
                'area': aname,
                'line': ln.name if ln else '-',
                'equipment': f"{eq.tag} — {eq.name}" if eq else '-',
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

    @app.route('/api/shutdowns/<int:shutdown_id>/report/excel', methods=['GET'])
    def export_shutdown_excel(shutdown_id):
        """Reporte ejecutivo de parada en Excel (múltiples hojas)."""
        try:
            from io import BytesIO
            import pandas as pd
            payload = _build_report_payload(shutdown_id)
            sh = payload['shutdown']
            k = payload['kpis']

            bio = BytesIO()
            with pd.ExcelWriter(bio, engine='openpyxl') as writer:
                # Resumen
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

                # OTs
                ot_df = pd.DataFrame([{
                    'Código OT': r['code'],
                    'Área': r['area'],
                    'Línea': r['line'],
                    'Equipo': r['equipment'],
                    'Tipo': r['type'],
                    'Descripción': r['description'],
                    'Modo de falla': r['failure_mode'],
                    'Horas Est.': r['estimated_h'],
                    'Horas Reales': r['real_h'],
                    'Estado': r['status'],
                } for r in payload['ot_rows']])
                ot_df.to_excel(writer, sheet_name='OTs', index=False)

                # Repuestos detallado por OT
                rep_rows = []
                for r in payload['ot_rows']:
                    for m in r['materials']:
                        rep_rows.append({
                            'OT': r['code'],
                            'Área': r['area'],
                            'Equipo': r['equipment'],
                            'Código Repuesto': m['code'],
                            'Descripción': m['name'],
                            'Cantidad': m['quantity'],
                            'Unidad': m['unit'],
                        })
                if rep_rows:
                    pd.DataFrame(rep_rows).to_excel(writer, sheet_name='Repuestos por OT', index=False)

            bio.seek(0)
            filename = f"Parada_{sh.code or sh.id}_{sh.shutdown_date}.xlsx"
            from flask import send_file
            return send_file(
                bio, as_attachment=True, download_name=filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            logger.error(f"export_shutdown_excel error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/report/pdf', methods=['GET'])
    def export_shutdown_pdf(shutdown_id):
        """Reporte ejecutivo de parada en PDF."""
        try:
            from io import BytesIO
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
            )

            payload = _build_report_payload(shutdown_id)
            sh = payload['shutdown']
            k = payload['kpis']

            bio = BytesIO()
            doc = SimpleDocTemplate(
                bio, pagesize=landscape(A4),
                leftMargin=12*mm, rightMargin=12*mm,
                topMargin=12*mm, bottomMargin=12*mm,
                title=f"Reporte Parada {sh.code or sh.id}",
            )
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#FF9F0A'), alignment=1)
            subtitle_style = ParagraphStyle('s', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#5a6570'), alignment=1)
            section_style = ParagraphStyle('sec', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0a84ff'), spaceBefore=10)
            body_style = ParagraphStyle('b', parent=styles['Normal'], fontSize=9)
            body_small = ParagraphStyle('bs', parent=styles['Normal'], fontSize=8)

            story = []

            # Portada / Cabecera
            story.append(Paragraph(f"REPORTE EJECUTIVO DE PARADA DE PLANTA", title_style))
            story.append(Paragraph(f"<b>{sh.code or ''}</b> — {sh.name}", subtitle_style))
            story.append(Spacer(1, 4*mm))

            info_data = [
                ['Fecha', sh.shutdown_date, 'Horario', f"{sh.start_time} — {sh.end_time}"],
                ['Tipo', sh.shutdown_type, 'Estado', sh.status],
                ['Áreas', ', '.join(payload['areas']) if payload['areas'] else 'TODAS', 'Responsable', sh.created_by or '-'],
            ]
            info_table = Table(info_data, colWidths=[30*mm, 90*mm, 30*mm, 90*mm])
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
            story.append(Spacer(1, 5*mm))

            # KPIs
            story.append(Paragraph("INDICADORES CLAVE", section_style))
            kpi_data = [
                ['OTs Total', 'Cerradas', 'Cumplimiento', 'Horas Est.', 'Horas Reales', 'Desviación'],
                [str(k['ot_count']), str(k['ot_closed']), f"{k['compliance']}%",
                 f"{k['estimated_hours']}h", f"{k['real_hours']}h",
                 f"{k['deviation_hours']:+.1f}h ({k['deviation_pct']:+.1f}%)"],
            ]
            kpi_table = Table(kpi_data, colWidths=[45*mm]*6)
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
            story.append(Spacer(1, 5*mm))

            # Requerimientos a producción
            if sh.production_requirements:
                story.append(Paragraph("REQUERIMIENTOS A PRODUCCIÓN", section_style))
                story.append(Paragraph(sh.production_requirements.replace('\n', '<br/>'), body_style))
                story.append(Spacer(1, 4*mm))

            # Tabla de OTs agrupada por área
            story.append(Paragraph("DETALLE DE ÓRDENES DE TRABAJO", section_style))
            # Estilo compacto para celdas con wrap automático
            cell_style = ParagraphStyle(
                'cell', parent=styles['Normal'], fontSize=7, leading=9,
            )
            cell_bold = ParagraphStyle(
                'cellb', parent=styles['Normal'], fontSize=7, leading=9,
                fontName='Helvetica-Bold',
            )
            ot_header = ['OT', 'Área', 'Línea', 'Equipo', 'Descripción', 'Tipo', 'Hrs Est.', 'Hrs Real', 'Estado']
            ot_table_data = [ot_header]
            for r in payload['ot_rows']:
                ot_table_data.append([
                    Paragraph(r['code'], cell_bold),
                    Paragraph(r['area'] or '-', cell_style),
                    Paragraph(r['line'] or '-', cell_style),
                    Paragraph(r['equipment'] or '-', cell_style),
                    Paragraph((r['description'] or '-')[:300], cell_style),
                    Paragraph(r['type'] or '-', cell_style),
                    f"{r['estimated_h']}h",
                    f"{r['real_h']}h",
                    Paragraph(r['status'] or '-', cell_style),
                ])
            ot_table = Table(
                ot_table_data,
                colWidths=[18*mm, 28*mm, 30*mm, 38*mm, 78*mm, 20*mm, 14*mm, 14*mm, 22*mm],
                repeatRows=1,
            )
            ot_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a84ff')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8),
                ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 4),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f7fa')]),
            ]))
            story.append(ot_table)
            story.append(Spacer(1, 5*mm))

            # Repuestos por OT
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
                    colWidths=[22*mm, 55*mm, 28*mm, 130*mm, 15*mm, 20*mm],
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

            # Observaciones
            if sh.observations:
                story.append(Spacer(1, 5*mm))
                story.append(Paragraph("OBSERVACIONES / LECCIONES APRENDIDAS", section_style))
                story.append(Paragraph(sh.observations.replace('\n', '<br/>'), body_style))

            doc.build(story)
            bio.seek(0)
            filename = f"Parada_{sh.code or sh.id}_{sh.shutdown_date}.pdf"
            from flask import send_file
            return send_file(
                bio, as_attachment=True, download_name=filename,
                mimetype='application/pdf',
            )
        except Exception as e:
            logger.error(f"export_shutdown_pdf error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/preventive-sources', methods=['GET'])
    def get_shutdown_preventive_sources(shutdown_id):
        """Lista puntos preventivos (lubricacion, inspeccion, monitoreo) que
        se pueden agregar a esta parada, filtrados por las areas de la parada.

        Prioriza puntos VENCIDOS/PROXIMOS y excluye los que ya tienen OT
        abierta vinculada (para no duplicar).

        Query param opcional: ?source_type=lubrication|inspection|monitoring
        """
        try:
            from models import (
                LubricationPoint, InspectionRoute, MonitoringPoint,
            )
            sh = Shutdown.query.get_or_404(shutdown_id)
            filter_type = request.args.get('source_type')

            # Areas de la parada (vacio = todas las areas)
            area_ids = [sa.area_id for sa in sh.areas] if sh.shutdown_type == 'PARCIAL' else []

            # Mapas auxiliares
            line_map = {l.id: l for l in Line.query.all()}
            equip_map = {e.id: e for e in Equipment.query.all()}
            area_map = {a.id: a for a in Area.query.all()}

            def _resolve_area_id(point):
                if point.area_id:
                    return point.area_id
                if point.line_id and point.line_id in line_map:
                    return line_map[point.line_id].area_id
                if point.equipment_id and point.equipment_id in equip_map:
                    eq = equip_map[point.equipment_id]
                    if eq.line_id and eq.line_id in line_map:
                        return line_map[eq.line_id].area_id
                return None

            def _in_area_filter(aid):
                if not area_ids:
                    return True  # parada TOTAL
                return aid in area_ids

            # OTs abiertas por source (para excluir duplicados)
            open_ots = WorkOrder.query.filter(
                WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso']),
                WorkOrder.source_type.isnot(None),
            ).all()
            occupied = {(o.source_type, o.source_id) for o in open_ots if o.source_id}

            sources = []

            # Lubricacion
            if not filter_type or filter_type == 'lubrication':
                for p in LubricationPoint.query.filter_by(is_active=True).all():
                    aid = _resolve_area_id(p)
                    if not _in_area_filter(aid):
                        continue
                    if ('lubrication', p.id) in occupied:
                        continue
                    eq = equip_map.get(p.equipment_id) if p.equipment_id else None
                    ln = line_map.get(p.line_id) if p.line_id else (line_map.get(eq.line_id) if eq else None)
                    desc = f"[PREVENTIVO - LUBRICACION] {p.code or ''} {p.name or p.task_name or ''}".strip()
                    if p.lubricant_name:
                        desc += f"\nLubricante: {p.lubricant_name}"
                        if p.quantity_nominal:
                            desc += f" | Cantidad: {p.quantity_nominal} {p.quantity_unit or ''}".strip()
                    if p.last_service_date:
                        desc += f"\nUltimo servicio: {p.last_service_date}"
                    sources.append({
                        'source_type': 'lubrication',
                        'source_id': p.id,
                        'code': p.code or '',
                        'name': p.name or p.task_name or '(sin nombre)',
                        'semaphore': p.semaphore_status or 'VERDE',
                        'next_due_date': p.next_due_date or '-',
                        'frequency_days': p.frequency_days,
                        'last_execution': p.last_service_date or '-',
                        'area_id': aid,
                        'area_name': area_map.get(aid).name if aid in area_map else '-',
                        'line_id': p.line_id or (eq.line_id if eq else None),
                        'line_name': ln.name if ln else '-',
                        'equipment_id': p.equipment_id,
                        'equipment_tag': eq.tag if eq else '-',
                        'equipment_name': eq.name if eq else '-',
                        'system_id': p.system_id,
                        'component_id': p.component_id,
                        'description': desc,
                    })

            # Inspeccion
            if not filter_type or filter_type == 'inspection':
                for r in InspectionRoute.query.filter_by(is_active=True).all():
                    aid = _resolve_area_id(r)
                    if not _in_area_filter(aid):
                        continue
                    if ('inspection', r.id) in occupied:
                        continue
                    eq = equip_map.get(r.equipment_id) if r.equipment_id else None
                    ln = line_map.get(r.line_id) if r.line_id else (line_map.get(eq.line_id) if eq else None)
                    desc = f"[PREVENTIVO - INSPECCION] {r.code or ''} {r.name or ''}".strip()
                    desc += f"\nFrecuencia: cada {r.frequency_days} dias"
                    if r.last_execution_date:
                        desc += f" | Ultima ejecucion: {r.last_execution_date}"
                    sources.append({
                        'source_type': 'inspection',
                        'source_id': r.id,
                        'code': r.code or '',
                        'name': r.name or '',
                        'semaphore': r.semaphore_status or 'VERDE',
                        'next_due_date': r.next_due_date or '-',
                        'frequency_days': r.frequency_days,
                        'last_execution': r.last_execution_date or '-',
                        'area_id': aid,
                        'area_name': area_map.get(aid).name if aid in area_map else '-',
                        'line_id': r.line_id or (eq.line_id if eq else None),
                        'line_name': ln.name if ln else '-',
                        'equipment_id': r.equipment_id,
                        'equipment_tag': eq.tag if eq else '-',
                        'equipment_name': eq.name if eq else '-',
                        'system_id': None,
                        'component_id': None,
                        'description': desc,
                    })

            # Monitoreo
            if not filter_type or filter_type == 'monitoring':
                for p in MonitoringPoint.query.filter_by(is_active=True).all():
                    aid = _resolve_area_id(p)
                    if not _in_area_filter(aid):
                        continue
                    if ('monitoring', p.id) in occupied:
                        continue
                    eq = equip_map.get(p.equipment_id) if p.equipment_id else None
                    ln = line_map.get(p.line_id) if p.line_id else (line_map.get(eq.line_id) if eq else None)
                    desc = f"[PREVENTIVO - MONITOREO] {p.code or ''} {p.name or ''}".strip()
                    if p.measurement_type:
                        desc += f"\nTipo: {p.measurement_type}"
                        if p.axis:
                            desc += f" Eje: {p.axis}"
                    if p.alarm_min is not None or p.alarm_max is not None:
                        desc += f"\nAlarma: {p.alarm_min or '-'} a {p.alarm_max or '-'} {p.unit or ''}".strip()
                    sources.append({
                        'source_type': 'monitoring',
                        'source_id': p.id,
                        'code': p.code or '',
                        'name': p.name or '',
                        'semaphore': p.semaphore_status or 'VERDE',
                        'next_due_date': p.next_due_date or '-',
                        'frequency_days': p.frequency_days,
                        'last_execution': p.last_measurement_date or '-',
                        'area_id': aid,
                        'area_name': area_map.get(aid).name if aid in area_map else '-',
                        'line_id': p.line_id or (eq.line_id if eq else None),
                        'line_name': ln.name if ln else '-',
                        'equipment_id': p.equipment_id,
                        'equipment_tag': eq.tag if eq else '-',
                        'equipment_name': eq.name if eq else '-',
                        'system_id': p.system_id,
                        'component_id': p.component_id,
                        'description': desc,
                    })

            # Orden: ROJO primero, luego AMARILLO, luego VERDE; por next_due_date
            sem_rank = {'ROJO': 0, 'AMARILLO': 1, 'VERDE': 2}
            sources.sort(key=lambda s: (sem_rank.get(s['semaphore'], 9), s['next_due_date'] or 'zzz'))

            return jsonify(sources)
        except Exception as e:
            logger.error(f"get_shutdown_preventive_sources error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdowns/<int:shutdown_id>/suggestions', methods=['GET'])
    def get_shutdown_suggestions(shutdown_id):
        """OTs abiertas/pendientes que podrían agregarse a esta parada."""
        try:
            shutdown = Shutdown.query.get_or_404(shutdown_id)
            area_ids = [sa.area_id for sa in shutdown.areas]
            q = WorkOrder.query.filter(
                WorkOrder.status.in_(['Abierta', 'Programada']),
                WorkOrder.shutdown_id.is_(None),
            )
            if area_ids and shutdown.shutdown_type == 'PARCIAL':
                q = q.filter(WorkOrder.area_id.in_(area_ids))
            candidates = q.order_by(WorkOrder.id.desc()).limit(50).all()

            area_map = {a.id: a.name for a in Area.query.all()}
            equip_map = {e.id: e for e in Equipment.query.all()}
            result = []
            for ot in candidates:
                od = ot.to_dict()
                od['area_name'] = area_map.get(ot.area_id, '-')
                eq = equip_map.get(ot.equipment_id)
                od['equipment_name'] = eq.name if eq else '-'
                od['equipment_tag'] = eq.tag if eq else '-'
                result.append(od)
            return jsonify(result)
        except Exception as e:
            return jsonify([])
