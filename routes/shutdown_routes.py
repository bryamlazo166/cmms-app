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
