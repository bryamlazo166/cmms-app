"""Modulo Pendientes.

Lo que hay que hacer y todavia no es una orden de trabajo: se anota al vuelo
desde Telegram (`/p ...`) o desde esta pantalla, queda anclado al arbol de
equipos cuando el texto lo permite, y al terminarlo pasa a HECHO — no se
borra: sale de la lista activa y queda como bitacora con quien lo cerro,
cuando y con que comentario.

Un pendiente puede colgar de una OT o de un aviso, o no colgar de nada; y
puede convertirse en aviso cuando amerita entrar al flujo formal.
"""
import datetime as dt

from flask import jsonify, request, render_template
from flask_login import current_user

from utils.pending_helpers import (
    PENDING_OPEN, PENDING_DONE, PENDING_CANCELLED, PENDING_STATUSES, PRIORITIES,
    parse_due_phrase, infer_priority,
    close_payload, reopen_payload, overdue_days,
)


def register_pending_routes(app, db, logger, PendingTask, MaintenanceNotice,
                            WorkOrder):

    def _actor():
        """Nombre para la bitacora: el usuario logueado o el que venga en el body."""
        try:
            if current_user.is_authenticated:
                return current_user.username
        except Exception:
            pass
        return (request.get_json(silent=True) or {}).get('actor') or 'CMMS'

    def _resolve_tree(data):
        """Resuelve equipo/componente desde tags o texto libre.

        Reutiliza el resolvedor del bot para que la web y Telegram anclen igual
        (incluidas las reglas de taxonomia de los TH).
        """
        payload = {k: data.get(k) for k in
                   ('equipment_id', 'component_id', 'system_id', 'line_id', 'area_id',
                    'equipment_tag', 'equipment_name', 'component_name', 'system_name',
                    'rotative_asset_id')
                   if data.get(k) not in (None, '')}
        if data.get('_user_text'):
            payload['_user_text'] = data['_user_text']
        if not payload:
            return (None,) * 6
        try:
            from sqlalchemy import text as _t
            from bot.resolvers import resolve_equipment
            return resolve_equipment(db, _t, payload)
        except Exception as e:
            logger.warning(f"pendientes: no se pudo resolver la taxonomia: {e}")
            return (None,) * 6

    def _row(task):
        d = task.to_dict()
        od = overdue_days(task.due_date)
        d['overdue_days'] = od
        d['due_status'] = (None if od is None else
                           'VENCIDO' if od > 0 else 'HOY' if od == 0 else 'PROXIMO')
        return d

    # ── Pagina ───────────────────────────────────────────────────────────
    @app.route('/pendientes', methods=['GET'])
    def pendientes_page():
        return render_template('pendientes.html')

    # ── Listado ──────────────────────────────────────────────────────────
    @app.route('/api/pending-tasks', methods=['GET', 'POST'])
    def pending_tasks():
        if request.method == 'GET':
            try:
                q = PendingTask.query
                status = (request.args.get('status') or '').strip()
                if status and status.lower() != 'todos':
                    q = q.filter(PendingTask.status == status)
                for arg, col in (('equipment_id', PendingTask.equipment_id),
                                 ('area_id', PendingTask.area_id),
                                 ('line_id', PendingTask.line_id),
                                 ('component_id', PendingTask.component_id),
                                 ('work_order_id', PendingTask.work_order_id)):
                    val = request.args.get(arg)
                    if val:
                        q = q.filter(col == int(val))
                tasks = q.order_by(PendingTask.id.desc()).all()

                search = (request.args.get('q') or '').strip().lower()
                rows = [_row(t) for t in tasks]
                if search:
                    rows = [r for r in rows if search in ' '.join(
                        str(r.get(k) or '') for k in
                        ('code', 'description', 'equipment_tag', 'equipment_name',
                         'component_name', 'area_name', 'created_by')).lower()]

                summary = {
                    'abiertos': sum(1 for r in rows if r['status'] == PENDING_OPEN),
                    'vencidos': sum(1 for r in rows if r['status'] == PENDING_OPEN and r['due_status'] == 'VENCIDO'),
                    'hoy': sum(1 for r in rows if r['status'] == PENDING_OPEN and r['due_status'] == 'HOY'),
                    'sin_fecha': sum(1 for r in rows if r['status'] == PENDING_OPEN and not r['due_date']),
                    'hechos': sum(1 for r in rows if r['status'] == PENDING_DONE),
                    'anulados': sum(1 for r in rows if r['status'] == PENDING_CANCELLED),
                }
                return jsonify({'rows': rows, 'summary': summary, 'total': len(rows)})
            except Exception as e:
                logger.exception(f"pending_tasks GET error: {e}")
                return jsonify({"error": str(e)}), 500

        # POST — crear
        try:
            data = request.get_json(silent=True) or {}
            raw = (data.get('description') or '').strip()
            if not raw:
                return jsonify({"error": "La descripcion es obligatoria"}), 400

            due = (data.get('due_date') or '').strip() or None
            desc = raw
            if not due:
                # El plazo puede venir dentro del texto ("... en 2 semanas")
                due, desc = parse_due_phrase(raw)

            priority = (data.get('priority') or '').strip() or infer_priority(raw)
            if priority not in PRIORITIES:
                priority = 'Normal'

            data.setdefault('_user_text', raw)
            eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = _resolve_tree(data)

            wo_id = data.get('work_order_id')
            wo_code = (data.get('work_order_code') or '').strip().upper()
            if not wo_id and wo_code:
                wo = WorkOrder.query.filter_by(code=wo_code).first()
                if not wo:
                    return jsonify({"error": f"{wo_code} no encontrada"}), 404
                wo_id = wo.id

            task = PendingTask(
                description=desc or raw,
                due_date=due,
                priority=priority,
                status=PENDING_OPEN,
                area_id=ar_id, line_id=ln_id, equipment_id=eq_id,
                system_id=sys_id, component_id=comp_id, rotative_asset_id=ra_id,
                work_order_id=wo_id,
                notice_id=data.get('notice_id'),
                created_by=(data.get('created_by') or _actor()),
                source=(data.get('source') or 'web'),
            )
            db.session.add(task)
            db.session.flush()
            task.code = f"PEND-{str(task.id).zfill(4)}"
            db.session.commit()
            return jsonify(_row(task)), 201
        except Exception as e:
            db.session.rollback()
            logger.exception(f"pending_tasks POST error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Edicion ──────────────────────────────────────────────────────────
    @app.route('/api/pending-tasks/<int:task_id>', methods=['PUT', 'DELETE'])
    def pending_task_detail(task_id):
        task = PendingTask.query.get(task_id)
        if not task:
            return jsonify({"error": "Pendiente no encontrado"}), 404

        if request.method == 'DELETE':
            # No se borra: se anula, para que quede el rastro de lo que se pidio.
            try:
                for k, v in close_payload(PENDING_CANCELLED, _actor(),
                                          (request.args.get('reason') or 'Anulado')).items():
                    setattr(task, k, v)
                db.session.commit()
                return jsonify(_row(task))
            except Exception as e:
                db.session.rollback()
                logger.exception(f"pending_task DELETE error: {e}")
                return jsonify({"error": str(e)}), 500

        try:
            data = request.get_json(silent=True) or {}
            if 'description' in data and (data['description'] or '').strip():
                task.description = data['description'].strip()
            if 'due_date' in data:
                task.due_date = (data['due_date'] or '').strip() or None
            if data.get('priority') in PRIORITIES:
                task.priority = data['priority']
            if data.get('status') in PENDING_STATUSES:
                task.status = data['status']
            if 'work_order_code' in data:
                code = (data['work_order_code'] or '').strip().upper()
                if not code:
                    task.work_order_id = None
                else:
                    wo = WorkOrder.query.filter_by(code=code).first()
                    if not wo:
                        return jsonify({"error": f"{code} no encontrada"}), 404
                    task.work_order_id = wo.id
            if any(k in data for k in ('equipment_tag', 'equipment_id', 'component_name',
                                       'component_id', 'system_name')):
                eq_id, ln_id, ar_id, sys_id, comp_id, ra_id = _resolve_tree(data)
                if eq_id:
                    task.equipment_id, task.line_id, task.area_id = eq_id, ln_id, ar_id
                    task.system_id, task.component_id = sys_id, comp_id
                    task.rotative_asset_id = ra_id
            db.session.commit()
            return jsonify(_row(task))
        except Exception as e:
            db.session.rollback()
            logger.exception(f"pending_task PUT error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Cierre / reapertura ──────────────────────────────────────────────
    @app.route('/api/pending-tasks/<int:task_id>/<any(done,cancel,reopen):op>', methods=['POST'])
    def pending_task_close(task_id, op):
        task = PendingTask.query.get(task_id)
        if not task:
            return jsonify({"error": "Pendiente no encontrado"}), 404
        try:
            data = request.get_json(silent=True) or {}
            if op == 'reopen':
                for k, v in reopen_payload().items():
                    setattr(task, k, v)
            else:
                status = PENDING_DONE if op == 'done' else PENDING_CANCELLED
                payload = close_payload(
                    status,
                    (data.get('done_by') or _actor()),
                    data.get('comment') or data.get('done_comment'),
                    when=(data.get('done_date') or None),
                )
                for k, v in payload.items():
                    setattr(task, k, v)
            db.session.commit()
            return jsonify(_row(task))
        except Exception as e:
            db.session.rollback()
            logger.exception(f"pending_task {op} error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Convertir en aviso ───────────────────────────────────────────────
    @app.route('/api/pending-tasks/<int:task_id>/to-notice', methods=['POST'])
    def pending_task_to_notice(task_id):
        """Promueve el pendiente al flujo formal creando un aviso.

        El pendiente no se cierra solo: queda vinculado al aviso y se cierra
        cuando el trabajo se hace, para no perder el rastro de quien lo pidio.
        """
        task = PendingTask.query.get(task_id)
        if not task:
            return jsonify({"error": "Pendiente no encontrado"}), 404
        if task.notice_id:
            return jsonify({"error": f"Ya tiene el aviso vinculado (id {task.notice_id})"}), 400
        try:
            data = request.get_json(silent=True) or {}
            notice = MaintenanceNotice(
                reporter_name=(task.created_by or _actor()),
                reporter_type="PENDIENTE",
                area_id=task.area_id, line_id=task.line_id,
                equipment_id=task.equipment_id, system_id=task.system_id,
                component_id=task.component_id,
                rotative_asset_id=task.rotative_asset_id,
                description=f"[{task.code}] {task.description}",
                maintenance_type=(data.get('maintenance_type') or "Correctivo"),
                priority=('Alta' if task.priority == 'Alta' else 'Normal'),
                status="Pendiente",
                request_date=dt.date.today().isoformat(),
            )
            db.session.add(notice)
            db.session.flush()
            notice.code = f"AV-{notice.id:04d}"
            task.notice_id = notice.id
            db.session.commit()
            return jsonify({'notice_code': notice.code, 'notice_id': notice.id,
                            'task': _row(task)}), 201
        except Exception as e:
            db.session.rollback()
            logger.exception(f"pending_task_to_notice error: {e}")
            return jsonify({"error": str(e)}), 500
