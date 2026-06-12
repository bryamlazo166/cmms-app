"""Módulo Motores Eléctricos.

Megado (resistencia de aislamiento, semestral + ad-hoc), corriente por fase
(R/S/T) y temperatura de los motores eléctricos de la planta. Los motores son
RotativeAsset marcados con is_electric_motor=True (cubre motores sueltos y
acoplados: motorreductores, bombas, ventiladores). Los registros se anclan al
motor para que el historial lo siga cuando se mueve entre taller y equipos.
"""
import datetime as dt

from flask import jsonify, request, render_template

from utils.schedule_helpers import _calculate_monitoring_schedule


def register_motors_routes(app, db, logger, RotativeAsset, MotorElectricalTest,
                           MaintenanceNotice, Equipment):

    def _megado_schedule(asset):
        """next_due, status (por tiempo) del megado desde last_megado_date."""
        return _calculate_monitoring_schedule(
            asset.last_megado_date,
            asset.megado_frequency_days or 180,
            asset.megado_warning_days or 14,
        )

    @app.route('/motores-electricos', methods=['GET'])
    def motores_electricos_page():
        return render_template('motores_electricos.html')

    @app.route('/api/motors', methods=['GET'])
    def list_motors():
        """Motores eléctricos con último megado/corriente/temperatura y el
        semáforo de megado (vencido/próximo/al día)."""
        try:
            motors = RotativeAsset.query.filter_by(
                is_electric_motor=True, is_active=True).all()
            ids = [m.id for m in motors]
            last_by = {}  # (asset_id, test_type) -> test mas reciente
            if ids:
                tests = (MotorElectricalTest.query
                         .filter(MotorElectricalTest.rotative_asset_id.in_(ids))
                         .order_by(MotorElectricalTest.test_date.desc(),
                                   MotorElectricalTest.id.desc())
                         .all())
                for t in tests:
                    key = (t.rotative_asset_id, t.test_type)
                    if key not in last_by:
                        last_by[key] = t

            rows = []
            summary = {'vencido': 0, 'proximo': 0, 'al_dia': 0, 'pendiente': 0, 'en_taller': 0}
            for m in motors:
                next_due, mstatus = _megado_schedule(m)
                meg = last_by.get((m.id, 'MEGADO'))
                cur = last_by.get((m.id, 'CORRIENTE'))
                tem = last_by.get((m.id, 'TEMPERATURA'))
                if mstatus == 'ROJO':
                    summary['vencido'] += 1
                elif mstatus == 'AMARILLO':
                    summary['proximo'] += 1
                elif mstatus == 'VERDE':
                    summary['al_dia'] += 1
                else:
                    summary['pendiente'] += 1
                if (m.status or '') in ('En Taller', 'Taller'):
                    summary['en_taller'] += 1
                rows.append({
                    'id': m.id, 'code': m.code, 'name': m.name, 'category': m.category,
                    'status': m.status,
                    'area_name': m.area.name if m.area else None,
                    'line_name': m.line.name if m.line else None,
                    'equipment_tag': m.equipment.tag if m.equipment else None,
                    'equipment_name': m.equipment.name if m.equipment else None,
                    'megado_frequency_days': m.megado_frequency_days,
                    'megado_min_mohm': m.megado_min_mohm,
                    'last_megado_date': m.last_megado_date,
                    'next_megado_due': next_due,
                    'megado_status': mstatus,
                    'last_megado_mohm': meg.insulation_mohm if meg else None,
                    'last_current_date': cur.test_date if cur else None,
                    'last_current_r': cur.current_r if cur else None,
                    'last_current_s': cur.current_s if cur else None,
                    'last_current_t': cur.current_t if cur else None,
                    'last_temp_date': tem.test_date if tem else None,
                    'last_temperature_c': tem.temperature_c if tem else None,
                })
            rank = {'ROJO': 0, 'AMARILLO': 1, 'PENDIENTE': 2, 'VERDE': 3}
            rows.sort(key=lambda r: (rank.get(r['megado_status'], 9), r['code'] or ''))
            return jsonify({'rows': rows, 'summary': summary, 'total': len(rows)})
        except Exception as e:
            logger.exception(f"list_motors error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/motors/<int:asset_id>/tests', methods=['GET', 'POST'])
    def motor_tests(asset_id):
        asset = RotativeAsset.query.get(asset_id)
        if not asset:
            return jsonify({"error": "Motor no encontrado"}), 404

        if request.method == 'GET':
            tests = (MotorElectricalTest.query
                     .filter_by(rotative_asset_id=asset_id)
                     .order_by(MotorElectricalTest.test_date.desc(),
                               MotorElectricalTest.id.desc()).all())
            return jsonify([t.to_dict() for t in tests])

        # POST — registrar una prueba (megado / corriente / temperatura)
        try:
            data = request.json or {}
            ttype = (data.get('test_type') or '').upper()
            if ttype not in ('MEGADO', 'CORRIENTE', 'TEMPERATURA'):
                return jsonify({"error": "test_type debe ser MEGADO, CORRIENTE o TEMPERATURA"}), 400
            test_date = data.get('test_date') or dt.date.today().isoformat()

            def _f(k):
                v = data.get(k)
                if v in (None, ''):
                    return None
                try:
                    return float(v)
                except Exception:
                    return None

            def _i(k):
                v = data.get(k)
                if v in (None, ''):
                    return None
                try:
                    return int(v)
                except Exception:
                    return None

            test = MotorElectricalTest(
                rotative_asset_id=asset.id,
                test_type=ttype,
                test_date=test_date,
                context=(data.get('context') or 'PROGRAMADO'),
                insulation_mohm=_f('insulation_mohm'),
                test_voltage_v=_i('test_voltage_v'),
                current_r=_f('current_r'), current_s=_f('current_s'), current_t=_f('current_t'),
                temperature_c=_f('temperature_c'),
                temp_point=(data.get('temp_point') or None),
                equipment_id=asset.equipment_id,
                executed_by=(data.get('executed_by') or None),
                notes=(data.get('notes') or None),
                photo_url=(data.get('photo_url') or None),
            )

            value_status = None
            if ttype == 'MEGADO':
                # Semáforo por valor: aislamiento bajo el mínimo => ROJO
                if test.insulation_mohm is not None and asset.megado_min_mohm is not None:
                    value_status = 'ROJO' if test.insulation_mohm < float(asset.megado_min_mohm) else 'VERDE'
                test.status = value_status
                # Actualizar programación semestral
                asset.last_megado_date = test_date
                next_due, sched_status = _megado_schedule(asset)
                asset.next_megado_due = next_due
                asset.megado_status = ('ROJO' if value_status == 'ROJO' else sched_status)

                # Auto-aviso si el aislamiento está bajo el mínimo
                create_notice = bool(data.get('create_notice', True))
                if create_notice and value_status == 'ROJO':
                    notice = MaintenanceNotice(
                        reporter_name=test.executed_by or "Tecnico Electrico",
                        reporter_type="MEGADO",
                        area_id=asset.area_id, line_id=asset.line_id,
                        equipment_id=asset.equipment_id, system_id=asset.system_id,
                        component_id=asset.component_id,
                        description=(f"[MEGADO] {asset.code} {asset.name}: aislamiento "
                                     f"{test.insulation_mohm} MΩ < mínimo {asset.megado_min_mohm} MΩ"),
                        maintenance_type="Correctivo", priority="Alta",
                        status="Pendiente", request_date=dt.date.today().isoformat(),
                        rotative_asset_id=asset.id,
                    )
                    db.session.add(notice)
                    db.session.flush()
                    notice.code = f"AV-{notice.id:04d}"
                    test.created_notice_id = notice.id

            db.session.add(test)
            db.session.commit()
            payload = test.to_dict()
            payload['value_status'] = value_status
            return jsonify(payload), 201
        except Exception as e:
            db.session.rollback()
            logger.exception(f"motor_tests POST error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/motors/<int:asset_id>/config', methods=['PUT'])
    def motor_config(asset_id):
        """Editar config de megado del motor (frecuencia, umbral) y el flag."""
        asset = RotativeAsset.query.get(asset_id)
        if not asset:
            return jsonify({"error": "Motor no encontrado"}), 404
        try:
            data = request.json or {}
            if 'is_electric_motor' in data:
                asset.is_electric_motor = bool(data['is_electric_motor'])
            if data.get('megado_frequency_days') not in (None, ''):
                asset.megado_frequency_days = int(data['megado_frequency_days'])
            if data.get('megado_min_mohm') not in (None, ''):
                asset.megado_min_mohm = float(data['megado_min_mohm'])
            next_due, status = _megado_schedule(asset)
            asset.next_megado_due = next_due
            asset.megado_status = status
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.exception(f"motor_config error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/motors/manage', methods=['GET', 'POST'])
    def manage_motors():
        """Curar la lista de motores: marcar/desmarcar is_electric_motor en lote."""
        if request.method == 'GET':
            assets = (RotativeAsset.query.filter_by(is_active=True)
                      .order_by(RotativeAsset.code).all())
            return jsonify([{
                'id': a.id, 'code': a.code, 'name': a.name, 'category': a.category,
                'status': a.status, 'is_electric_motor': bool(a.is_electric_motor),
                'equipment_tag': a.equipment.tag if a.equipment else None,
            } for a in assets])
        try:
            data = request.json or {}
            ids = data.get('ids') or []
            val = bool(data.get('is_electric_motor', True))
            if ids:
                for a in RotativeAsset.query.filter(RotativeAsset.id.in_(ids)).all():
                    a.is_electric_motor = val
                    if val and not a.megado_frequency_days:
                        a.megado_frequency_days = 180
                db.session.commit()
            return jsonify({"updated": len(ids)})
        except Exception as e:
            db.session.rollback()
            logger.exception(f"manage_motors error: {e}")
            return jsonify({"error": str(e)}), 500
