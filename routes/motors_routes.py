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

    def _measure_schedule(asset):
        """next_due, status de la ruta MENSUAL de corriente/temperatura."""
        return _calculate_monitoring_schedule(
            asset.last_measure_date,
            asset.measure_frequency_days or 30,
            asset.measure_warning_days or 5,
        )

    def _nominal_current(asset):
        """Corriente nominal (placa). Si no está, la estima desde HP y voltaje
        (3F): In ≈ HP*746 / (√3 * V * η * fp), con η≈0.88 y fp≈0.85.
        Devuelve (amperios, estimado?)."""
        if asset.rated_current_a:
            return float(asset.rated_current_a), False
        if asset.rated_hp and asset.rated_voltage_v:
            try:
                est = (float(asset.rated_hp) * 746.0) / (1.732 * float(asset.rated_voltage_v) * 0.88 * 0.85)
                return round(est, 1), True
            except Exception:
                return None, False
        return None, False

    def _overload_status(asset, max_phase):
        """% de carga y semáforo de la corriente medida vs la nominal."""
        nom, _est = _nominal_current(asset)
        if not nom or max_phase is None:
            return None, None
        pct = round(max_phase / nom * 100)
        alarm = float(asset.current_alarm_pct or 110)
        if pct >= alarm:
            st = 'ROJO'
        elif pct >= 100:
            st = 'AMARILLO'
        else:
            st = 'VERDE'
        return pct, st

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
            summary = {'vencido': 0, 'proximo': 0, 'al_dia': 0, 'pendiente': 0, 'en_taller': 0,
                       'm_vencido': 0, 'm_proximo': 0, 'm_aldia': 0, 'm_pendiente': 0}
            for m in motors:
                next_due, mstatus = _megado_schedule(m)
                next_meas, measure_status = _measure_schedule(m)
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
                if measure_status == 'ROJO':
                    summary['m_vencido'] += 1
                elif measure_status == 'AMARILLO':
                    summary['m_proximo'] += 1
                elif measure_status == 'VERDE':
                    summary['m_aldia'] += 1
                else:
                    summary['m_pendiente'] += 1
                if (m.status or '') in ('En Taller', 'Taller'):
                    summary['en_taller'] += 1
                nom, nom_est = _nominal_current(m)
                cur_phases = [cur.current_r, cur.current_s, cur.current_t] if cur else []
                cur_max = max([p for p in cur_phases if p is not None], default=None)
                load_pct, overload_status = _overload_status(m, cur_max)
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
                    'last_current_load_pct': load_pct,
                    'last_current_overload': overload_status,
                    'last_temp_date': tem.test_date if tem else None,
                    'last_temperature_c': tem.temperature_c if tem else None,
                    'rated_hp': m.rated_hp,
                    'rated_voltage_v': m.rated_voltage_v,
                    'rated_current_a': nom,
                    'rated_current_estimated': nom_est,
                    'current_alarm_pct': m.current_alarm_pct,
                    'measure_frequency_days': m.measure_frequency_days,
                    'next_measure_due': next_meas,
                    'measure_status': measure_status,
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
                voltage_rs=_f('voltage_rs'), voltage_st=_f('voltage_st'), voltage_tr=_f('voltage_tr'),
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

            elif ttype in ('CORRIENTE', 'TEMPERATURA'):
                # Ruta MENSUAL: actualizar la programación de medición
                asset.last_measure_date = test_date
                nd, sched = _measure_schedule(asset)
                asset.next_measure_due = nd
                asset.measure_status = sched
                if ttype == 'CORRIENTE':
                    # Relacionar con la placa: % de la corriente nominal
                    phases = [test.current_r, test.current_s, test.current_t]
                    cur_max = max([p for p in phases if p is not None], default=None)
                    pct, ov = _overload_status(asset, cur_max)
                    test.status = ov
                    value_status = ov
                    create_notice = bool(data.get('create_notice', True))
                    if create_notice and ov == 'ROJO':
                        nom, _e = _nominal_current(asset)
                        notice = MaintenanceNotice(
                            reporter_name=test.executed_by or "Tecnico Electrico",
                            reporter_type="MOTOR",
                            area_id=asset.area_id, line_id=asset.line_id,
                            equipment_id=asset.equipment_id, system_id=asset.system_id,
                            component_id=asset.component_id,
                            description=(f"[MOTOR] {asset.code} {asset.name}: SOBRECARGA — corriente "
                                         f"{cur_max} A ≈ {pct}% de la nominal ({nom} A)"),
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

            def _setf(attr, key):
                v = data.get(key)
                if v in (None, ''):
                    return
                try:
                    setattr(asset, attr, float(v))
                except Exception:
                    pass

            def _seti(attr, key):
                v = data.get(key)
                if v in (None, ''):
                    return
                try:
                    setattr(asset, attr, int(v))
                except Exception:
                    pass

            if 'is_electric_motor' in data:
                asset.is_electric_motor = bool(data['is_electric_motor'])
            _seti('megado_frequency_days', 'megado_frequency_days')
            _setf('megado_min_mohm', 'megado_min_mohm')
            _setf('rated_hp', 'rated_hp')
            _setf('rated_voltage_v', 'rated_voltage_v')
            _setf('rated_current_a', 'rated_current_a')
            _setf('current_alarm_pct', 'current_alarm_pct')
            _seti('measure_frequency_days', 'measure_frequency_days')

            nd1, s1 = _megado_schedule(asset)
            asset.next_megado_due, asset.megado_status = nd1, s1
            nd2, s2 = _measure_schedule(asset)
            asset.next_measure_due, asset.measure_status = nd2, s2
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
