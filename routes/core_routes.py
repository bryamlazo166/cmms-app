import datetime as dt
from collections import defaultdict

from flask import jsonify, redirect, render_template, request, url_for


def register_core_routes(app, db, logger, app_build_tag,
                         WorkOrder, MaintenanceNotice, Technician,
                         Area, Line, Equipment, OTPersonnel,
                         _parse_date_flexible, _safe_duration_hours):
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

    @app.route('/activos-rotativos')
    def rotative_assets_page():
        return render_template('rotative_assets.html')

    @app.route('/herramientas')
    def tools_page():
        return render_template('tools.html')

    @app.route('/compras')
    def purchasing_page():
        return render_template('purchasing.html')

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
