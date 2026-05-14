"""Acciones del bot relacionadas con lotes de martillos FAPMETAL.

Estas funciones replican la logica de los endpoints /api/hammer-batches/change
y /api/hammer-batches/<id>/receive para que el bot pueda registrar cambios
desde voz/texto sin pasar por HTTP.
"""
import logging
from datetime import date as _date, datetime as _datetime

logger = logging.getLogger(__name__)


def change_hammer_batch(app, data):
    """Registra cambio de lote de martillos en M1 o M2.

    Si batch_out/batch_in no vienen explicitos, se infieren del estado actual
    (deberia haber 1 en INSTALADO_Mx y 1 en RELLENADO_EN_STOCK).

    Returns: (info_dict | None, err | None).
    """
    with app.app_context():
        from database import db as _db
        from models import HammerBatch, HammerBatchMovement, WorkOrder, Provider
        try:
            mill = (data.get('mill') or '').upper().strip()
            if mill not in ('M1', 'M2'):
                return None, "Falta especificar molino (M1 o M2)"

            start_time = (data.get('start_time') or '').strip()
            end_time = (data.get('end_time') or '').strip()
            if not start_time or not end_time:
                return None, "Faltan hora inicio y/o hora fin"

            target_state = f'INSTALADO_{mill}'

            # Batch saliente
            batch_out_code = (data.get('batch_out_code') or '').strip()
            if batch_out_code:
                batch_out = HammerBatch.query.filter_by(code=batch_out_code).first()
                if not batch_out:
                    return None, f"Lote {batch_out_code} no encontrado"
                if batch_out.state != target_state:
                    return None, f"Lote {batch_out.code} no esta en Molino #{mill[-1]} (estado: {batch_out.state})"
            else:
                cands = HammerBatch.query.filter(
                    HammerBatch.state == target_state,
                    HammerBatch.is_active == True,  # noqa: E712
                ).all()
                if len(cands) == 0:
                    return None, f"No hay lote instalado en Molino #{mill[-1]}"
                if len(cands) > 1:
                    return None, f"Multiples lotes en Molino #{mill[-1]}: {[c.code for c in cands]}. Especifica batch_out_code."
                batch_out = cands[0]

            # Batch entrante
            batch_in_code = (data.get('batch_in_code') or '').strip()
            if batch_in_code:
                batch_in = HammerBatch.query.filter_by(code=batch_in_code).first()
                if not batch_in:
                    return None, f"Lote {batch_in_code} no encontrado"
                if batch_in.state != 'RELLENADO_EN_STOCK':
                    return None, f"Lote {batch_in.code} no esta en RELLENADO_EN_STOCK (estado: {batch_in.state})"
            else:
                cands = HammerBatch.query.filter(
                    HammerBatch.state == 'RELLENADO_EN_STOCK',
                    HammerBatch.is_active == True,  # noqa: E712
                ).all()
                if len(cands) == 0:
                    return None, "No hay lote rellenado disponible en stock. Verifica que FAPMETAL haya devuelto el lote."
                if len(cands) > 1:
                    return None, f"Multiples lotes en stock: {[c.code for c in cands]}. Especifica batch_in_code."
                batch_in = cands[0]

            if batch_out.id == batch_in.id:
                return None, "Lote saliente y entrante no pueden ser el mismo"

            hammers_changed = int(data.get('hammers_changed_count') or batch_out.hammers_count)
            lubrication_done = data.get('lubrication_done', True)
            event_date = start_time[:10] if len(start_time) >= 10 else _date.today().isoformat()

            real_duration = None
            for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
                try:
                    sd = _datetime.strptime(start_time, fmt)
                    ed = _datetime.strptime(end_time, fmt)
                    real_duration = round((ed - sd).total_seconds() / 3600, 2)
                    break
                except ValueError:
                    continue

            lub_text = " + Lubricacion chumaceras motriz/conducida" if lubrication_done else ""
            description = (
                f"Cambio de martillos Molino #{mill[-1]} (Lote OUT: {batch_out.code} / "
                f"IN: {batch_in.code} | {hammers_changed} martillos){lub_text}"
            )
            user_notes = (data.get('notes') or '').strip()
            ec = [
                f"Lote retirado: {batch_out.code} -> EN_FAPMETAL",
                f"Lote instalado: {batch_in.code} (rellenado #{batch_in.refill_count + 1})",
                f"Martillos cambiados: {hammers_changed}",
            ]
            if lubrication_done:
                ec.append("Lubricacion chumaceras motriz y conducida: realizada")
            if user_notes:
                ec.append(f"Notas: {user_notes}")

            fap = Provider.query.filter(Provider.name.ilike('FAPMETAL%')).first()
            wo = WorkOrder(
                description=description,
                maintenance_type='Preventivo',
                status='Cerrada',
                scheduled_date=event_date,
                real_start_date=start_time,
                real_end_date=end_time,
                real_duration=real_duration,
                estimated_duration=1.0,
                execution_comments="\n".join(ec),
                technician_id=data.get('technician_id') or 'FAPMETAL',
                provider_id=fap.id if fap else None,
                caused_downtime=False,
            )
            _db.session.add(wo)
            _db.session.flush()
            wo.code = f"OT-{wo.id:04d}"

            prev_out_state = batch_out.state
            batch_out.state = 'EN_FAPMETAL'
            _db.session.add(HammerBatchMovement(
                batch_id=batch_out.id, event_type=f'RETIRAR_{mill}',
                event_date=event_date, state_from=prev_out_state, state_to='EN_FAPMETAL',
                work_order_id=wo.id, hammers_count=hammers_changed,
                notes=f"Retiro de molino {mill} hacia FAPMETAL (OT {wo.code})",
                created_by='telegram_bot',
            ))
            _db.session.add(HammerBatchMovement(
                batch_id=batch_out.id, event_type='ENVIAR_FAPMETAL',
                event_date=event_date, state_from='EN_FAPMETAL', state_to='EN_FAPMETAL',
                work_order_id=wo.id, hammers_count=hammers_changed,
                notes='Envio al proveedor para rellenado',
                created_by='telegram_bot',
            ))

            prev_in_state = batch_in.state
            batch_in.state = target_state
            batch_in.refill_count += 1
            _db.session.add(HammerBatchMovement(
                batch_id=batch_in.id, event_type=f'INSTALAR_{mill}',
                event_date=event_date, state_from=prev_in_state, state_to=target_state,
                work_order_id=wo.id, hammers_count=hammers_changed,
                notes=f"Instalacion en molino {mill} (refill #{batch_in.refill_count}, OT {wo.code})",
                created_by='telegram_bot',
            ))

            _db.session.commit()

            return {
                'ot_code': wo.code,
                'mill': mill,
                'batch_out_code': batch_out.code,
                'batch_in_code': batch_in.code,
                'batch_in_refill_count': batch_in.refill_count,
                'hammers_changed': hammers_changed,
                'duration_h': real_duration,
                'lubrication_done': lubrication_done,
                'event_date': event_date,
            }, None
        except Exception as e:
            _db.session.rollback()
            logger.error(f"change_hammer_batch error: {e}")
            return None, str(e)


def receive_hammer_batch(app, data):
    """Marca un lote como recibido rellenado desde FAPMETAL.

    Si batch_code no viene y hay un solo lote en EN_FAPMETAL, lo infiere.

    Returns: (info_dict | None, err | None).
    """
    with app.app_context():
        from database import db as _db
        from models import HammerBatch, HammerBatchMovement
        try:
            batch_code = (data.get('batch_code') or '').strip()
            if batch_code:
                batch = HammerBatch.query.filter_by(code=batch_code).first()
                if not batch:
                    return None, f"Lote {batch_code} no encontrado"
                if batch.state != 'EN_FAPMETAL':
                    return None, f"Lote {batch.code} no esta en FAPMETAL (estado: {batch.state})"
            else:
                cands = HammerBatch.query.filter_by(state='EN_FAPMETAL', is_active=True).all()
                if len(cands) == 0:
                    return None, "No hay lotes en FAPMETAL para recibir"
                if len(cands) > 1:
                    return None, f"Multiples lotes en FAPMETAL: {[c.code for c in cands]}. Especifica batch_code."
                batch = cands[0]

            event_date = (data.get('event_date') or _date.today().isoformat())
            prev = batch.state
            batch.state = 'RELLENADO_EN_STOCK'
            _db.session.add(HammerBatchMovement(
                batch_id=batch.id, event_type='RECIBIR_RELLENADO',
                event_date=event_date, state_from=prev, state_to='RELLENADO_EN_STOCK',
                notes=(data.get('notes') or 'Recibido rellenado de FAPMETAL'),
                created_by='telegram_bot',
            ))
            _db.session.commit()
            return {'code': batch.code, 'event_date': event_date, 'refill_count': batch.refill_count}, None
        except Exception as e:
            _db.session.rollback()
            logger.error(f"receive_hammer_batch error: {e}")
            return None, str(e)
