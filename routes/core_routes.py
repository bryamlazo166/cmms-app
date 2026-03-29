from flask import jsonify, redirect, render_template, url_for


def register_core_routes(app, db, logger, app_build_tag, WorkOrder, MaintenanceNotice, Technician):
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
            recent_data = [
                {
                    'code': ot.code,
                    'desc': ot.description,
                    'status': ot.status,
                    'date': ot.scheduled_date,
                }
                for ot in recent_ots
            ]

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

    @app.route('/activos-rotativos')
    def rotative_assets_page():
        return render_template('rotative_assets.html')

    @app.route('/herramientas')
    def tools_page():
        return render_template('tools.html')

    @app.route('/compras')
    def purchasing_page():
        return render_template('purchasing.html')
