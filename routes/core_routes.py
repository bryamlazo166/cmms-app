import datetime as dt
from collections import defaultdict

from flask import jsonify, redirect, render_template, request, url_for


def register_core_routes(app, db, logger, app_build_tag,
                         WorkOrder, MaintenanceNotice, Technician,
                         Area, Line, Equipment, OTPersonnel,
                         _parse_date_flexible, _safe_duration_hours,
                         LubricationPoint=None, LubricationExecution=None,
                         InspectionRoute=None, InspectionExecution=None,
                         MonitoringPoint=None, MonitoringReading=None,
                         Notification=None, WarehouseItem=None,
                         _calculate_lubrication_schedule=None,
                         FailureCatalog=None):
    @app.route('/configuracion')
    def taxonomy_page():
        return render_template('taxonomy.html')

    @app.route('/api/system/db-status', methods=['GET'])
    def get_db_status():
        return jsonify({
            "mode": app.config.get("CMMS_DB_MODE", "unknown"),
            "uri_masked": app.config.get("CMMS_DB_URI_MASKED"),
            "build": app_build_tag,
        })

    @app.route('/health', methods=['GET'])
    def health_check():
        """Uptime check for Render / external monitors. No auth required."""
        try:
            db.session.execute(db.text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        status = 200 if db_ok else 503
        return jsonify({
            "status": "ok" if db_ok else "degraded",
            "db": "connected" if db_ok else "unreachable",
            "build": app_build_tag,
        }), status

    @app.route('/api/dashboard-stats', methods=['GET'])
    def dashboard_stats():
        try:
            total_ots_open = WorkOrder.query.filter(WorkOrder.status != 'Cerrada').count()
            total_ots_closed = WorkOrder.query.filter_by(status='Cerrada').count()
            notices_pending = MaintenanceNotice.query.filter_by(status='Pendiente').count()
            active_techs = Technician.query.filter_by(is_active=True).count()

            status_counts = db.session.query(WorkOrder.status, db.func.count(WorkOrder.status)).group_by(WorkOrder.status).all()
            status_data = {status: count for status, count in status_counts}

            type_counts = db.session.query(WorkOrder.maintenance_type, db.func.count(WorkOrder.maintenance_type)).group_by(WorkOrder.maintenance_type).all()
            type_data = {mtype: count for mtype, count in type_counts}

            failures = (
                db.session.query(WorkOrder.failure_mode, db.func.count(WorkOrder.failure_mode))
                .filter(WorkOrder.failure_mode != None, WorkOrder.failure_mode != "")
                .group_by(WorkOrder.failure_mode)
                .order_by(db.func.count(WorkOrder.failure_mode).desc())
                .limit(5)
                .all()
            )
            failure_data = [{'mode': failure_mode, 'count': count} for failure_mode, count in failures]

            recent_ots = WorkOrder.query.order_by(WorkOrder.id.desc()).limit(5).all()
            recent_data = []
            for ot in recent_ots:
                eq = Equipment.query.get(ot.equipment_id) if ot.equipment_id else None
                eq_label = f"{eq.tag or ''} {eq.name}".strip() if eq else None
                desc = ot.description or ot.failure_mode or eq_label or ot.maintenance_type or '-'
                recent_data.append({
                    'code': ot.code,
                    'description': desc,
                    'equipment': eq_label,
                    'status': ot.status,
                    'date': ot.scheduled_date or ot.real_start_date,
                })

            return jsonify(
                {
                    'kpi': {
                        'open_ots': total_ots_open,
                        'closed_ots': total_ots_closed,
                        'pending_notices': notices_pending,
                        'active_techs': active_techs,
                    },
                    'charts': {
                        'status': status_data,
                        'types': type_data,
                        'failures': failure_data,
                    },
                    'recent': recent_data,
                }
            )
        except Exception as e:
            logger.error(f"Dashboard Stats Error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/avisos')
    def notices_page():
        return render_template('notices.html')

    @app.route('/ordenes')
    def work_orders_page():
        return render_template('work_orders.html')

    @app.route('/almacen')
    def warehouse_page():
        return render_template('warehouse.html')

    @app.route('/reportes')
    def reports_page():
        return render_template('reports.html')

    @app.route('/lubricacion')
    def lubrication_page():
        return render_template('lubrication.html')

    @app.route('/monitoreo')
    def monitoring_page():
        return render_template('monitoring.html')

    @app.route('/inspecciones')
    def inspections_page():
        return render_template('inspections.html')

    @app.route('/espesores')
    def thickness_page():
        return render_template('thickness.html')

    @app.route('/cockpit')
    def cockpit_page():
        return render_template('cockpit.html')

    @app.route('/paradas')
    def shutdowns_page():
        return render_template('shutdowns.html')

    @app.route('/indicadores')
    def indicators_page():
        return render_template('indicators.html')

    @app.route('/activos-rotativos')
    def rotative_assets_page():
        return render_template('rotative_assets.html')

    @app.route('/herramientas')
    def tools_page():
        return render_template('tools.html')

    @app.route('/compras')
    def purchasing_page():
        return render_template('purchasing.html')

    @app.route('/seguimiento')
    def activities_page():
        return render_template('activities.html')

    @app.route('/equipo-historial')
    def equipment_history_page():
        return render_template('equipment_history.html')

    # ── Equipment consolidated history ─────────────────────────────────────

    @app.route('/api/equipment/<int:equip_id>/history', methods=['GET'])
    def get_equipment_history(equip_id):
        try:
            eq = Equipment.query.get(equip_id)
            if not eq:
                return jsonify({"error": "Equipo no encontrado"}), 404

            ln = Line.query.get(eq.line_id) if eq.line_id else None
            ar = Area.query.get(ln.area_id) if ln and ln.area_id else None
            equip_info = {
                'id': eq.id, 'name': eq.name, 'tag': eq.tag,
                'line': ln.name if ln else None,
                'area': ar.name if ar else None,
            }

            events = []

            # 1. Work Orders
            ots = WorkOrder.query.filter_by(equipment_id=equip_id).order_by(WorkOrder.id.desc()).all()
            for ot in ots:
                events.append({
                    'date': ot.real_start_date or ot.scheduled_date or '',
                    'category': 'OT',
                    'code': ot.code,
                    'type': ot.maintenance_type,
                    'status': ot.status,
                    'description': ot.description,
                    'failure_mode': ot.failure_mode,
                    'duration_h': _safe_duration_hours(ot.real_duration),
                    'source_type': getattr(ot, 'source_type', None),
                })

            # 2. Maintenance Notices
            notices = MaintenanceNotice.query.filter_by(equipment_id=equip_id).order_by(MaintenanceNotice.id.desc()).all()
            for n in notices:
                events.append({
                    'date': n.request_date or '',
                    'category': 'AVISO',
                    'code': n.code,
                    'type': n.maintenance_type,
                    'status': n.status,
                    'description': n.description,
                    'failure_mode': None,
                    'duration_h': None,
                    'source_type': getattr(n, 'source_type', None),
                })

            # 3. Lubrication
            if LubricationExecution and LubricationPoint:
                lub_points = LubricationPoint.query.filter_by(equipment_id=equip_id).all()
                lub_ids = [p.id for p in lub_points]
                lub_map = {p.id: p for p in lub_points}
                if lub_ids:
                    execs = LubricationExecution.query.filter(
                        LubricationExecution.point_id.in_(lub_ids)
                    ).order_by(LubricationExecution.id.desc()).all()
                    for e in execs:
                        pt = lub_map.get(e.point_id)
                        events.append({
                            'date': e.execution_date or '',
                            'category': 'LUBRICACION',
                            'code': pt.code if pt else None,
                            'type': e.action_type,
                            'status': f"{'Fuga' if e.leak_detected else ''}{'Anomalia' if e.anomaly_detected else ''}".strip() or 'Normal',
                            'description': f"{pt.name if pt else ''}: {pt.lubricant_name if pt else ''} {e.quantity_used or ''} {e.quantity_unit or ''}".strip(),
                            'failure_mode': None,
                            'duration_h': None,
                            'source_type': None,
                        })

            # 4. Inspections
            if InspectionExecution and InspectionRoute:
                insp_routes = InspectionRoute.query.filter_by(equipment_id=equip_id).all()
                route_ids = [r.id for r in insp_routes]
                route_map = {r.id: r for r in insp_routes}
                if route_ids:
                    execs = InspectionExecution.query.filter(
                        InspectionExecution.route_id.in_(route_ids)
                    ).order_by(InspectionExecution.id.desc()).all()
                    for e in execs:
                        rt = route_map.get(e.route_id)
                        events.append({
                            'date': e.execution_date or '',
                            'category': 'INSPECCION',
                            'code': rt.code if rt else None,
                            'type': e.overall_result,
                            'status': f"{e.findings_count} hallazgo(s)" if e.findings_count else 'OK',
                            'description': rt.name if rt else '',
                            'failure_mode': None,
                            'duration_h': None,
                            'source_type': None,
                        })

            # 5. Monitoring readings
            if MonitoringReading and MonitoringPoint:
                mon_points = MonitoringPoint.query.filter_by(equipment_id=equip_id).all()
                mon_ids = [p.id for p in mon_points]
                mon_map = {p.id: p for p in mon_points}
                if mon_ids:
                    readings = MonitoringReading.query.filter(
                        MonitoringReading.point_id.in_(mon_ids)
                    ).order_by(MonitoringReading.id.desc()).limit(100).all()
                    for r in readings:
                        pt = mon_map.get(r.point_id)
                        events.append({
                            'date': r.reading_date or '',
                            'category': 'MONITOREO',
                            'code': pt.code if pt else None,
                            'type': pt.measurement_type if pt else None,
                            'status': f"{r.value} {pt.unit if pt else ''}".strip(),
                            'description': pt.name if pt else '',
                            'failure_mode': None,
                            'duration_h': None,
                            'source_type': None,
                        })

            # Sort all events by date descending
            events.sort(key=lambda e: e.get('date') or '', reverse=True)

            return jsonify({
                'equipment': equip_info,
                'events': events[:200],
                'counts': {
                    'ots': len([e for e in events if e['category'] == 'OT']),
                    'avisos': len([e for e in events if e['category'] == 'AVISO']),
                    'lubricacion': len([e for e in events if e['category'] == 'LUBRICACION']),
                    'inspeccion': len([e for e in events if e['category'] == 'INSPECCION']),
                    'monitoreo': len([e for e in events if e['category'] == 'MONITOREO']),
                }
            })
        except Exception as e:
            logger.exception("Equipment history error")
            return jsonify({"error": str(e)}), 500

    # ── KPI Dashboard — MTTR, MTBF, Availability per equipment/line/area ──

    @app.route('/api/dashboard-kpis', methods=['GET'])
    def dashboard_kpis():
        try:
            # Time window
            days = int(request.args.get('days', 90))
            level = request.args.get('level', 'equipment')  # equipment | line | area
            area_id = request.args.get('area_id', type=int)
            line_id = request.args.get('line_id', type=int)

            cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
            calendar_hours = days * 24

            # Pre-load hierarchy maps
            areas_map = {a.id: a.name for a in Area.query.all()}
            lines_map = {l.id: {'name': l.name, 'area_id': l.area_id} for l in Line.query.all()}
            equips_all = Equipment.query.all()
            equips_map = {}
            for e in equips_all:
                l = lines_map.get(e.line_id, {})
                equips_map[e.id] = {
                    'name': e.name, 'tag': e.tag, 'criticality': e.criticality,
                    'line_id': e.line_id, 'line_name': l.get('name'),
                    'area_id': l.get('area_id'), 'area_name': areas_map.get(l.get('area_id')),
                }

            # Fetch closed corrective OTs within window
            query = WorkOrder.query.filter(
                WorkOrder.status == 'Cerrada',
                WorkOrder.equipment_id.isnot(None),
            )
            # Filter by date: use scheduled_date or real_start_date
            all_ots = query.all()
            ots_in_window = []
            for ot in all_ots:
                d = _parse_date_flexible(ot.real_start_date or ot.scheduled_date)
                if d and d.isoformat() >= cutoff:
                    ots_in_window.append(ot)

            # Filter by hierarchy
            if area_id:
                ots_in_window = [ot for ot in ots_in_window
                                 if equips_map.get(ot.equipment_id, {}).get('area_id') == area_id]
            if line_id:
                ots_in_window = [ot for ot in ots_in_window
                                 if equips_map.get(ot.equipment_id, {}).get('line_id') == line_id]

            # ── Group by level ────────────────────────────────────────────
            groups = defaultdict(lambda: {
                'failures': 0, 'total_repair_h': 0, 'downtime_h': 0,
                'preventive': 0, 'corrective': 0, 'ots': [],
                'downtime_events': 0,
            })

            for ot in ots_in_window:
                eq_info = equips_map.get(ot.equipment_id, {})
                if level == 'equipment':
                    key = ot.equipment_id
                    label = f"{eq_info.get('tag') or ''} {eq_info.get('name', '?')}".strip()
                elif level == 'line':
                    key = eq_info.get('line_id')
                    label = eq_info.get('line_name') or '(Sin Linea)'
                else:
                    key = eq_info.get('area_id')
                    label = eq_info.get('area_name') or '(Sin Area)'

                if not key:
                    continue

                g = groups[key]
                g['label'] = label
                g['id'] = key

                mtype = (ot.maintenance_type or '').lower()
                is_corrective = 'correct' in mtype

                if is_corrective:
                    g['corrective'] += 1
                    g['failures'] += 1
                else:
                    g['preventive'] += 1

                # Repair time
                repair_h = _safe_duration_hours(ot.real_duration)
                if not repair_h:
                    rs = _parse_date_flexible(ot.real_start_date)
                    re = _parse_date_flexible(ot.real_end_date)
                    if rs and re:
                        repair_h = round((re - rs).total_seconds() / 3600, 2)
                g['total_repair_h'] += (repair_h or 0)

                # Downtime
                dh = getattr(ot, 'downtime_hours', None)
                if dh:
                    g['downtime_h'] += dh
                    g['downtime_events'] += 1
                elif getattr(ot, 'caused_downtime', False) and repair_h:
                    g['downtime_h'] += repair_h
                    g['downtime_events'] += 1
                elif is_corrective and repair_h:
                    # Default: corrective OTs count as downtime
                    g['downtime_h'] += repair_h
                    g['downtime_events'] += 1

                g['ots'].append({
                    'code': ot.code,
                    'date': ot.real_start_date or ot.scheduled_date,
                    'type': ot.maintenance_type,
                    'failure_mode': ot.failure_mode,
                    'repair_h': repair_h,
                    'downtime_h': dh or repair_h if is_corrective else 0,
                    'equipment': f"{eq_info.get('tag', '')} {eq_info.get('name', '')}".strip(),
                    'description': ot.description,
                })

            # ── Calculate KPIs per group ──────────────────────────────────
            result = []
            totals = {'failures': 0, 'repair_h': 0, 'downtime_h': 0,
                       'preventive': 0, 'corrective': 0}

            for key, g in groups.items():
                n_fail = g['failures']
                t_repair = g['total_repair_h']
                t_down = g['downtime_h']
                t_up = max(calendar_hours - t_down, 0)

                mtbf = round(t_up / n_fail, 1) if n_fail > 0 else None
                mttr = round(t_repair / n_fail, 1) if n_fail > 0 else None
                availability = round((t_up / calendar_hours) * 100, 1) if calendar_hours > 0 else 100
                # Reliability R(t) = e^(-t/MTBF) for mission time = frequency (e.g. 168h = 1 week)
                reliability = None
                if mtbf and mtbf > 0:
                    import math
                    mission_t = 168  # 1 week
                    reliability = round(math.exp(-mission_t / mtbf) * 100, 1)

                ratio_pc = None
                total_ots = g['preventive'] + g['corrective']
                if total_ots > 0:
                    ratio_pc = round((g['preventive'] / total_ots) * 100, 1)

                result.append({
                    'id': g['id'],
                    'label': g['label'],
                    'failures': n_fail,
                    'preventive': g['preventive'],
                    'corrective': g['corrective'],
                    'total_ots': total_ots,
                    'repair_hours': round(t_repair, 1),
                    'downtime_hours': round(t_down, 1),
                    'mtbf': mtbf,
                    'mttr': mttr,
                    'availability': availability,
                    'reliability': reliability,
                    'ratio_preventive': ratio_pc,
                    'ots': sorted(g['ots'], key=lambda x: x.get('date') or '', reverse=True),
                })

                totals['failures'] += n_fail
                totals['repair_h'] += t_repair
                totals['downtime_h'] += t_down
                totals['preventive'] += g['preventive']
                totals['corrective'] += g['corrective']

            result.sort(key=lambda x: x['availability'] if x['availability'] is not None else 999)

            # Global KPIs
            tf = totals['failures']
            tr = totals['repair_h']
            td = totals['downtime_h']
            tu = max(calendar_hours - td, 0)

            global_kpis = {
                'calendar_hours': calendar_hours,
                'days': days,
                'total_ots': totals['preventive'] + totals['corrective'],
                'total_failures': tf,
                'total_preventive': totals['preventive'],
                'total_corrective': totals['corrective'],
                'global_mtbf': round(tu / tf, 1) if tf > 0 else None,
                'global_mttr': round(tr / tf, 1) if tf > 0 else None,
                'global_availability': round((tu / calendar_hours) * 100, 1) if calendar_hours > 0 else 100,
                'global_downtime_h': round(td, 1),
                'ratio_preventive': round((totals['preventive'] / (totals['preventive'] + totals['corrective'])) * 100, 1) if (totals['preventive'] + totals['corrective']) > 0 else 0,
            }

            # Hierarchy for filters
            areas_list = [{'id': a.id, 'name': a.name} for a in Area.query.order_by(Area.name).all()]
            lines_list = [{'id': l.id, 'name': l.name, 'area_id': l.area_id}
                          for l in Line.query.order_by(Line.name).all()]

            return jsonify({
                'kpis': global_kpis,
                'items': result,
                'areas': areas_list,
                'lines': lines_list,
            })
        except Exception as e:
            logger.exception("Dashboard KPIs error")
            return jsonify({"error": str(e)}), 500

    # ── Photo Attachments ────────────────────────────────────────────────

    @app.route('/api/photos/<entity_type>/<int:entity_id>', methods=['GET', 'POST'])
    def handle_photos(entity_type, entity_id):
        if entity_type not in ('notice', 'work_order'):
            return jsonify({"error": "entity_type debe ser notice o work_order."}), 400

        if request.method == 'POST':
            try:
                from models import PhotoAttachment
                from utils.photo_helpers import compress_photo, upload_to_supabase_storage, MAX_FILE_SIZE

                MAX_PHOTOS = {'notice': 3, 'work_order': 10}
                current_count = PhotoAttachment.query.filter_by(
                    entity_type=entity_type, entity_id=entity_id
                ).count()
                limit = MAX_PHOTOS.get(entity_type, 10)
                if current_count >= limit:
                    return jsonify({"error": f"Maximo {limit} fotos por {entity_type}."}), 400

                if 'photo' not in request.files:
                    return jsonify({"error": "No se envio archivo. Campo: photo"}), 400

                file = request.files['photo']
                if not file.filename:
                    return jsonify({"error": "Archivo vacio."}), 400

                raw = file.read()
                if len(raw) > MAX_FILE_SIZE:
                    return jsonify({"error": f"Archivo muy grande. Maximo {MAX_FILE_SIZE // (1024*1024)}MB."}), 400

                original_kb = len(raw) // 1024

                # Compress
                compressed, dimensions = compress_photo(raw)
                compressed_kb = len(compressed) // 1024

                # Upload to Supabase Storage
                url = upload_to_supabase_storage(compressed, file.filename)

                caption = request.form.get('caption', '').strip() or None

                photo = PhotoAttachment(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    url=url,
                    caption=caption,
                    original_size_kb=original_kb,
                    compressed_size_kb=compressed_kb,
                )
                db.session.add(photo)
                db.session.commit()
                return jsonify(photo.to_dict()), 201
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400
            except Exception as e:
                db.session.rollback()
                logger.exception("Photo upload error")
                return jsonify({"error": str(e)}), 500

        # GET
        from models import PhotoAttachment
        photos = PhotoAttachment.query.filter_by(
            entity_type=entity_type, entity_id=entity_id
        ).order_by(PhotoAttachment.id.desc()).all()
        return jsonify([p.to_dict() for p in photos])

    @app.route('/api/photos/<int:photo_id>', methods=['DELETE'])
    def delete_photo(photo_id):
        from models import PhotoAttachment
        from utils.photo_helpers import delete_from_supabase_storage
        photo = PhotoAttachment.query.get_or_404(photo_id)
        delete_from_supabase_storage(photo.url)
        db.session.delete(photo)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Photo Share (signed temporary link) ──────────────────────────────
    import hashlib, hmac, time as _time

    _PHOTO_SHARE_SECRET = (os.getenv('SECRET_KEY') or 'cmms-photo-share-2026').encode()
    _PHOTO_SHARE_TTL = 86400  # 24 horas

    def _sign_photo_token(photo_id, expires):
        payload = f"{photo_id}:{expires}".encode()
        sig = hmac.new(_PHOTO_SHARE_SECRET, payload, hashlib.sha256).hexdigest()[:16]
        return sig

    @app.route('/api/photo-share/generate/<entity_type>/<int:entity_id>', methods=['GET'])
    def generate_photo_share_link(entity_type, entity_id):
        """Genera un link temporal firmado para la primera foto de un aviso/OT."""
        from models import PhotoAttachment
        photo = PhotoAttachment.query.filter_by(
            entity_type=entity_type, entity_id=entity_id
        ).order_by(PhotoAttachment.id.desc()).first()
        if not photo:
            return jsonify({"url": None, "message": "Sin fotos"})
        expires = int(_time.time()) + _PHOTO_SHARE_TTL
        sig = _sign_photo_token(photo.id, expires)
        share_url = f"/api/photo-view/{photo.id}/{expires}/{sig}"
        return jsonify({"url": share_url, "photo_id": photo.id, "expires_in": _PHOTO_SHARE_TTL})

    @app.route('/api/photo-view/<int:photo_id>/<int:expires>/<sig>', methods=['GET'])
    def view_shared_photo(photo_id, expires, sig):
        """Sirve una foto compartida si el token es válido y no expiró."""
        # Validar firma
        expected_sig = _sign_photo_token(photo_id, expires)
        if not hmac.compare_digest(sig, expected_sig):
            return "<h2>Link inválido</h2><p>Este enlace de foto no es válido.</p>", 403
        # Validar expiración
        if _time.time() > expires:
            return "<h2>Link expirado</h2><p>Este enlace de foto expiró. Solicita uno nuevo desde el CMMS.</p>", 410
        # Buscar foto
        from models import PhotoAttachment
        photo = PhotoAttachment.query.get(photo_id)
        if not photo or not photo.url:
            return "<h2>Foto no encontrada</h2>", 404
        # Redirigir a la URL real de la foto en Storage
        from flask import redirect
        return redirect(photo.url)

    # ── Technical Specs (Equipment & Component) ──────────────────────────

    @app.route('/api/specs/<entity_type>/<int:entity_id>', methods=['GET', 'POST'])
    def handle_specs(entity_type, entity_id):
        from models import EquipmentSpec, ComponentSpec
        MODEL_MAP = {'equipment': EquipmentSpec, 'component': ComponentSpec}
        FK_MAP = {'equipment': 'equipment_id', 'component': 'component_id'}

        if entity_type not in MODEL_MAP:
            return jsonify({"error": "entity_type debe ser equipment o component"}), 400

        Model = MODEL_MAP[entity_type]
        fk = FK_MAP[entity_type]

        if request.method == 'POST':
            data = request.get_json()
            spec = Model(**{fk: entity_id, 'key_name': data['key_name'], 'value_text': data['value_text'], 'unit': data.get('unit', '')})
            max_order = db.session.query(db.func.max(Model.order_index)).filter(getattr(Model, fk) == entity_id).scalar() or 0
            spec.order_index = max_order + 1
            db.session.add(spec)
            db.session.commit()
            return jsonify(spec.to_dict()), 201

        specs = Model.query.filter(getattr(Model, fk) == entity_id).order_by(Model.order_index).all()
        return jsonify([s.to_dict() for s in specs])

    @app.route('/api/specs/<entity_type>/<int:spec_id>/update', methods=['PUT'])
    def update_spec(entity_type, spec_id):
        from models import EquipmentSpec, ComponentSpec
        MODEL_MAP = {'equipment': EquipmentSpec, 'component': ComponentSpec}
        if entity_type not in MODEL_MAP:
            return jsonify({"error": "entity_type invalido"}), 400
        spec = MODEL_MAP[entity_type].query.get_or_404(spec_id)
        data = request.get_json()
        if data.get('key_name'):
            spec.key_name = data['key_name']
        if data.get('value_text'):
            spec.value_text = data['value_text']
        if 'unit' in data:
            spec.unit = data['unit']
        db.session.commit()
        return jsonify(spec.to_dict())

    @app.route('/api/specs/<entity_type>/<int:spec_id>/delete', methods=['DELETE'])
    def delete_spec(entity_type, spec_id):
        from models import EquipmentSpec, ComponentSpec
        MODEL_MAP = {'equipment': EquipmentSpec, 'component': ComponentSpec}
        if entity_type not in MODEL_MAP:
            return jsonify({"error": "entity_type invalido"}), 400
        spec = MODEL_MAP[entity_type].query.get_or_404(spec_id)
        db.session.delete(spec)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Document Links ──────────────────────────────────────────────────

    @app.route('/api/doc-links/<entity_type>/<int:entity_id>', methods=['GET', 'POST'])
    def handle_doc_links(entity_type, entity_id):
        from models import DocumentLink
        if entity_type not in ('equipment', 'component', 'rotative_asset'):
            return jsonify({"error": "entity_type debe ser equipment, component o rotative_asset"}), 400

        if request.method == 'POST':
            data = request.get_json()
            doc = DocumentLink(
                entity_type=entity_type, entity_id=entity_id,
                title=data['title'], url=data['url'],
                doc_type=data.get('doc_type', 'otro')
            )
            db.session.add(doc)
            db.session.commit()
            return jsonify(doc.to_dict()), 201

        docs = DocumentLink.query.filter_by(entity_type=entity_type, entity_id=entity_id).order_by(DocumentLink.id.desc()).all()
        return jsonify([d.to_dict() for d in docs])

    @app.route('/api/doc-links/<int:doc_id>', methods=['DELETE'])
    def delete_doc_link(doc_id):
        from models import DocumentLink
        doc = DocumentLink.query.get_or_404(doc_id)
        db.session.delete(doc)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Failure Recurrence Dashboard ────────────────────────────────────

    @app.route('/api/failure-recurrence', methods=['GET'])
    def failure_recurrence():
        """Top components/equipment with most corrective WOs in a period."""
        from sqlalchemy import func
        months = int(request.args.get('months', 6))
        limit_n = int(request.args.get('limit', 20))
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=months * 30)

        # Top components by corrective OT count
        results = db.session.query(
            WorkOrder.component_id,
            func.count(WorkOrder.id).label('wo_count'),
            func.max(WorkOrder.created_at).label('last_wo'),
        ).filter(
            WorkOrder.maintenance_type == 'Correctivo',
            WorkOrder.created_at >= cutoff,
            WorkOrder.component_id.isnot(None),
        ).group_by(WorkOrder.component_id).order_by(func.count(WorkOrder.id).desc()).limit(limit_n).all()

        from models import Component as Comp, System as Sys, Equipment as Eq, Line as Ln
        data = []
        for comp_id, count, last_wo in results:
            comp = Comp.query.get(comp_id)
            if not comp:
                continue
            sys_obj = Sys.query.get(comp.system_id) if comp else None
            eq_obj = Eq.query.get(sys_obj.equipment_id) if sys_obj else None
            ln_obj = Ln.query.get(eq_obj.line_id) if eq_obj else None

            days_span = (dt.datetime.utcnow() - cutoff).days
            mtbf_days = round(days_span / count, 1) if count > 1 else None

            data.append({
                "component_id": comp_id,
                "component_name": comp.name if comp else '?',
                "system_name": sys_obj.name if sys_obj else '?',
                "equipment_name": eq_obj.name if eq_obj else '?',
                "equipment_tag": eq_obj.tag if eq_obj else '?',
                "line_name": ln_obj.name if ln_obj else '?',
                "wo_count": count,
                "last_wo": last_wo.isoformat() if last_wo else None,
                "mtbf_days": mtbf_days,
            })

        # Top equipment
        eq_results = db.session.query(
            WorkOrder.equipment_id,
            func.count(WorkOrder.id).label('wo_count'),
        ).filter(
            WorkOrder.maintenance_type == 'Correctivo',
            WorkOrder.created_at >= cutoff,
            WorkOrder.equipment_id.isnot(None),
        ).group_by(WorkOrder.equipment_id).order_by(func.count(WorkOrder.id).desc()).limit(10).all()

        eq_data = []
        for eq_id, count in eq_results:
            eq = Eq.query.get(eq_id)
            eq_data.append({
                "equipment_id": eq_id,
                "equipment_name": eq.name if eq else '?',
                "equipment_tag": eq.tag if eq else '?',
                "wo_count": count,
            })

        return jsonify({"by_component": data, "by_equipment": eq_data, "months": months})

    # ── Failure Catalog (Catalogo de Fallas) ──────────────────────────────

    @app.route('/api/failure-catalog', methods=['GET'])
    def get_failure_catalog():
        """List all active failure catalog entries ordered by usage_count desc."""
        if FailureCatalog is None:
            return jsonify({"error": "FailureCatalog not available"}), 501
        entries = FailureCatalog.query.filter_by(is_active=True).order_by(
            FailureCatalog.usage_count.desc()
        ).all()
        return jsonify([e.to_dict() for e in entries])

    @app.route('/api/failure-catalog', methods=['POST'])
    def create_failure_catalog():
        """Create a new failure catalog entry."""
        if FailureCatalog is None:
            return jsonify({"error": "FailureCatalog not available"}), 501
        data = request.get_json(force=True)
        entry = FailureCatalog(
            failure_mode=data.get('failure_mode', '').strip(),
            failure_category=data.get('failure_category', '').strip(),
            description=data.get('description'),
            recommended_action=data.get('recommended_action'),
            is_active=data.get('is_active', True),
            usage_count=data.get('usage_count', 0),
        )
        if not entry.failure_mode or not entry.failure_category:
            return jsonify({"error": "failure_mode and failure_category are required"}), 400
        db.session.add(entry)
        db.session.commit()
        return jsonify(entry.to_dict()), 201

    @app.route('/api/failure-catalog/<int:entry_id>', methods=['PUT'])
    def update_failure_catalog(entry_id):
        """Update an existing failure catalog entry."""
        if FailureCatalog is None:
            return jsonify({"error": "FailureCatalog not available"}), 501
        entry = FailureCatalog.query.get_or_404(entry_id)
        data = request.get_json(force=True)
        if 'failure_mode' in data:
            entry.failure_mode = data['failure_mode'].strip()
        if 'failure_category' in data:
            entry.failure_category = data['failure_category'].strip()
        if 'description' in data:
            entry.description = data['description']
        if 'recommended_action' in data:
            entry.recommended_action = data['recommended_action']
        if 'is_active' in data:
            entry.is_active = data['is_active']
        if 'usage_count' in data:
            entry.usage_count = data['usage_count']
        db.session.commit()
        return jsonify(entry.to_dict())

    @app.route('/api/failure-catalog/<int:entry_id>', methods=['DELETE'])
    def delete_failure_catalog(entry_id):
        """Soft-delete a failure catalog entry (set is_active=False)."""
        if FailureCatalog is None:
            return jsonify({"error": "FailureCatalog not available"}), 501
        entry = FailureCatalog.query.get_or_404(entry_id)
        entry.is_active = False
        db.session.commit()
        return jsonify({"ok": True, "id": entry_id})

    @app.route('/api/failure-catalog/increment/<int:entry_id>', methods=['POST'])
    def increment_failure_catalog(entry_id):
        """Increment the usage_count for a failure catalog entry."""
        if FailureCatalog is None:
            return jsonify({"error": "FailureCatalog not available"}), 501
        entry = FailureCatalog.query.get_or_404(entry_id)
        entry.usage_count = (entry.usage_count or 0) + 1
        db.session.commit()
        return jsonify(entry.to_dict())

    @app.route('/api/failure-catalog/seed', methods=['POST'])
    def seed_failure_catalog():
        """Seed the failure catalog with common failure modes (only if table is empty)."""
        if FailureCatalog is None:
            return jsonify({"error": "FailureCatalog not available"}), 501
        existing = FailureCatalog.query.first()
        if existing:
            return jsonify({"message": "Catalog already has entries, seed skipped",
                            "count": FailureCatalog.query.count()}), 200
        defaults = [
            ("Rotura", "Mecanica"),
            ("Desgaste", "Mecanica"),
            ("Fuga", "Mecanica"),
            ("Desalineacion", "Mecanica"),
            ("Desbalanceo", "Mecanica"),
            ("Sobrecalentamiento", "Mecanica"),
            ("Ruido anormal", "Mecanica"),
            ("Vibracion excesiva", "Mecanica"),
            ("Aflojamiento", "Mecanica"),
            ("Corrosion", "Mecanica"),
            ("Atascamiento", "Mecanica"),
            ("Descarrilamiento", "Mecanica"),
            ("Fatiga", "Mecanica"),
            ("Deformacion", "Mecanica"),
            ("Cortocircuito", "Electrica"),
            ("Sobrecarga", "Electrica"),
            ("Falla de aislamiento", "Electrica"),
            ("Fuga hidraulica", "Hidraulica"),
            ("Fuga neumatica", "Neumatica"),
            ("Falla de sensor", "Instrumentacion"),
            ("Falta de lubricacion", "Lubricacion"),
            ("Contaminacion de lubricante", "Lubricacion"),
            ("Fractura estructural", "Estructural"),
        ]
        for mode, category in defaults:
            db.session.add(FailureCatalog(failure_mode=mode, failure_category=category))
        db.session.commit()
        return jsonify({"message": "Catalog seeded", "count": len(defaults)}), 201

    # ── KPI Trends + Costs ───────────────────────────────────────────────

    @app.route('/api/dashboard-trends', methods=['GET'])
    def dashboard_trends():
        """Monthly KPI trends + cost breakdown for last N months."""
        try:
            months = int(request.args.get('months', 12))
            today = dt.date.today()

            # Build month buckets
            month_buckets = []
            for i in range(months - 1, -1, -1):
                d = today.replace(day=1) - dt.timedelta(days=i * 30)
                m_start = d.replace(day=1)
                if m_start.month == 12:
                    m_end = m_start.replace(year=m_start.year + 1, month=1, day=1)
                else:
                    m_end = m_start.replace(month=m_start.month + 1, day=1)
                month_buckets.append({
                    'label': m_start.strftime('%Y-%m'),
                    'start': m_start, 'end': m_end,
                })

            # Filter params
            f_area = request.args.get('area_id', type=int)
            f_line = request.args.get('line_id', type=int)
            f_equip = request.args.get('equipment_id', type=int)

            # Load closed OTs with optional filters
            q = WorkOrder.query.filter(WorkOrder.status == 'Cerrada')
            if f_equip:
                q = q.filter(WorkOrder.equipment_id == f_equip)
            elif f_line:
                # Get all equipments in this line
                eq_ids = [e.id for e in Equipment.query.filter_by(line_id=f_line).all()]
                if eq_ids:
                    q = q.filter(WorkOrder.equipment_id.in_(eq_ids))
                else:
                    q = q.filter(db.literal(False))
            elif f_area:
                # Get all lines in area, then all equipments
                ln_ids = [l.id for l in Line.query.filter_by(area_id=f_area).all()]
                if ln_ids:
                    eq_ids = [e.id for e in Equipment.query.filter(Equipment.line_id.in_(ln_ids)).all()]
                    if eq_ids:
                        q = q.filter(WorkOrder.equipment_id.in_(eq_ids))
                    else:
                        q = q.filter(db.literal(False))
                else:
                    q = q.filter(db.literal(False))
            all_ots = q.all()
            # Load personnel hours and materials
            ot_ids = [o.id for o in all_ots]
            personnel = OTPersonnel.query.filter(OTPersonnel.work_order_id.in_(ot_ids)).all() if ot_ids else []
            from models import OTMaterial, WarehouseItem as WI
            materials = OTMaterial.query.filter(OTMaterial.work_order_id.in_(ot_ids)).all() if ot_ids else []

            # Build cost lookup per OT
            hh_by_ot = defaultdict(float)
            for p in personnel:
                hh_by_ot[p.work_order_id] += (p.hours_worked or p.hours_assigned or 0)

            mat_cost_by_ot = defaultdict(float)
            for m in materials:
                if m.item_type == 'warehouse' and m.item_id:
                    wi = WI.query.get(m.item_id)
                    if wi and wi.unit_cost:
                        mat_cost_by_ot[m.work_order_id] += (m.quantity or 0) * wi.unit_cost

            HH_COST = float(request.args.get('hh_cost', 15))  # $/hour default

            # Calculate per month
            trend_data = []
            for bucket in month_buckets:
                ots_in_month = []
                for o in all_ots:
                    d = _parse_date_flexible(o.real_end_date or o.real_start_date or o.scheduled_date)
                    if d and bucket['start'] <= d < bucket['end']:
                        ots_in_month.append(o)

                n_corr = sum(1 for o in ots_in_month if 'correct' in (o.maintenance_type or '').lower())
                n_prev = sum(1 for o in ots_in_month if 'correct' not in (o.maintenance_type or '').lower())
                total_repair = sum(_safe_duration_hours(o.real_duration) or 0 for o in ots_in_month)
                total_down = sum(getattr(o, 'downtime_hours', 0) or 0 for o in ots_in_month
                                 if getattr(o, 'caused_downtime', False))

                cal_hours = (bucket['end'] - bucket['start']).days * 24
                t_up = max(cal_hours - total_down, 0)
                mtbf = round(t_up / n_corr, 1) if n_corr > 0 else None
                mttr = round(total_repair / n_corr, 1) if n_corr > 0 else None
                avail = round((t_up / cal_hours) * 100, 1) if cal_hours > 0 else 100

                # Costs
                total_hh = sum(hh_by_ot.get(o.id, 0) for o in ots_in_month)
                total_mat = sum(mat_cost_by_ot.get(o.id, 0) for o in ots_in_month)
                cost_hh = round(total_hh * HH_COST, 2)
                cost_mat = round(total_mat, 2)

                trend_data.append({
                    'month': bucket['label'],
                    'ots': len(ots_in_month),
                    'correctivo': n_corr,
                    'preventivo': n_prev,
                    'mtbf': mtbf,
                    'mttr': mttr,
                    'availability': avail,
                    'downtime_h': round(total_down, 1),
                    'hh_total': round(total_hh, 1),
                    'cost_hh': cost_hh,
                    'cost_materials': cost_mat,
                    'cost_total': round(cost_hh + cost_mat, 2),
                })

            # OT cost summary (all time)
            cost_summary = []
            for o in all_ots:
                hh = hh_by_ot.get(o.id, 0)
                mc = mat_cost_by_ot.get(o.id, 0)
                if hh > 0 or mc > 0:
                    eq = Equipment.query.get(o.equipment_id) if o.equipment_id else None
                    cost_summary.append({
                        'code': o.code,
                        'equipment': f"{eq.tag or ''} {eq.name}".strip() if eq else '-',
                        'type': o.maintenance_type,
                        'hh': round(hh, 1),
                        'cost_hh': round(hh * HH_COST, 2),
                        'cost_materials': round(mc, 2),
                        'cost_total': round(hh * HH_COST + mc, 2),
                    })
            cost_summary.sort(key=lambda x: x['cost_total'], reverse=True)

            return jsonify({
                'trends': trend_data,
                'costs': cost_summary[:50],
                'hh_rate': HH_COST,
            })
        except Exception as e:
            logger.exception("Dashboard trends error")
            return jsonify({"error": str(e)}), 500

    # ── Maintenance Calendar ───────────────────────────────────────────────

    @app.route('/api/maintenance-calendar', methods=['GET'])
    def maintenance_calendar():
        """Return all due dates for lub/insp/mon points as calendar events."""
        try:
            events = []

            if LubricationPoint:
                for p in LubricationPoint.query.filter_by(is_active=True).all():
                    if _calculate_lubrication_schedule:
                        nd, sem = _calculate_lubrication_schedule(
                            p.last_service_date, p.frequency_days, p.warning_days)
                    else:
                        nd, sem = p.next_due_date, p.semaphore_status
                    eq = Equipment.query.get(p.equipment_id) if p.equipment_id else None
                    events.append({
                        'id': f'lub-{p.id}',
                        'title': f'LUB {p.code}: {p.name}',
                        'start': nd or '',
                        'category': 'lubricacion',
                        'semaphore': sem,
                        'equipment': eq.name if eq else None,
                        'frequency': p.frequency_days,
                        'last_date': p.last_service_date,
                    })

            if InspectionRoute:
                for r in InspectionRoute.query.filter_by(is_active=True).all():
                    if _calculate_lubrication_schedule:
                        nd, sem = _calculate_lubrication_schedule(
                            r.last_execution_date, r.frequency_days, r.warning_days)
                    else:
                        nd, sem = r.next_due_date, r.semaphore_status
                    eq = Equipment.query.get(r.equipment_id) if r.equipment_id else None
                    events.append({
                        'id': f'insp-{r.id}',
                        'title': f'INSP {r.code}: {r.name}',
                        'start': nd or '',
                        'category': 'inspeccion',
                        'semaphore': sem,
                        'equipment': eq.name if eq else None,
                        'frequency': r.frequency_days,
                        'last_date': r.last_execution_date,
                    })

            if MonitoringPoint:
                for p in MonitoringPoint.query.filter_by(is_active=True).all():
                    from utils.schedule_helpers import _calculate_monitoring_schedule
                    nd, sem = _calculate_monitoring_schedule(
                        p.last_measurement_date, p.frequency_days, p.warning_days)
                    eq = Equipment.query.get(p.equipment_id) if p.equipment_id else None
                    events.append({
                        'id': f'mon-{p.id}',
                        'title': f'MON {p.code}: {p.name}',
                        'start': nd or '',
                        'category': 'monitoreo',
                        'semaphore': sem,
                        'equipment': eq.name if eq else None,
                        'frequency': p.frequency_days,
                        'last_date': p.last_measurement_date,
                    })

            # Also add scheduled OTs
            scheduled_ots = WorkOrder.query.filter(
                WorkOrder.status.in_(['Programada', 'Abierta']),
                WorkOrder.scheduled_date.isnot(None),
            ).all()
            for ot in scheduled_ots:
                eq = Equipment.query.get(ot.equipment_id) if ot.equipment_id else None
                events.append({
                    'id': f'ot-{ot.id}',
                    'title': f'OT {ot.code}: {ot.description or ot.maintenance_type or ""}',
                    'start': ot.scheduled_date,
                    'category': 'ot',
                    'semaphore': 'AMARILLO' if ot.status == 'Abierta' else 'VERDE',
                    'equipment': eq.name if eq else None,
                    'frequency': None,
                    'last_date': None,
                })

            return jsonify(events)
        except Exception as e:
            logger.exception("Maintenance calendar error")
            return jsonify({"error": str(e)}), 500

    @app.route('/calendario')
    def calendar_page():
        return render_template('calendar.html')

    # ── Notifications ──────────────────────────────────────────────────────

    @app.route('/api/notifications', methods=['GET'])
    def get_notifications():
        if not Notification:
            return jsonify([])
        from flask_login import current_user
        unread_only = request.args.get('unread', 'false').lower() == 'true'
        query = Notification.query.filter(
            db.or_(Notification.user_id == None, Notification.user_id == current_user.id)
        ).order_by(Notification.id.desc())
        if unread_only:
            query = query.filter_by(is_read=False)
        items = query.limit(50).all()
        return jsonify([n.to_dict() for n in items])

    @app.route('/api/notifications/count', methods=['GET'])
    def notification_count():
        if not Notification:
            return jsonify({'count': 0})
        from flask_login import current_user
        count = Notification.query.filter(
            Notification.is_read == False,
            db.or_(Notification.user_id == None, Notification.user_id == current_user.id)
        ).count()
        return jsonify({'count': count})

    @app.route('/api/notifications/read', methods=['POST'])
    def mark_notifications_read():
        if not Notification:
            return jsonify({'ok': True})
        data = request.get_json() or {}
        ids = data.get('ids', [])
        if ids:
            Notification.query.filter(Notification.id.in_(ids)).update(
                {Notification.is_read: True}, synchronize_session=False)
        else:
            from flask_login import current_user
            Notification.query.filter(
                Notification.is_read == False,
                db.or_(Notification.user_id == None, Notification.user_id == current_user.id)
            ).update({Notification.is_read: True}, synchronize_session=False)
        db.session.commit()
        return jsonify({'ok': True})

    @app.route('/api/notifications/scan', methods=['POST'])
    def scan_notifications():
        """Generate notifications from overdue points and low stock."""
        if not Notification:
            return jsonify({'created': 0})
        try:
            created = 0
            today = dt.date.today()
            today_str = today.isoformat()

            # Don't duplicate: only create if no unread notification of same category+title exists
            def _exists(title):
                return Notification.query.filter_by(
                    title=title, is_read=False).first() is not None

            # 1. Overdue lubrication points
            if LubricationPoint and _calculate_lubrication_schedule:
                for p in LubricationPoint.query.filter_by(is_active=True).all():
                    _, sem = _calculate_lubrication_schedule(
                        p.last_service_date, p.frequency_days, p.warning_days)
                    if sem == 'ROJO':
                        title = f"Lubricacion vencida: {p.code}"
                        if not _exists(title):
                            db.session.add(Notification(
                                title=title,
                                message=f"{p.name} — vencido desde {p.next_due_date or '?'}",
                                category='VENCIDO',
                                link='/lubricacion',
                            ))
                            created += 1

            # 2. Overdue inspections
            if InspectionRoute and _calculate_lubrication_schedule:
                for r in InspectionRoute.query.filter_by(is_active=True).all():
                    _, sem = _calculate_lubrication_schedule(
                        r.last_execution_date, r.frequency_days, r.warning_days)
                    if sem == 'ROJO':
                        title = f"Inspeccion vencida: {r.code}"
                        if not _exists(title):
                            db.session.add(Notification(
                                title=title,
                                message=f"{r.name} — vencida desde {r.next_due_date or '?'}",
                                category='VENCIDO',
                                link='/inspecciones',
                            ))
                            created += 1

            # 3. Low stock items
            if WarehouseItem:
                low = WarehouseItem.query.filter(
                    WarehouseItem.is_active == True,
                    WarehouseItem.min_stock != None,
                    WarehouseItem.stock <= WarehouseItem.min_stock
                ).all()
                for item in low:
                    title = f"Stock bajo: {item.code}"
                    if not _exists(title):
                        db.session.add(Notification(
                            title=title,
                            message=f"{item.name} — Stock: {item.stock} {item.unit or ''} (min: {item.min_stock})",
                            category='STOCK_BAJO',
                            link='/almacen',
                        ))
                        created += 1

            # 4. OTs open > 7 days without progress
            old_ots = WorkOrder.query.filter(
                WorkOrder.status.in_(['Abierta', 'Pendiente']),
            ).all()
            for ot in old_ots:
                d = _parse_date_flexible(ot.scheduled_date)
                if d and (today - d).days > 7:
                    title = f"OT sin progreso: {ot.code}"
                    if not _exists(title):
                        db.session.add(Notification(
                            title=title,
                            message=f"{ot.description or '-'} — {(today - d).days} dias sin avance",
                            category='OT',
                            link='/ordenes',
                        ))
                        created += 1

            db.session.commit()
            return jsonify({'created': created})
        except Exception as e:
            db.session.rollback()
            logger.exception("Notification scan error")
            return jsonify({"error": str(e)}), 500
