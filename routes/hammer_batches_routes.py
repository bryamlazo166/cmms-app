"""Rutas API para gestion de lotes de martillos (FAPMETAL).

Modelo de negocio:
  - 3 lotes fisicos rotan entre Molino #1, Molino #2 y FAPMETAL (proveedor).
  - En cualquier momento: 2 lotes instalados + 1 en transito.
  - Cuando se hace un cambio: el lote del molino sale a FAPMETAL para rellenar
    y entra el que estaba en stock rellenado.
  - El sistema infiere automaticamente los lotes involucrados.

Endpoints principales:
  POST /api/hammer-batches/change          Cambio de lote en molino (la accion clave)
  POST /api/hammer-batches/<id>/receive    Recibir lote rellenado de FAPMETAL
  GET  /api/hammer-batches/conciliation    Reporte de conciliacion (90d default)
"""
import datetime as dt
from flask import jsonify, request
from sqlalchemy import text, func


STATES_INSTALLED = ('INSTALADO_M1', 'INSTALADO_M2')
STATE_FAPMETAL = 'EN_FAPMETAL'
STATE_REFILLED = 'RELLENADO_EN_STOCK'
STATE_DISCARDED = 'DESCARTADO'

MILL_TO_STATE = {
    'M1': 'INSTALADO_M1',
    'M2': 'INSTALADO_M2',
}
MILL_TO_RETIRE_EVENT = {'M1': 'RETIRAR_M1', 'M2': 'RETIRAR_M2'}
MILL_TO_INSTALL_EVENT = {'M1': 'INSTALAR_M1', 'M2': 'INSTALAR_M2'}


def register_hammer_batches_routes(
    app,
    db,
    logger,
    HammerBatch,
    HammerBatchMovement,
    WorkOrder,
    Provider=None,
    Equipment=None,
):
    def _record_movement(batch, event_type, *, state_from=None, state_to=None,
                         work_order_id=None, hammers_count=None, notes=None,
                         event_date=None, created_by=None):
        mov = HammerBatchMovement(
            batch_id=batch.id,
            event_type=event_type,
            event_date=event_date or dt.date.today().isoformat(),
            state_from=state_from,
            state_to=state_to,
            work_order_id=work_order_id,
            hammers_count=hammers_count if hammers_count is not None else batch.hammers_count,
            notes=notes,
            created_by=created_by,
        )
        db.session.add(mov)
        return mov

    def _fapmetal_provider_id():
        """Devuelve el id del proveedor FAPMETAL si existe, sino None."""
        if not Provider:
            return None
        try:
            p = Provider.query.filter(Provider.name.ilike('FAPMETAL%')).first()
            return p.id if p else None
        except Exception:
            return None

    # ── List & Create ────────────────────────────────────────────────────────
    @app.route('/api/hammer-batches', methods=['GET', 'POST'])
    def handle_hammer_batches():
        if request.method == 'POST':
            try:
                data = request.json or {}
                code = (data.get('code') or '').strip()
                if not code:
                    return jsonify({"error": "code requerido"}), 400
                if HammerBatch.query.filter_by(code=code).first():
                    return jsonify({"error": f"Lote con codigo {code} ya existe"}), 409

                batch = HammerBatch(
                    code=code,
                    state=data.get('state') or STATE_REFILLED,
                    hammers_count=int(data.get('hammers_count') or 72),
                    refill_count=int(data.get('refill_count') or 0),
                    purchased_at=data.get('purchased_at'),
                    provider_id=data.get('provider_id') or _fapmetal_provider_id(),
                    notes=data.get('notes'),
                    is_active=True,
                )
                db.session.add(batch)
                db.session.flush()
                _record_movement(
                    batch, 'ALTA',
                    state_from=None, state_to=batch.state,
                    notes=f"Alta inicial del lote {batch.code}",
                    created_by=data.get('created_by'),
                )
                db.session.commit()
                return jsonify(batch.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creando hammer batch: {e}")
                return jsonify({"error": str(e)}), 500

        # GET — lista todos los activos por defecto
        try:
            include_discarded = (request.args.get('include_discarded') or '').lower() in {'1', 'true', 'yes'}
            q = HammerBatch.query
            if not include_discarded:
                q = q.filter(HammerBatch.is_active == True)  # noqa: E712
            batches = q.order_by(HammerBatch.code).all()
            return jsonify([b.to_dict() for b in batches]), 200
        except Exception as e:
            logger.error(f"Error listando hammer batches: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Detail / Update ──────────────────────────────────────────────────────
    @app.route('/api/hammer-batches/<int:batch_id>', methods=['GET', 'PUT'])
    def handle_hammer_batch_id(batch_id):
        batch = HammerBatch.query.get(batch_id)
        if not batch:
            return jsonify({"error": "Lote no encontrado"}), 404

        if request.method == 'PUT':
            try:
                data = request.json or {}
                # Solo permitimos editar campos administrativos. El estado
                # se cambia por las acciones (/change, /receive, /discard).
                for field in ('code', 'hammers_count', 'notes', 'provider_id', 'purchased_at'):
                    if field in data:
                        setattr(batch, field, data[field])
                db.session.commit()
                return jsonify(batch.to_dict()), 200
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error actualizando hammer batch {batch_id}: {e}")
                return jsonify({"error": str(e)}), 500

        # GET — detalle + movements
        result = batch.to_dict()
        result['movements'] = [m.to_dict() for m in batch.movements]
        return jsonify(result), 200

    # ── Discard (baja de lote) ───────────────────────────────────────────────
    @app.route('/api/hammer-batches/<int:batch_id>/discard', methods=['POST'])
    def discard_hammer_batch(batch_id):
        batch = HammerBatch.query.get(batch_id)
        if not batch:
            return jsonify({"error": "Lote no encontrado"}), 404
        if batch.state == STATE_DISCARDED:
            return jsonify({"error": "Lote ya descartado"}), 400
        if batch.state in STATES_INSTALLED:
            return jsonify({"error": "No se puede descartar un lote instalado en un molino. Cambialo primero."}), 400

        try:
            data = request.json or {}
            today = data.get('event_date') or dt.date.today().isoformat()
            prev_state = batch.state
            batch.state = STATE_DISCARDED
            batch.discarded_at = today
            batch.is_active = False
            _record_movement(
                batch, 'DESCARTAR',
                state_from=prev_state, state_to=STATE_DISCARDED,
                event_date=today,
                notes=data.get('notes') or 'Lote dado de baja',
                created_by=data.get('created_by'),
            )
            db.session.commit()
            return jsonify(batch.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error descartando hammer batch {batch_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Receive refilled (lote vuelve de FAPMETAL) ───────────────────────────
    @app.route('/api/hammer-batches/<int:batch_id>/receive', methods=['POST'])
    def receive_refilled_batch(batch_id):
        batch = HammerBatch.query.get(batch_id)
        if not batch:
            return jsonify({"error": "Lote no encontrado"}), 404
        if batch.state != STATE_FAPMETAL:
            return jsonify({"error": f"El lote no esta en FAPMETAL (estado actual: {batch.state})"}), 400

        try:
            data = request.json or {}
            today = data.get('event_date') or dt.date.today().isoformat()
            prev_state = batch.state
            batch.state = STATE_REFILLED
            _record_movement(
                batch, 'RECIBIR_RELLENADO',
                state_from=prev_state, state_to=STATE_REFILLED,
                event_date=today,
                notes=data.get('notes') or f'Recibido rellenado de FAPMETAL',
                created_by=data.get('created_by'),
            )
            db.session.commit()
            return jsonify(batch.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error recibiendo hammer batch {batch_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Change batch in mill (la accion principal) ───────────────────────────
    @app.route('/api/hammer-batches/change', methods=['POST'])
    def change_hammer_batch():
        """Registra un cambio de martillos en M1 o M2.

        Body:
          mill: 'M1' | 'M2'                 (requerido)
          start_time: 'YYYY-MM-DD HH:MM'    (requerido)
          end_time: 'YYYY-MM-DD HH:MM'      (requerido)
          batch_out_id: int (opcional, se infiere si no viene)
          batch_in_id: int  (opcional, se infiere si no viene)
          hammers_changed_count: int (opcional, default = batch.hammers_count)
          equipment_id: int (opcional)
          lubrication_done: bool (default True)
          notes: str (opcional)
          technician_id: str (opcional)
          created_by: str (opcional)

        Efecto:
          - Crea WorkOrder preventiva.
          - batch_out: INSTALADO_Mx -> EN_FAPMETAL (movements RETIRAR + ENVIAR_FAPMETAL)
          - batch_in:  RELLENADO_EN_STOCK -> INSTALADO_Mx, refill_count += 1
        """
        try:
            data = request.json or {}
            mill = (data.get('mill') or '').upper().strip()
            if mill not in MILL_TO_STATE:
                return jsonify({"error": "mill debe ser 'M1' o 'M2'"}), 400

            start_time = (data.get('start_time') or '').strip()
            end_time = (data.get('end_time') or '').strip()
            if not start_time or not end_time:
                return jsonify({"error": "start_time y end_time son requeridos"}), 400

            target_state = MILL_TO_STATE[mill]  # INSTALADO_M1 o M2

            # ── Inferencia / validacion de batch_out ────────────────────────
            batch_out_id = data.get('batch_out_id')
            if batch_out_id:
                batch_out = HammerBatch.query.get(batch_out_id)
                if not batch_out:
                    return jsonify({"error": f"Lote saliente {batch_out_id} no encontrado"}), 404
                if batch_out.state != target_state:
                    return jsonify({
                        "error": f"Lote {batch_out.code} no esta en {target_state} (esta en {batch_out.state})"
                    }), 400
            else:
                candidates = HammerBatch.query.filter(
                    HammerBatch.state == target_state,
                    HammerBatch.is_active == True,  # noqa: E712
                ).all()
                if len(candidates) == 0:
                    return jsonify({"error": f"No hay lote en estado {target_state}"}), 400
                if len(candidates) > 1:
                    return jsonify({
                        "error": f"Hay {len(candidates)} lotes en {target_state}. Especifica batch_out_id.",
                        "candidates": [c.to_dict() for c in candidates],
                    }), 400
                batch_out = candidates[0]

            # ── Inferencia / validacion de batch_in ─────────────────────────
            batch_in_id = data.get('batch_in_id')
            if batch_in_id:
                batch_in = HammerBatch.query.get(batch_in_id)
                if not batch_in:
                    return jsonify({"error": f"Lote entrante {batch_in_id} no encontrado"}), 404
                if batch_in.state != STATE_REFILLED:
                    return jsonify({
                        "error": f"Lote {batch_in.code} no esta en {STATE_REFILLED} (esta en {batch_in.state})"
                    }), 400
            else:
                candidates = HammerBatch.query.filter(
                    HammerBatch.state == STATE_REFILLED,
                    HammerBatch.is_active == True,  # noqa: E712
                ).all()
                if len(candidates) == 0:
                    return jsonify({
                        "error": f"No hay lote en {STATE_REFILLED}. Verifica que FAPMETAL haya devuelto un lote rellenado."
                    }), 400
                if len(candidates) > 1:
                    return jsonify({
                        "error": f"Hay {len(candidates)} lotes en {STATE_REFILLED}. Especifica batch_in_id.",
                        "candidates": [c.to_dict() for c in candidates],
                    }), 400
                batch_in = candidates[0]

            if batch_out.id == batch_in.id:
                return jsonify({"error": "batch_out y batch_in no pueden ser el mismo lote"}), 400

            hammers_changed = int(data.get('hammers_changed_count') or batch_out.hammers_count)
            lubrication_done = data.get('lubrication_done', True)
            equipment_id = data.get('equipment_id')
            today = dt.date.today().isoformat()
            event_date = start_time[:10] if len(start_time) >= 10 else today

            # ── Crear OT ────────────────────────────────────────────────────
            lub_text = " + Lubricacion chumaceras motriz/conducida" if lubrication_done else ""
            description = (
                f"Cambio de martillos Molino #{mill[-1]} (Lote OUT: {batch_out.code} / "
                f"IN: {batch_in.code} | {hammers_changed} martillos){lub_text}"
            )
            user_notes = (data.get('notes') or '').strip()
            execution_comments_parts = [
                f"Lote retirado: {batch_out.code} -> EN_FAPMETAL",
                f"Lote instalado: {batch_in.code} (rellenado #{batch_in.refill_count + 1})",
                f"Martillos cambiados: {hammers_changed}",
            ]
            if lubrication_done:
                execution_comments_parts.append("Lubricacion chumaceras motriz y conducida: realizada")
            if user_notes:
                execution_comments_parts.append(f"Notas: {user_notes}")
            execution_comments = "\n".join(execution_comments_parts)

            # Calcular duracion real en horas
            real_duration = None
            try:
                fmt_candidates = ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S')
                start_dt = end_dt = None
                for fmt in fmt_candidates:
                    try:
                        start_dt = dt.datetime.strptime(start_time, fmt)
                        break
                    except ValueError:
                        pass
                for fmt in fmt_candidates:
                    try:
                        end_dt = dt.datetime.strptime(end_time, fmt)
                        break
                    except ValueError:
                        pass
                if start_dt and end_dt:
                    real_duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
            except Exception:
                real_duration = None

            wo = WorkOrder(
                description=description,
                maintenance_type='Preventivo',
                status='Cerrada',
                scheduled_date=event_date,
                real_start_date=start_time,
                real_end_date=end_time,
                real_duration=real_duration,
                estimated_duration=1.0,
                execution_comments=execution_comments,
                technician_id=data.get('technician_id') or 'FAPMETAL',
                provider_id=_fapmetal_provider_id(),
                equipment_id=equipment_id,
                caused_downtime=False,
            )
            db.session.add(wo)
            db.session.flush()
            wo.code = f"OT-{wo.id:04d}"

            # ── Mover lote saliente: INSTALADO_Mx -> EN_FAPMETAL ────────────
            prev_out_state = batch_out.state
            batch_out.state = STATE_FAPMETAL
            _record_movement(
                batch_out, MILL_TO_RETIRE_EVENT[mill],
                state_from=prev_out_state, state_to=STATE_FAPMETAL,
                work_order_id=wo.id,
                hammers_count=hammers_changed,
                event_date=event_date,
                notes=f"Retiro de molino {mill} hacia FAPMETAL (OT {wo.code})",
                created_by=data.get('created_by'),
            )
            _record_movement(
                batch_out, 'ENVIAR_FAPMETAL',
                state_from=STATE_FAPMETAL, state_to=STATE_FAPMETAL,
                work_order_id=wo.id,
                hammers_count=hammers_changed,
                event_date=event_date,
                notes='Envio al proveedor para rellenado',
                created_by=data.get('created_by'),
            )

            # ── Mover lote entrante: RELLENADO_EN_STOCK -> INSTALADO_Mx ─────
            prev_in_state = batch_in.state
            batch_in.state = target_state
            batch_in.refill_count += 1  # cuenta ciclos: cada vez que se reinstala
            _record_movement(
                batch_in, MILL_TO_INSTALL_EVENT[mill],
                state_from=prev_in_state, state_to=target_state,
                work_order_id=wo.id,
                hammers_count=hammers_changed,
                event_date=event_date,
                notes=f"Instalacion en molino {mill} (refill #{batch_in.refill_count}, OT {wo.code})",
                created_by=data.get('created_by'),
            )

            db.session.commit()

            return jsonify({
                "work_order": wo.to_dict(),
                "batch_out": batch_out.to_dict(),
                "batch_in": batch_in.to_dict(),
            }), 201

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error en cambio de hammer batch: {e}")
            return jsonify({"error": str(e)}), 500

    # ── State overview (resumen de los 3 lotes activos) ──────────────────────
    @app.route('/api/hammer-batches/state', methods=['GET'])
    def hammer_batches_state():
        """Resumen: que esta en M1, M2, FAPMETAL, RELLENADO_EN_STOCK."""
        try:
            active = HammerBatch.query.filter(HammerBatch.is_active == True).all()  # noqa: E712
            by_state = {}
            for b in active:
                by_state.setdefault(b.state, []).append(b.to_dict())
            return jsonify({
                "molino_1": by_state.get('INSTALADO_M1', []),
                "molino_2": by_state.get('INSTALADO_M2', []),
                "en_fapmetal": by_state.get(STATE_FAPMETAL, []),
                "rellenado_stock": by_state.get(STATE_REFILLED, []),
                "alertas": _state_alerts(by_state),
            }), 200
        except Exception as e:
            logger.error(f"Error en hammer-batches/state: {e}")
            return jsonify({"error": str(e)}), 500

    def _state_alerts(by_state):
        """Detecta anomalias en la distribucion de lotes."""
        alerts = []
        n_m1 = len(by_state.get('INSTALADO_M1', []))
        n_m2 = len(by_state.get('INSTALADO_M2', []))
        n_fap = len(by_state.get(STATE_FAPMETAL, []))
        n_stk = len(by_state.get(STATE_REFILLED, []))
        if n_m1 != 1:
            alerts.append(f"Molino #1 tiene {n_m1} lotes instalados (deberia ser 1)")
        if n_m2 != 1:
            alerts.append(f"Molino #2 tiene {n_m2} lotes instalados (deberia ser 1)")
        if n_fap + n_stk == 0:
            alerts.append("No hay ningun lote en transito ni en stock — proximo cambio no es posible")
        return alerts

    # ── Conciliacion FAPMETAL ────────────────────────────────────────────────
    @app.route('/api/hammer-batches/conciliation', methods=['GET'])
    def hammer_batches_conciliation():
        """Reporte de conciliacion contra informe de FAPMETAL.

        Query:
          start: 'YYYY-MM-DD' (default: hoy - 90d)
          end:   'YYYY-MM-DD' (default: hoy)
        """
        try:
            today = dt.date.today()
            start = request.args.get('start') or (today - dt.timedelta(days=90)).isoformat()
            end = request.args.get('end') or today.isoformat()

            # Cambios por molino en el periodo
            mov_q = db.session.query(
                HammerBatchMovement.event_type,
                func.count(HammerBatchMovement.id),
                func.sum(HammerBatchMovement.hammers_count),
            ).filter(
                HammerBatchMovement.event_date >= start,
                HammerBatchMovement.event_date <= end,
            ).group_by(HammerBatchMovement.event_type).all()

            summary = {ev: {"count": int(c or 0), "hammers": int(h or 0)} for ev, c, h in mov_q}

            cambios_m1 = summary.get('RETIRAR_M1', {}).get('count', 0)
            cambios_m2 = summary.get('RETIRAR_M2', {}).get('count', 0)
            enviados = summary.get('ENVIAR_FAPMETAL', {})
            recibidos = summary.get('RECIBIR_RELLENADO', {})

            # Detalle por lote
            detail_rows = db.session.query(
                HammerBatchMovement.batch_id,
                HammerBatch.code,
                HammerBatchMovement.event_type,
                func.count(HammerBatchMovement.id),
                func.sum(HammerBatchMovement.hammers_count),
            ).join(HammerBatch, HammerBatch.id == HammerBatchMovement.batch_id).filter(
                HammerBatchMovement.event_date >= start,
                HammerBatchMovement.event_date <= end,
                HammerBatchMovement.event_type.in_(['RECIBIR_RELLENADO', 'ENVIAR_FAPMETAL']),
            ).group_by(
                HammerBatchMovement.batch_id, HammerBatch.code, HammerBatchMovement.event_type
            ).all()

            by_batch = {}
            for batch_id, code, ev, c, h in detail_rows:
                row = by_batch.setdefault(code, {"code": code, "enviados": 0, "recibidos": 0,
                                                  "hammers_enviados": 0, "hammers_recibidos": 0})
                if ev == 'ENVIAR_FAPMETAL':
                    row['enviados'] = int(c or 0)
                    row['hammers_enviados'] = int(h or 0)
                elif ev == 'RECIBIR_RELLENADO':
                    row['recibidos'] = int(c or 0)
                    row['hammers_recibidos'] = int(h or 0)

            # Saldo en FAPMETAL HOY (lotes en estado EN_FAPMETAL)
            in_fapmetal_now = HammerBatch.query.filter(
                HammerBatch.state == STATE_FAPMETAL,
                HammerBatch.is_active == True,  # noqa: E712
            ).all()

            return jsonify({
                "period": {"start": start, "end": end},
                "totals": {
                    "cambios_molino_1": cambios_m1,
                    "cambios_molino_2": cambios_m2,
                    "cambios_total": cambios_m1 + cambios_m2,
                    "envios_fapmetal_count": enviados.get('count', 0),
                    "martillos_enviados": enviados.get('hammers', 0),
                    "recepciones_fapmetal_count": recibidos.get('count', 0),
                    "martillos_recibidos": recibidos.get('hammers', 0),
                    "saldo_pendiente_count": enviados.get('count', 0) - recibidos.get('count', 0),
                    "saldo_pendiente_hammers": enviados.get('hammers', 0) - recibidos.get('hammers', 0),
                },
                "by_batch": list(by_batch.values()),
                "in_fapmetal_now": [
                    {**b.to_dict(), "days_pending": _days_since_last_event(b, 'ENVIAR_FAPMETAL')}
                    for b in in_fapmetal_now
                ],
            }), 200
        except Exception as e:
            logger.error(f"Error en conciliacion FAPMETAL: {e}")
            return jsonify({"error": str(e)}), 500

    def _days_since_last_event(batch, event_type):
        last = HammerBatchMovement.query.filter_by(
            batch_id=batch.id, event_type=event_type
        ).order_by(HammerBatchMovement.event_date.desc()).first()
        if not last or not last.event_date:
            return None
        try:
            ed = dt.datetime.strptime(last.event_date[:10], '%Y-%m-%d').date()
            return (dt.date.today() - ed).days
        except Exception:
            return None
