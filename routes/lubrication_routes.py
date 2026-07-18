import datetime as dt
import re
from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file
from flask_login import login_required
from openpyxl.utils import get_column_letter
from sqlalchemy import inspect, text

from utils.audit import audit_log
from utils.rate_limit import limit_export


def register_lubrication_routes(
    app,
    db,
    logger,
    LubricationPoint,
    LubricationExecution,
    MaintenanceNotice,
    _calculate_lubrication_schedule,
):
    _schema_compat_checked = {"done": False}

    def _parse_date_flexible(raw):
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(str(raw), fmt).date()
            except Exception:
                pass
        return None

    def _friendly_error_message(exc, context):
        raw = str(exc or "")
        lower = raw.lower()
        if "undefinedcolumn" in lower or "does not exist" in lower:
            return f"Error de esquema de base de datos en {context}. Ejecuta la migracion de lubricacion."
        if "null value in column" in lower and "violates not-null constraint" in lower:
            m = re.search(r'column "([^"]+)"', raw, flags=re.IGNORECASE)
            col = m.group(1) if m else "campo requerido"
            return f"No se pudo guardar {context}: falta valor obligatorio en '{col}'."
        if "violates foreign key constraint" in lower:
            return f"No se pudo guardar {context}: el equipo/sistema/componente seleccionado no es valido."
        if "unique constraint" in lower or "duplicate key value" in lower:
            return f"No se pudo guardar {context}: ya existe un registro con ese codigo."
        return f"Error procesando {context}. Intenta nuevamente."

    # _generate_lubrication_code removed — code assigned after flush

    def _safe_int(raw):
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except Exception:
            return None

    def _safe_float(raw):
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except Exception:
            return None

    def _safe_date_iso(raw):
        d = _parse_date_flexible(raw)
        return d.isoformat() if d else None

    def _resolve_hierarchy_ids(area_id, line_id, equipment_id, system_id, component_id):
        area_id = _safe_int(area_id)
        line_id = _safe_int(line_id)
        equipment_id = _safe_int(equipment_id)
        system_id = _safe_int(system_id)
        component_id = _safe_int(component_id)

        if component_id and not system_id:
            system_id = db.session.execute(
                text("SELECT system_id FROM components WHERE id = :id"),
                {"id": component_id},
            ).scalar()
            system_id = _safe_int(system_id)

        if system_id and not equipment_id:
            equipment_id = db.session.execute(
                text("SELECT equipment_id FROM systems WHERE id = :id"),
                {"id": system_id},
            ).scalar()
            equipment_id = _safe_int(equipment_id)

        if equipment_id and not line_id:
            line_id = db.session.execute(
                text("SELECT line_id FROM equipments WHERE id = :id"),
                {"id": equipment_id},
            ).scalar()
            line_id = _safe_int(line_id)

        if line_id and not area_id:
            area_id = db.session.execute(
                text("SELECT area_id FROM lines WHERE id = :id"),
                {"id": line_id},
            ).scalar()
            area_id = _safe_int(area_id)

        return area_id, line_id, equipment_id, system_id, component_id

    _ACTION_LABELS = {
        'CAMBIO_TOTAL': 'Cambio total',
        'SERVICIO': 'Cambio total',
        'RELLENO': 'Relleno',
    }

    _POINT_FILTER_KEYS = ('area', 'line', 'equipment', 'system', 'component',
                          'lubricant', 'freq', 'responsible', 'search')

    def _has_point_filters(args):
        return any((args.get(k) or '').strip() for k in _POINT_FILTER_KEYS)

    def _point_matches_filters(p, args):
        """True si el punto pasa los filtros de taxonomia que llegan como query
        params. Se filtra por NOMBRE (los mismos valores que muestran los
        selects de la UI), no por id, para que la URL de exportacion sea la
        misma que ve el usuario en pantalla."""
        def norm(s):
            return (s or '').strip().lower()

        pairs = (
            ('area', p.area.name if p.area else None),
            ('line', p.line.name if p.line else None),
            ('equipment', p.equipment.name if p.equipment else None),
            ('system', p.system.name if p.system else None),
            ('component', p.component.name if p.component else None),
            ('lubricant', p.lubricant_name),
            ('freq', str(p.frequency_days or '')),
        )
        for key, value in pairs:
            wanted = norm(args.get(key))
            if wanted and norm(value) != wanted:
                return False

        wanted_resp = norm(args.get('responsible'))
        if wanted_resp:
            effective = (
                p.responsible_party_override
                or (p.equipment.default_responsible_party if p.equipment else None)
                or 'INTERNO'
            )
            if norm(effective) != wanted_resp:
                return False

        search = norm(args.get('search'))
        if search:
            blob = ' '.join(filter(None, [
                p.code, p.name, p.lubricant_name,
                p.area.name if p.area else None,
                p.line.name if p.line else None,
                p.equipment.name if p.equipment else None,
                p.equipment.tag if p.equipment else None,
                p.system.name if p.system else None,
                p.component.name if p.component else None,
            ])).lower()
            tokens = [t for t in re.split(r'[\s,;/#-]+', search) if t]
            if not all(t in blob for t in tokens):
                return False
        return True

    def _interval_map_for_points(point_ids):
        """{execution_id: dias transcurridos desde la ejecucion anterior del
        mismo punto}. Se calcula sobre TODO el historial de esos puntos, no
        solo la ventana filtrada, para que el primer registro de un rango de
        fechas conserve su intervalo real."""
        if not point_ids:
            return {}
        rows = (
            db.session.query(
                LubricationExecution.id,
                LubricationExecution.point_id,
                LubricationExecution.execution_date,
            )
            .filter(LubricationExecution.point_id.in_(point_ids))
            .all()
        )
        by_point = {}
        for exec_id, pid, date_raw in rows:
            d = _parse_date_flexible(date_raw)
            if d:
                by_point.setdefault(pid, []).append((d, exec_id))
        intervals = {}
        for parsed in by_point.values():
            parsed.sort()
            prev = None
            for d, exec_id in parsed:
                if prev is not None:
                    intervals[exec_id] = (d - prev).days
                prev = d
        return intervals

    def _ensure_lubrication_schema_compat():
        if _schema_compat_checked["done"]:
            return

        try:
            with db.engine.begin() as conn:
                inspector = inspect(conn)
                if not inspector.has_table("lubrication_points"):
                    _schema_compat_checked["done"] = True
                    return

                cols_lp = {c["name"]: c for c in inspector.get_columns("lubrication_points")}

                if "name" not in cols_lp:
                    conn.execute(text("ALTER TABLE lubrication_points ADD COLUMN name VARCHAR(120)"))
                    cols_lp["name"] = {"name": "name", "nullable": True}

                if "description" not in cols_lp:
                    conn.execute(text("ALTER TABLE lubrication_points ADD COLUMN description TEXT"))
                    cols_lp["description"] = {"name": "description", "nullable": True}

                if "task_name" in cols_lp and "name" in cols_lp:
                    conn.execute(text("""
                        UPDATE lubrication_points
                        SET name = task_name
                        WHERE (name IS NULL OR btrim(name) = '')
                          AND task_name IS NOT NULL
                    """))

                if "notes" in cols_lp and "description" in cols_lp:
                    conn.execute(text("""
                        UPDATE lubrication_points
                        SET description = notes
                        WHERE description IS NULL
                          AND notes IS NOT NULL
                    """))

                cols_le = {}
                if inspector.has_table("lubrication_executions"):
                    cols_le = {c["name"]: c for c in inspector.get_columns("lubrication_executions")}
                    if "execution_date" not in cols_le:
                        conn.execute(text("ALTER TABLE lubrication_executions ADD COLUMN execution_date VARCHAR(20)"))
                        cols_le["execution_date"] = {"name": "execution_date", "nullable": True}
                    if "executed_date" in cols_le and "execution_date" in cols_le:
                        conn.execute(text("""
                            UPDATE lubrication_executions
                            SET execution_date = executed_date
                            WHERE execution_date IS NULL
                              AND executed_date IS NOT NULL
                        """))

                backend = (conn.engine.url.get_backend_name() or "").lower()
                if "postgres" in backend:
                    if "task_name" in cols_lp and cols_lp["task_name"].get("nullable") is False:
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN task_name DROP NOT NULL"))
                    if "notes" in cols_lp and cols_lp["notes"].get("nullable") is False:
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN notes DROP NOT NULL"))
                    if "task_group" in cols_lp:
                        conn.execute(text("UPDATE lubrication_points SET task_group = COALESCE(task_group, 'GENERAL')"))
                        if cols_lp["task_group"].get("nullable") is False:
                            conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN task_group DROP NOT NULL"))
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN task_group SET DEFAULT 'GENERAL'"))
                    # task_type: legacy NOT NULL column no longer used by current model
                    if "task_type" in cols_lp and cols_lp["task_type"].get("nullable") is False:
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN task_type DROP NOT NULL"))
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN task_type SET DEFAULT 'Lubricacion'"))
                        conn.execute(text("UPDATE lubrication_points SET task_type = 'Lubricacion' WHERE task_type IS NULL"))
                    # code: allow null so auto-generation works
                    if "code" in cols_lp and cols_lp["code"].get("nullable") is False:
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN code DROP NOT NULL"))
                    # reset_cycle_on_topup: legacy boolean NOT NULL with no default
                    if "reset_cycle_on_topup" in cols_lp and cols_lp["reset_cycle_on_topup"].get("nullable") is False:
                        conn.execute(text("ALTER TABLE lubrication_points ALTER COLUMN reset_cycle_on_topup SET DEFAULT false"))
                        conn.execute(text("UPDATE lubrication_points SET reset_cycle_on_topup = false WHERE reset_cycle_on_topup IS NULL"))
                    # timestamps
                    for ts_col in ("created_at", "updated_at"):
                        if ts_col in cols_lp and cols_lp[ts_col].get("nullable") is False:
                            conn.execute(text(f"ALTER TABLE lubrication_points ALTER COLUMN {ts_col} SET DEFAULT NOW()"))
                            conn.execute(text(f"UPDATE lubrication_points SET {ts_col} = NOW() WHERE {ts_col} IS NULL"))
                    if "executed_date" in cols_le and cols_le["executed_date"].get("nullable") is False:
                        conn.execute(text("ALTER TABLE lubrication_executions ALTER COLUMN executed_date DROP NOT NULL"))

            _schema_compat_checked["done"] = True
        except Exception:
            logger.exception("Lubrication schema compat check warning")
            # No bloquea el flujo; se sigue con la operacion normal.

    @app.route('/api/lubrication/points', methods=['GET', 'POST'])
    def handle_lubrication_points():
        if request.method == 'POST':
            try:
                _ensure_lubrication_schema_compat()
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                last_service = _safe_date_iso(data.get('last_service_date'))
                frequency_days = int(data.get('frequency_days') or 30)
                warning_days = int(data.get('warning_days') or 3)
                next_due, semaphore = _calculate_lubrication_schedule(last_service, frequency_days, warning_days)

                area_id, line_id, equipment_id, system_id, component_id = _resolve_hierarchy_ids(
                    data.get('area_id'),
                    data.get('line_id'),
                    data.get('equipment_id'),
                    data.get('system_id'),
                    data.get('component_id'),
                )

                point = LubricationPoint(
                    code=data.get('code') or 'LUB-TEMP',
                    name=data.get('name').strip(),
                    description=data.get('description'),
                    area_id=area_id,
                    line_id=line_id,
                    equipment_id=equipment_id,
                    system_id=system_id,
                    component_id=component_id,
                    lubricant_name=data.get('lubricant_name'),
                    quantity_nominal=_safe_float(data.get('quantity_nominal')),
                    quantity_unit=data.get('quantity_unit') or 'L',
                    frequency_days=frequency_days,
                    warning_days=warning_days,
                    last_service_date=last_service,
                    next_due_date=next_due,
                    semaphore_status=semaphore,
                    is_active=bool(data.get('is_active', True))
                )
                db.session.add(point)
                db.session.flush()
                if point.code == 'LUB-TEMP':
                    point.code = f"LUB-{point.id:04d}"
                db.session.commit()
                return jsonify(point.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception('Lubrication points POST error')
                return jsonify({"error": _friendly_error_message(e, 'puntos de lubricacion')}), 500

        _ensure_lubrication_schema_compat()
        show_all = request.args.get('all', 'false').lower() == 'true'
        query = LubricationPoint.query
        if not show_all:
            query = query.filter_by(is_active=True)
        points = query.order_by(LubricationPoint.id.desc()).all()
        result = []
        for p in points:
            d = p.to_dict()
            next_due, semaphore = _calculate_lubrication_schedule(
                d.get('last_service_date'),
                d.get('frequency_days'),
                d.get('warning_days')
            )
            d['next_due_date'] = next_due
            d['semaphore_status'] = semaphore
            result.append(d)
        return jsonify(result)

    @app.route('/api/lubrication/points/<int:point_id>', methods=['PUT', 'DELETE'])
    def handle_lubrication_point_id(point_id):
        point = LubricationPoint.query.get_or_404(point_id)
        if request.method == 'DELETE':
            point.is_active = not point.is_active
            db.session.commit()
            state = "activado" if point.is_active else "desactivado"
            return jsonify({"message": f"Punto de lubricacion {state}", "is_active": point.is_active})

        try:
            _ensure_lubrication_schema_compat()
            data = request.json or {}
            for field in [
                'code', 'name', 'description', 'area_id', 'line_id', 'equipment_id',
                'system_id', 'component_id', 'lubricant_name', 'quantity_nominal',
                'quantity_unit', 'frequency_days', 'warning_days', 'last_service_date', 'is_active'
            ]:
                if field in data:
                    setattr(point, field, data[field])

            point.area_id, point.line_id, point.equipment_id, point.system_id, point.component_id = _resolve_hierarchy_ids(
                point.area_id,
                point.line_id,
                point.equipment_id,
                point.system_id,
                point.component_id,
            )
            point.quantity_nominal = _safe_float(point.quantity_nominal)
            point.last_service_date = _safe_date_iso(point.last_service_date)

            point.frequency_days = int(point.frequency_days or 30)
            point.warning_days = int(point.warning_days or 3)
            next_due, semaphore = _calculate_lubrication_schedule(
                point.last_service_date,
                point.frequency_days,
                point.warning_days
            )
            point.next_due_date = next_due
            point.semaphore_status = semaphore
            db.session.commit()
            return jsonify(point.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.exception('Lubrication point PUT error')
            return jsonify({"error": _friendly_error_message(e, 'actualizacion de punto')}), 500

    @app.route('/api/lubrication/executions', methods=['GET', 'POST'])
    def handle_lubrication_executions():
        if request.method == 'POST':
            try:
                _ensure_lubrication_schema_compat()
                data = request.json or {}
                point_id = data.get('point_id')
                if not point_id:
                    return jsonify({"error": "point_id es obligatorio"}), 400
                point = LubricationPoint.query.get(point_id)
                if not point:
                    return jsonify({"error": "Punto no encontrado"}), 404

                execution_date = _safe_date_iso(data.get('execution_date')) or dt.date.today().isoformat()
                # action_type:
                #   CAMBIO_TOTAL -> reinicia el cronograma (drain & fill)
                #   RELLENO      -> top-up, NO reinicia el cronograma
                #   SERVICIO     -> legado: tratado como CAMBIO_TOTAL
                action_type = (data.get('action_type') or 'CAMBIO_TOTAL').upper()
                execution = LubricationExecution(
                    point_id=point.id,
                    execution_date=execution_date,
                    action_type=action_type,
                    quantity_used=data.get('quantity_used'),
                    quantity_unit=data.get('quantity_unit') or point.quantity_unit or 'L',
                    executed_by=data.get('executed_by'),
                    leak_detected=bool(data.get('leak_detected', False)),
                    anomaly_detected=bool(data.get('anomaly_detected', False)),
                    comments=data.get('comments')
                )

                # Avanza el cronograma solo cuando:
                #  (a) la accion reinicia el ciclo (CAMBIO_TOTAL o SERVICIO legado), y
                #  (b) esta ejecucion es la mas reciente (no retroactiva).
                # RELLENO se guarda en el historial pero NO mueve last_service_date,
                # porque el aceite/grasa solo se completo a nivel — el cambio total
                # sigue pendiente en su fecha programada.
                resets_cycle = action_type in ('CAMBIO_TOTAL', 'SERVICIO')
                current_last = _parse_date_flexible(point.last_service_date)
                new_exec = _parse_date_flexible(execution_date)
                if resets_cycle and ((current_last is None) or (new_exec and new_exec >= current_last)):
                    point.last_service_date = execution_date
                    next_due, semaphore = _calculate_lubrication_schedule(
                        point.last_service_date,
                        point.frequency_days,
                        point.warning_days
                    )
                    point.next_due_date = next_due
                    point.semaphore_status = semaphore

                create_notice = bool(data.get('create_notice', True))
                # Triggers: fuga, anomalia, o solo observacion con texto.
                # Antes solo creaba aviso si leak/anomaly; ahora tambien crea
                # aviso OBSERVADO cuando el lubricador deja comentario aunque
                # no marque fuga/anomalia (para no perder el dato).
                has_comment = bool((execution.comments or '').strip())
                trigger_alta = execution.leak_detected or execution.anomaly_detected
                if create_notice and (trigger_alta or has_comment):
                    # Construir descripcion enriquecida
                    desc_parts = [f"[LUBRICACION] {point.name}"]
                    flags = []
                    if execution.leak_detected:
                        flags.append('FUGA')
                    if execution.anomaly_detected:
                        flags.append('ANOMALIA')
                    if not flags and has_comment:
                        flags.append('OBSERVADO')
                    desc_parts.append(f"Estado: {' + '.join(flags)}")
                    if execution.comments:
                        desc_parts.append(f"Comentario: {execution.comments}")
                    if execution.executed_by:
                        desc_parts.append(f"Reportado por: {execution.executed_by}")
                    notice = MaintenanceNotice(
                        reporter_name=execution.executed_by or 'Tecnico Lubricacion',
                        reporter_type='MANTENIMIENTO',
                        area_id=point.area_id,
                        line_id=point.line_id,
                        equipment_id=point.equipment_id,
                        system_id=point.system_id,
                        component_id=point.component_id,
                        description=' | '.join(desc_parts),
                        maintenance_type='Correctivo' if trigger_alta else 'Preventivo',
                        priority='Alta' if trigger_alta else 'Media',
                        status='Pendiente',
                        request_date=dt.date.today().isoformat()
                    )
                    db.session.add(notice)
                    db.session.flush()
                    notice.code = f"AV-{notice.id:04d}"
                    execution.created_notice_id = notice.id

                db.session.add(execution)
                db.session.commit()
                return jsonify(execution.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception('Lubrication execution POST error')
                return jsonify({"error": _friendly_error_message(e, 'registro de ejecucion')}), 500

        _ensure_lubrication_schema_compat()
        args = request.args
        point_id = args.get('point_id', type=int)
        date_from = _safe_date_iso(args.get('date_from'))
        date_to = _safe_date_iso(args.get('date_to'))
        has_filters = bool(point_id or date_from or date_to or _has_point_filters(args))

        query = LubricationExecution.query
        if point_id:
            query = query.filter_by(point_id=point_id)
        elif _has_point_filters(args):
            matching_ids = [p.id for p in LubricationPoint.query.all()
                            if _point_matches_filters(p, args)]
            if not matching_ids:
                return jsonify([])
            query = query.filter(LubricationExecution.point_id.in_(matching_ids))
        if date_from:
            query = query.filter(LubricationExecution.execution_date >= date_from)
        if date_to:
            query = query.filter(LubricationExecution.execution_date <= date_to)

        # Con filtros dejamos traer mas historia (analisis de un componente);
        # sin filtros mantenemos la vista liviana de los ultimos registros.
        limit = 1000 if has_filters else 300
        rows = (query.order_by(LubricationExecution.execution_date.desc(),
                               LubricationExecution.id.desc())
                .limit(limit).all())
        intervals = _interval_map_for_points({r.point_id for r in rows})
        result = []
        for r in rows:
            d = r.to_dict()
            d['interval_days'] = intervals.get(r.id)
            p = r.point
            d['point_code'] = p.code if p else None
            d['area_name'] = p.area.name if p and p.area else None
            d['line_name'] = p.line.name if p and p.line else None
            d['equipment_name'] = p.equipment.name if p and p.equipment else None
            d['equipment_tag'] = p.equipment.tag if p and p.equipment else None
            d['system_name'] = p.system.name if p and p.system else None
            d['component_name'] = p.component.name if p and p.component else None
            d['frequency_days'] = p.frequency_days if p else None
            result.append(d)
        return jsonify(result)

    @app.route('/api/lubrication/executions/<int:exec_id>', methods=['DELETE'])
    def delete_lubrication_execution(exec_id):
        """Elimina una ejecucion y recalcula el semaforo del punto en base a las
        ejecuciones restantes (igual que el handler del bot)."""
        try:
            _ensure_lubrication_schema_compat()
            ex = LubricationExecution.query.get(exec_id)
            if not ex:
                return jsonify({"error": f"Ejecucion {exec_id} no existe"}), 404
            point_id = ex.point_id
            db.session.delete(ex)
            db.session.flush()

            # Recalcular last/next/semaforo del punto desde la ejecucion mas
            # reciente que reinicia el ciclo (CAMBIO_TOTAL o SERVICIO legado).
            # Los RELLENOs no cuentan: el cronograma depende del ultimo cambio
            # total. Si no queda ninguna ejecucion que reinicie, dejar PENDIENTE.
            point = LubricationPoint.query.get(point_id)
            if point:
                latest = (LubricationExecution.query
                          .filter_by(point_id=point_id)
                          .filter(LubricationExecution.action_type.in_(
                              ('CAMBIO_TOTAL', 'SERVICIO')))
                          .order_by(LubricationExecution.execution_date.desc(),
                                    LubricationExecution.id.desc())
                          .first())
                if latest:
                    point.last_service_date = latest.execution_date
                    nd, sema = _calculate_lubrication_schedule(
                        latest.execution_date, point.frequency_days, point.warning_days)
                    point.next_due_date = nd
                    point.semaphore_status = sema
                else:
                    point.last_service_date = None
                    point.next_due_date = None
                    point.semaphore_status = 'PENDIENTE'
            db.session.commit()
            return jsonify({"ok": True, "deleted_id": exec_id})
        except Exception as e:
            db.session.rollback()
            logger.exception('Lubrication execution DELETE error')
            return jsonify({"error": _friendly_error_message(e, 'eliminacion de ejecucion')}), 500

    @app.route('/api/lubrication/export', methods=['GET'])
    @login_required
    @limit_export
    def export_lubrication_excel():
        """Exporta a Excel la lubricacion en dos modos:

        scope=pending (default): lista de lubricaciones pendientes (ROJO,
            AMARILLO y sin fecha) con taxonomia completa y columnas vacias
            para completar en campo (fecha ejecutada, cantidad, observaciones).
        scope=history: historial de ejecuciones con intervalo real entre
            lubricaciones + hoja de resumen por punto (intervalo promedio
            real vs frecuencia teorica).

        Ambos aceptan los mismos filtros por nombre que la UI (area, line,
        equipment, system, component, lubricant, freq, responsible, search)
        y el historial ademas date_from/date_to.
        """
        try:
            _ensure_lubrication_schema_compat()
            args = request.args
            scope = (args.get('scope') or 'pending').lower()
            today = dt.date.today()

            # Pendientes: solo puntos activos (salvo show_inactive=true).
            # Historial: SIEMPRE incluye inactivos — el historial de un punto
            # desactivado sigue siendo historia valida (igual que la tabla).
            show_inactive = args.get('show_inactive', 'false').lower() == 'true'
            points_query = LubricationPoint.query
            if scope != 'history' and not show_inactive:
                points_query = points_query.filter_by(is_active=True)
            points = [p for p in points_query.all() if _point_matches_filters(p, args)]

            def taxonomy_cols(p):
                return {
                    'Código': p.code,
                    'Área': p.area.name if p.area else '-',
                    'Línea': p.line.name if p.line else '-',
                    'Equipo': p.equipment.name if p.equipment else '-',
                    'TAG': p.equipment.tag if p.equipment else '-',
                    'Sistema': p.system.name if p.system else '-',
                    'Componente': p.component.name if p.component else '-',
                    'Punto de Lubricación': p.name,
                }

            sheets = []
            if scope == 'history':
                date_from = _safe_date_iso(args.get('date_from'))
                date_to = _safe_date_iso(args.get('date_to'))
                point_map = {p.id: p for p in points}
                execs = []
                if point_map:
                    q = LubricationExecution.query.filter(
                        LubricationExecution.point_id.in_(point_map.keys()))
                    if date_from:
                        q = q.filter(LubricationExecution.execution_date >= date_from)
                    if date_to:
                        q = q.filter(LubricationExecution.execution_date <= date_to)
                    execs = (q.order_by(LubricationExecution.execution_date.desc(),
                                        LubricationExecution.id.desc()).all())
                intervals = _interval_map_for_points({e.point_id for e in execs})

                hist_rows = []
                per_point = {}
                for e in execs:
                    p = point_map.get(e.point_id)
                    if not p:
                        continue
                    row = {'Fecha': e.execution_date}
                    row.update(taxonomy_cols(p))
                    row.update({
                        'Acción': _ACTION_LABELS.get(e.action_type, e.action_type),
                        'Cantidad': e.quantity_used,
                        'Unidad': e.quantity_unit,
                        'Ejecutado Por': e.executed_by,
                        'Intervalo (días)': intervals.get(e.id),
                        'Fuga': 'Sí' if e.leak_detected else 'No',
                        'Anomalía': 'Sí' if e.anomaly_detected else 'No',
                        'Aviso': e.created_notice.code if e.created_notice else '',
                        'Comentarios': e.comments or '',
                    })
                    hist_rows.append(row)
                    per_point.setdefault(e.point_id, []).append(e)

                summary_rows = []
                for pid, plist in per_point.items():
                    p = point_map[pid]
                    ivals = [intervals[e.id] for e in plist if intervals.get(e.id) is not None]
                    dates = sorted(d for d in (e.execution_date for e in plist) if d)
                    total_changes = sum(1 for e in plist
                                        if e.action_type in ('CAMBIO_TOTAL', 'SERVICIO'))
                    avg = round(sum(ivals) / len(ivals), 1) if ivals else None
                    row = taxonomy_cols(p)
                    row.update({
                        'Lubricante': p.lubricant_name,
                        'N° Lubricaciones': len(plist),
                        'N° Cambios Totales': total_changes,
                        'N° Rellenos': len(plist) - total_changes,
                        'Primera Fecha': dates[0] if dates else None,
                        'Última Fecha': dates[-1] if dates else None,
                        'Intervalo Real Prom. (días)': avg,
                        'Intervalo Mín (días)': min(ivals) if ivals else None,
                        'Intervalo Máx (días)': max(ivals) if ivals else None,
                        'Frecuencia Teórica (días)': p.frequency_days,
                        'Desviación (días)': (round(avg - p.frequency_days, 1)
                                              if (avg is not None and p.frequency_days) else None),
                    })
                    summary_rows.append(row)
                summary_rows.sort(key=lambda r: (str(r['Área']), str(r['Equipo']),
                                                 str(r['Componente']),
                                                 str(r['Punto de Lubricación'])))

                sheets.append(('Historial', pd.DataFrame(hist_rows)))
                sheets.append(('Resumen por Punto', pd.DataFrame(summary_rows)))
                filename = f"Lubricacion_Historial_{today.isoformat()}.xlsx"
                audit_detail = f"scope=history rows={len(hist_rows)}"
            else:
                sema_filter = (args.get('sema') or '').strip().upper()
                due_filter = (args.get('due') or '').strip().lower()
                due_days_cap = None
                if due_filter and due_filter != 'vencido':
                    try:
                        due_days_cap = int(due_filter)
                    except ValueError:
                        due_filter = ''

                pend_rows = []
                for p in points:
                    next_due, semaphore = _calculate_lubrication_schedule(
                        p.last_service_date, p.frequency_days, p.warning_days)
                    # Sin filtro de semaforo se exporta lo pendiente (todo lo
                    # que no esta VERDE); con filtro se respeta lo que el
                    # usuario tiene seleccionado en pantalla.
                    if sema_filter:
                        if semaphore != sema_filter:
                            continue
                    elif semaphore == 'VERDE':
                        continue
                    due = _parse_date_flexible(next_due)
                    if due_filter:
                        if not due:
                            continue
                        days_until = (due - today).days
                        if due_filter == 'vencido':
                            if days_until >= 0:
                                continue
                        elif due_days_cap is not None and days_until > due_days_cap:
                            continue
                    days_overdue = max(0, (today - due).days) if due else None
                    effective_resp = (
                        p.responsible_party_override
                        or (p.equipment.default_responsible_party if p.equipment else None)
                        or 'INTERNO'
                    )
                    row = taxonomy_cols(p)
                    row.update({
                        'Lubricante': p.lubricant_name,
                        'Cant. Nominal': p.quantity_nominal,
                        'Unidad': p.quantity_unit,
                        'Frecuencia (días)': p.frequency_days,
                        'Último Servicio': p.last_service_date,
                        'Próximo Vencimiento': next_due,
                        'Días de Atraso': days_overdue,
                        'Semáforo': semaphore,
                        'Responsable': effective_resp,
                        'Ejecutado (fecha)': '',
                        'Cantidad Usada': '',
                        'Observaciones': '',
                    })
                    pend_rows.append(row)

                sema_order = {'ROJO': 0, 'AMARILLO': 1, 'PENDIENTE': 2, 'VERDE': 3}
                pend_rows.sort(key=lambda r: (
                    sema_order.get(r['Semáforo'], 9),
                    r['Próximo Vencimiento'] or '9999-12-31',
                    str(r['Área']), str(r['Equipo'])))

                summary_rows = []
                by_area = {}
                for r in pend_rows:
                    counts = by_area.setdefault(r['Área'], {'ROJO': 0, 'AMARILLO': 0,
                                                            'PENDIENTE': 0, 'VERDE': 0})
                    counts[r['Semáforo']] = counts.get(r['Semáforo'], 0) + 1
                for area_name in sorted(by_area, key=str):
                    c = by_area[area_name]
                    summary_rows.append({
                        'Área': area_name,
                        'Rojo (vencidas)': c.get('ROJO', 0),
                        'Amarillo (por vencer)': c.get('AMARILLO', 0),
                        'Sin fecha (pendiente)': c.get('PENDIENTE', 0),
                        'Total': sum(c.values()),
                    })
                if summary_rows:
                    summary_rows.append({
                        'Área': 'TOTAL',
                        'Rojo (vencidas)': sum(r['Rojo (vencidas)'] for r in summary_rows),
                        'Amarillo (por vencer)': sum(r['Amarillo (por vencer)'] for r in summary_rows),
                        'Sin fecha (pendiente)': sum(r['Sin fecha (pendiente)'] for r in summary_rows),
                        'Total': sum(r['Total'] for r in summary_rows),
                    })

                sheets.append(('Pendientes', pd.DataFrame(pend_rows)))
                sheets.append(('Resumen', pd.DataFrame(summary_rows)))
                filename = f"Lubricacion_Pendientes_{today.isoformat()}.xlsx"
                audit_detail = f"scope=pending rows={len(pend_rows)}"

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                for sheet_name, df in sheets:
                    if df.empty:
                        df = pd.DataFrame({'Info': ['Sin registros para los filtros aplicados']})
                    df.to_excel(writer, index=False, sheet_name=sheet_name)
                    ws = writer.sheets[sheet_name]
                    for idx, col in enumerate(df.columns, start=1):
                        try:
                            max_len = max([len(str(col))] +
                                          [len(str(v)) for v in df[col].head(200).fillna('')])
                        except Exception:
                            max_len = len(str(col))
                        ws.column_dimensions[get_column_letter(idx)].width = min(45, max(10, max_len + 2))
            output.seek(0)

            audit_log('EXPORT_MASS', module='lubricacion', detail=audit_detail)
            return send_file(
                output,
                download_name=filename,
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            db.session.rollback()
            logger.exception('Lubrication export error')
            return jsonify({"error": _friendly_error_message(e, 'exportacion de lubricacion')}), 500

    @app.route('/api/lubrication/dashboard', methods=['GET'])
    def get_lubrication_dashboard():
        try:
            _ensure_lubrication_schema_compat()
            show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
            if show_inactive:
                points = LubricationPoint.query.all()
            else:
                points = LubricationPoint.query.filter_by(is_active=True).all()
            kpi = {
                'total': len(points),
                'green': 0,
                'yellow': 0,
                'red': 0,
                'pending': 0,
                'due_now': 0,
                'compliance_percent': 100.0
            }
            today = dt.date.today()
            active_count = 0
            items = []
            for p in points:
                next_due, semaphore = _calculate_lubrication_schedule(
                    p.last_service_date,
                    p.frequency_days,
                    p.warning_days
                )
                due_date = _parse_date_flexible(next_due)

                # KPIs only count active points
                if p.is_active:
                    active_count += 1
                    if semaphore == 'VERDE':
                        kpi['green'] += 1
                    elif semaphore == 'AMARILLO':
                        kpi['yellow'] += 1
                    elif semaphore == 'ROJO':
                        kpi['red'] += 1
                    else:
                        kpi['pending'] += 1

                    if due_date and due_date <= today:
                        kpi['due_now'] += 1

                items.append({
                    'id': p.id,
                    'code': p.code,
                    'name': p.name,
                    'is_active': p.is_active,
                    'equipment_id': p.equipment_id,
                    'equipment_name': p.equipment.name if p.equipment else None,
                    'equipment_tag': p.equipment.tag if p.equipment else None,
                    'system_name': p.system.name if p.system else None,
                    'component_name': p.component.name if p.component else None,
                    'line_name': p.line.name if p.line else None,
                    'area_name': p.area.name if p.area else None,
                    'lubricant_name': p.lubricant_name,
                    'last_service_date': p.last_service_date,
                    'next_due_date': next_due,
                    'semaphore_status': semaphore,
                    'frequency_days': p.frequency_days,
                    'warning_days': p.warning_days,
                    'system_id': p.system_id,
                    'component_id': p.component_id,
                })

            kpi['total'] = active_count
            if kpi['total'] > 0:
                kpi['compliance_percent'] = round(((kpi['total'] - kpi['red']) / kpi['total']) * 100, 1)
            items.sort(key=lambda r: (r.get('next_due_date') or '9999-12-31'))
            return jsonify({'kpi': kpi, 'items': items[:200]})
        except Exception as e:
            logger.exception('Lubrication dashboard error')
            return jsonify({"error": _friendly_error_message(e, 'dashboard de lubricacion')}), 500
