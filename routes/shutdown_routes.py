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
                # Excluir herramientas de la lista de repuestos. Las
                # herramientas se asignan a la OT pero no son repuestos
                # consumibles para la parada.
                if m.item_type == 'tool' or (m.subtype or '').lower() == 'herramienta':
                    continue
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

    # ── Reportes ejecutivos (delegados a utils/shutdown_reports.py) ──────

    def _build_report_payload(shutdown_id):
        from models import OTMaterial, WarehouseItem, SparePart
        from utils.shutdown_reports import build_payload
        return build_payload(
            shutdown_id,
            Shutdown=Shutdown, WorkOrder=WorkOrder,
            Area=Area, Line=Line, Equipment=Equipment,
            OTMaterial=OTMaterial, WarehouseItem=WarehouseItem, SparePart=SparePart,
        )

    @app.route('/api/shutdowns/<int:shutdown_id>/report/excel', methods=['GET'])
    def export_shutdown_excel(shutdown_id):
        """Reporte ejecutivo de parada en Excel (múltiples hojas)."""
        try:
            from utils.shutdown_reports import generate_excel
            from flask import send_file
            payload = _build_report_payload(shutdown_id)
            bio = generate_excel(payload)
            sh = payload['shutdown']
            filename = f"Parada_{sh.code or sh.id}_{sh.shutdown_date}.xlsx"
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
            from utils.shutdown_reports import generate_pdf
            from flask import send_file
            payload = _build_report_payload(shutdown_id)
            bio = generate_pdf(payload)
            sh = payload['shutdown']
            filename = f"Parada_{sh.code or sh.id}_{sh.shutdown_date}.pdf"
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
        Excluye puntos ya ocupados en otras OTs abiertas para no duplicar.
        Query param opcional: ?source_type=lubrication|inspection|monitoring
        """
        try:
            from models import LubricationPoint, InspectionRoute, MonitoringPoint
            from utils.preventive_sources import collect_sources
            from utils.schedule_helpers import (
                _calculate_lubrication_schedule, _calculate_monitoring_schedule,
            )

            sh = Shutdown.query.get_or_404(shutdown_id)
            filter_type = request.args.get('source_type')

            # Areas de la parada (vacio = todas las areas = sin filtro)
            area_ids = [sa.area_id for sa in sh.areas] if sh.shutdown_type == 'PARCIAL' else None

            # Source types a incluir
            source_types = {filter_type} if filter_type else None

            # Excluir puntos que ya tienen OT abierta vinculada
            open_ots = WorkOrder.query.filter(
                WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso']),
                WorkOrder.source_type.isnot(None),
            ).all()
            exclude = {(o.source_type, o.source_id) for o in open_ots if o.source_id}

            sources = collect_sources(
                LubricationPoint, InspectionRoute, MonitoringPoint,
                _calc_lub_schedule=_calculate_lubrication_schedule,
                _calc_mon_schedule=_calculate_monitoring_schedule,
                source_types=source_types,
                area_ids=area_ids,
                exclude=exclude,
                enrich_names=True,
            )
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

    # ════════════════════════════════════════════════════════════════════════
    # PLANTILLAS DE PARADA (ShutdownTemplate)
    # ════════════════════════════════════════════════════════════════════════

    @app.route('/api/shutdown-templates', methods=['GET', 'POST'])
    def handle_shutdown_templates():
        from models import ShutdownTemplate, ShutdownTemplateItem
        if request.method == 'POST':
            try:
                from flask_login import current_user
                data = request.json or {}
                name = (data.get('name') or '').strip()
                if not name:
                    return jsonify({"error": "Falta name"}), 400
                t = ShutdownTemplate(
                    name=name,
                    description=(data.get('description') or '').strip() or None,
                    is_active=bool(data.get('is_active', True)),
                    created_by=getattr(current_user, 'full_name', None),
                )
                db.session.add(t)
                db.session.commit()
                return jsonify(t.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception('shutdown template POST error')
                return jsonify({"error": str(e)}), 500

        # GET — listar
        only_active = request.args.get('only_active', '0') == '1'
        q = ShutdownTemplate.query
        if only_active:
            q = q.filter_by(is_active=True)
        rows = q.order_by(ShutdownTemplate.name).all()
        return jsonify([t.to_dict() for t in rows])

    @app.route('/api/shutdown-templates/<int:template_id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_shutdown_template_detail(template_id):
        from models import ShutdownTemplate
        t = ShutdownTemplate.query.get_or_404(template_id)
        if request.method == 'GET':
            return jsonify(t.to_dict(with_items=True))
        if request.method == 'PUT':
            try:
                data = request.json or {}
                if 'name' in data:
                    t.name = (data['name'] or '').strip() or t.name
                if 'description' in data:
                    t.description = (data.get('description') or '').strip() or None
                if 'is_active' in data:
                    t.is_active = bool(data['is_active'])
                db.session.commit()
                return jsonify(t.to_dict(with_items=True))
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        # DELETE
        try:
            db.session.delete(t)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdown-templates/<int:template_id>/items', methods=['POST'])
    def add_template_item(template_id):
        from models import ShutdownTemplate, ShutdownTemplateItem
        t = ShutdownTemplate.query.get_or_404(template_id)
        try:
            data = request.json or {}
            description = (data.get('description') or '').strip()
            if not description:
                return jsonify({"error": "Falta description"}), 400
            mode = (data.get('application_mode') or 'specific_equipment').strip()
            if mode not in ('specific_equipment', 'tag_pattern', 'area', 'line'):
                return jsonify({"error": "application_mode invalido"}), 400
            # Validar que tenga el target acorde
            tgt = {
                'target_equipment_id': data.get('target_equipment_id'),
                'target_area_id': data.get('target_area_id'),
                'target_line_id': data.get('target_line_id'),
                'target_tag_pattern': (data.get('target_tag_pattern') or '').strip() or None,
            }
            if mode == 'specific_equipment' and not tgt['target_equipment_id']:
                return jsonify({"error": "Falta target_equipment_id"}), 400
            if mode == 'tag_pattern' and not tgt['target_tag_pattern']:
                return jsonify({"error": "Falta target_tag_pattern (ej: '^D[1-9]$')"}), 400
            if mode == 'area' and not tgt['target_area_id']:
                return jsonify({"error": "Falta target_area_id"}), 400
            if mode == 'line' and not tgt['target_line_id']:
                return jsonify({"error": "Falta target_line_id"}), 400

            # order_index siguiente
            max_idx = db.session.query(db.func.max(ShutdownTemplateItem.order_index)) \
                .filter_by(template_id=template_id).scalar() or 0
            it = ShutdownTemplateItem(
                template_id=template_id,
                order_index=max_idx + 1,
                description=description,
                maintenance_type=data.get('maintenance_type') or 'Preventivo',
                estimated_duration=data.get('estimated_duration'),
                tech_count=int(data.get('tech_count') or 1),
                specialty=(data.get('specialty') or '').strip() or None,
                component_name=(data.get('component_name') or '').strip() or None,
                application_mode=mode,
                target_equipment_id=tgt['target_equipment_id'] if mode == 'specific_equipment' else None,
                target_area_id=tgt['target_area_id'] if mode == 'area' else None,
                target_line_id=tgt['target_line_id'] if mode == 'line' else None,
                target_tag_pattern=tgt['target_tag_pattern'] if mode == 'tag_pattern' else None,
            )
            db.session.add(it)
            db.session.commit()
            return jsonify(it.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            logger.exception('add_template_item error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/shutdown-template-items/<int:item_id>', methods=['PUT', 'DELETE'])
    def handle_template_item(item_id):
        from models import ShutdownTemplateItem
        it = ShutdownTemplateItem.query.get_or_404(item_id)
        if request.method == 'DELETE':
            try:
                db.session.delete(it)
                db.session.commit()
                return jsonify({"ok": True})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        try:
            data = request.json or {}
            for fld in ('description', 'maintenance_type', 'specialty', 'component_name',
                        'target_tag_pattern'):
                if fld in data:
                    val = (data.get(fld) or '').strip() or None if isinstance(data.get(fld), str) else data.get(fld)
                    setattr(it, fld, val)
            for fld in ('estimated_duration', 'tech_count', 'order_index',
                        'target_equipment_id', 'target_area_id', 'target_line_id'):
                if fld in data:
                    setattr(it, fld, data.get(fld))
            if 'application_mode' in data:
                it.application_mode = data['application_mode']
            db.session.commit()
            return jsonify(it.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── Aplicar plantilla a una parada (preview + commit) ──────────────────
    def _resolve_template_targets(item, area_ids_filter=None):
        """Resuelve la lista de equipos objetivo de un item segun su patron.
        area_ids_filter: si se pasa (lista de area_ids), filtra los equipos
        cuya area no este incluida (util para paradas PARCIAL).
        Retorna lista de Equipment.
        """
        import re as _re
        targets = []
        mode = item.application_mode
        if mode == 'specific_equipment' and item.target_equipment_id:
            eq = Equipment.query.get(item.target_equipment_id)
            if eq:
                targets = [eq]
        elif mode == 'area' and item.target_area_id:
            targets = (
                Equipment.query.join(Line, Equipment.line_id == Line.id)
                .filter(Line.area_id == item.target_area_id)
                .all()
            )
        elif mode == 'line' and item.target_line_id:
            targets = Equipment.query.filter_by(line_id=item.target_line_id).all()
        elif mode == 'tag_pattern' and item.target_tag_pattern:
            try:
                pat = _re.compile(item.target_tag_pattern)
            except Exception:
                pat = None
            if pat:
                all_eq = Equipment.query.all()
                targets = [e for e in all_eq if e.tag and pat.match(e.tag)]
        if area_ids_filter:
            allowed = set(int(x) for x in area_ids_filter)
            line_to_area = {l.id: l.area_id for l in Line.query.all()}
            targets = [
                e for e in targets
                if e.line_id and line_to_area.get(e.line_id) in allowed
            ]
        return targets

    @app.route('/api/shutdowns/<int:shutdown_id>/apply-template/<int:template_id>',
               methods=['POST'])
    def apply_template_to_shutdown(shutdown_id, template_id):
        """Aplica una plantilla a la parada. Comportamiento:
          - Si body tiene 'preview': true (default) → devuelve la lista de OTs
            candidatas con cruce (existing_in_shutdown / preventive_due / ok),
            sin crear nada.
          - Si body tiene 'commit': true → genera las OTs marcadas como
            selected (lista de keys 'item_id:equipment_id') y devuelve el
            resumen.
        """
        from models import (
            Shutdown, ShutdownTemplate, ShutdownTemplateItem,
            LubricationPoint, InspectionRoute, MonitoringPoint,
        )
        sh = Shutdown.query.get_or_404(shutdown_id)
        tpl = ShutdownTemplate.query.get_or_404(template_id)
        data = request.json or {}
        do_commit = bool(data.get('commit', False))

        # Areas de la parada (si es PARCIAL, filtramos equipos a esas areas)
        sh_area_ids = [sa.area_id for sa in sh.areas]
        area_filter = sh_area_ids if (sh.shutdown_type or '').upper() == 'PARCIAL' and sh_area_ids else None

        # OTs ya en la parada (para detectar duplicado)
        ots_in_shutdown = WorkOrder.query.filter_by(shutdown_id=shutdown_id).all()

        def matches_existing(desc, equipment_id):
            d_low = (desc or '').lower().strip()
            for ot in ots_in_shutdown:
                if ot.equipment_id != equipment_id:
                    continue
                ot_desc = (ot.description or '').lower().strip()
                # Coincidencia por substring fuerte (los primeros 30 chars suelen
                # ser distintivos)
                if not d_low or not ot_desc:
                    continue
                if d_low[:40] in ot_desc or ot_desc[:40] in d_low:
                    return ot
            return None

        # Preventivos proximos (ventana ±15d alrededor de la parada)
        try:
            shut_dt = datetime.strptime(sh.shutdown_date[:10], '%Y-%m-%d').date()
        except Exception:
            shut_dt = datetime.utcnow().date()
        from datetime import timedelta as _td
        win_start = (shut_dt - _td(days=15)).isoformat()
        win_end = (shut_dt + _td(days=30)).isoformat()

        # Indexar puntos preventivos por (equipment_id, component_id|None)
        # para poder cruzar al nivel de componente cuando esta disponible.
        prev_due_index = {}
        for cls, kind in ((LubricationPoint, 'lubrication'),
                          (InspectionRoute, 'inspection'),
                          (MonitoringPoint, 'monitoring')):
            try:
                rows = cls.query.filter(
                    cls.is_active == True,  # noqa: E712
                    cls.next_due_date.isnot(None),
                    cls.next_due_date >= win_start,
                    cls.next_due_date <= win_end,
                ).all()
            except Exception:
                rows = []
            for r in rows:
                eqid = getattr(r, 'equipment_id', None)
                if not eqid:
                    continue
                comp_id = getattr(r, 'component_id', None)
                comp_obj = getattr(r, 'component', None)
                prev_due_index.setdefault((eqid, comp_id), []).append({
                    'kind': kind,
                    'code': getattr(r, 'code', None) or getattr(r, 'name', '?'),
                    'name': getattr(r, 'name', None),
                    'due_date': r.next_due_date,
                    'component_name': comp_obj.name if comp_obj else None,
                })

        # Resolver componente fuzzy para cada (item, equipo). Cacheado para
        # evitar llamar al matcher dos veces (preview + posterior commit).
        try:
            from bot.telegram_bot import _smart_component_match
        except Exception:
            _smart_component_match = None
        from sqlalchemy import text as _sqltext
        comp_resolved = {}  # (item_id, eq_id) -> (comp_id, sys_id) o None

        def _resolve_comp(item, eq_id):
            key = (item.id, eq_id)
            if key in comp_resolved:
                return comp_resolved[key]
            res = None
            if item.component_name and _smart_component_match:
                try:
                    res = _smart_component_match(db, _sqltext, eq_id, item.component_name)
                except Exception:
                    res = None
            comp_resolved[key] = res
            return res

        # Heuristica: detectar si la descripcion del item habla de
        # lubricacion / inspeccion / monitoreo para no marcar warnings
        # ruidosos cuando no aplica.
        def _kinds_in_desc(desc):
            d = (desc or '').lower()
            kinds = set()
            if any(w in d for w in ('lubric', 'engras', 'engrasar', 'aceite', 'grasa', 'graseado')):
                kinds.add('lubrication')
            if any(w in d for w in ('inspec', 'revis', 'medic', 'verific', 'observ')):
                kinds.add('inspection')
            if any(w in d for w in ('monitore', 'tendenc', 'vibrac', 'temperatur', 'amperaj')):
                kinds.add('monitoring')
            return kinds

        # Construir candidatos
        equipments_cache = {e.id: e for e in Equipment.query.all()}
        lines_cache = {l.id: l for l in Line.query.all()}

        candidates = []
        for it in tpl.items:
            targets = _resolve_template_targets(it, area_filter)
            for eq in targets:
                desc_resolved = (it.description or '')
                desc_resolved = desc_resolved.replace('{tag}', eq.tag or '')
                desc_resolved = desc_resolved.replace('{name}', eq.name or '')
                desc_resolved = desc_resolved.strip()

                ln = lines_cache.get(eq.line_id) if eq.line_id else None
                area_id = ln.area_id if ln else None

                existing = matches_existing(desc_resolved, eq.id)

                # Cruce de preventivos REFINADO:
                # - Si el item tiene component_name resoluble → solo
                #   preventivos del MISMO componente cuentan.
                # - Sino, miramos preventivos del equipo cuya 'kind' matchee
                #   palabras clave en la descripcion (lubric/inspec/monitor).
                prev_warns = []
                comp_pair = _resolve_comp(it, eq.id)
                if comp_pair:
                    cid = comp_pair[0]
                    prev_warns = list(prev_due_index.get((eq.id, cid), []))
                else:
                    desc_kinds = _kinds_in_desc(it.description or desc_resolved)
                    if desc_kinds:
                        for (e_id, _c_id), lst in prev_due_index.items():
                            if e_id == eq.id:
                                prev_warns.extend(p for p in lst if p['kind'] in desc_kinds)

                status = 'ok'
                hint = None
                if existing:
                    status = 'duplicate'
                    hint = f"Ya existe OT {existing.code} en esta parada"
                elif prev_warns:
                    status = 'preventive_near'
                    parts = []
                    for p in prev_warns[:3]:
                        comp_part = f" [{p['component_name']}]" if p.get('component_name') else ''
                        parts.append(f"{p['code']}{comp_part} (vence {p['due_date']})")
                    hint = "Preventivo proximo: " + ' · '.join(parts)

                candidates.append({
                    'key': f"{it.id}:{eq.id}",
                    'item_id': it.id,
                    'description': desc_resolved,
                    'maintenance_type': it.maintenance_type,
                    'estimated_duration': it.estimated_duration,
                    'tech_count': it.tech_count,
                    'specialty': it.specialty,
                    'component_name': it.component_name,
                    'equipment_id': eq.id,
                    'equipment_tag': eq.tag,
                    'equipment_name': eq.name,
                    'line_id': eq.line_id,
                    'line_name': ln.name if ln else None,
                    'area_id': area_id,
                    'status': status,  # ok | duplicate | preventive_near
                    'hint': hint,
                    'item_description_template': it.description,
                })

        # ── Modo PREVIEW ────────────────────────────────────────────────
        if not do_commit:
            return jsonify({
                'shutdown': {
                    'id': sh.id, 'code': sh.code, 'name': sh.name,
                    'shutdown_date': sh.shutdown_date,
                    'shutdown_type': sh.shutdown_type,
                    'area_ids': sh_area_ids,
                },
                'template': {'id': tpl.id, 'name': tpl.name, 'item_count': len(tpl.items)},
                'candidates': candidates,
                'summary': {
                    'total': len(candidates),
                    'ok': sum(1 for c in candidates if c['status'] == 'ok'),
                    'duplicate': sum(1 for c in candidates if c['status'] == 'duplicate'),
                    'preventive_near': sum(1 for c in candidates if c['status'] == 'preventive_near'),
                },
            })

        # ── Modo COMMIT ─────────────────────────────────────────────────
        # selected_keys es lista de "item_id:equipment_id"
        selected_keys = set(data.get('selected_keys') or [])
        if not selected_keys:
            return jsonify({"error": "selected_keys requerido para commit"}), 400

        created = []
        skipped = []
        for c in candidates:
            if c['key'] not in selected_keys:
                continue
            if c['status'] == 'duplicate':
                skipped.append({'key': c['key'], 'reason': c['hint']})
                continue

            comp_id = sys_id = None
            it = next((i for i in tpl.items if i.id == c['item_id']), None)
            if it:
                pair = comp_resolved.get((it.id, c['equipment_id']))
                if pair:
                    comp_id, sys_id = pair

            wo = WorkOrder(
                description=c['description'],
                maintenance_type=c['maintenance_type'] or 'Preventivo',
                status='Programada',
                scheduled_date=sh.shutdown_date,
                estimated_duration=c['estimated_duration'],
                tech_count=c['tech_count'] or 1,
                area_id=c['area_id'],
                line_id=c['line_id'],
                equipment_id=c['equipment_id'],
                system_id=sys_id,
                component_id=comp_id,
                shutdown_id=shutdown_id,
            )
            db.session.add(wo)
            db.session.flush()
            wo.code = f"OT-{wo.id:04d}"
            created.append({'code': wo.code, 'description': wo.description,
                            'equipment_tag': c['equipment_tag']})

        db.session.commit()
        return jsonify({
            'ok': True,
            'created': created,
            'skipped': skipped,
            'created_count': len(created),
            'skipped_count': len(skipped),
        }), 201
