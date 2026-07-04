"""Equipos Alquilados (RDrental u otros proveedores de flota movil).

Seguimiento de montacargas y minicargadores alquilados:
  - Horometros (lecturas periodicas + % de vida hacia el cambio a 4000 h)
  - Fallas con doble atribucion de responsabilidad (proveedor vs. nuestra)
  - Deteccion de fallas repetitivas (mismo sistema en ventana de dias)
  - Export a Excel para sustentar reclamos ante el proveedor
"""
from datetime import datetime, timedelta
from io import BytesIO

from flask import jsonify, render_template, request, send_file
from flask_login import current_user, login_required

# Ventana (dias) para considerar que una falla del mismo sistema es "repetida".
REPEAT_WINDOW_DAYS = 30
FAILURE_SYSTEMS = ['MOTOR', 'HIDRAULICO', 'ELECTRICO', 'TRANSMISION', 'FRENOS',
                   'LLANTAS', 'TREN_RODAJE', 'MASTIL_UNAS', 'CABINA', 'OTRO']
RESPONSIBILITIES = ['NUESTRA', 'PROVEEDOR', 'COMPARTIDA', 'SIN_DEFINIR']


def _parse_date(s):
    try:
        return datetime.strptime((s or '')[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def register_rental_routes(app, db, logger, RentalEquipment,
                           RentalHorometerReading, RentalFailure):

    @app.route('/equipos-alquilados')
    @login_required
    def rental_equipment_page():
        return render_template('rental_equipment.html')

    # ── Equipos ────────────────────────────────────────────────────────────

    @app.route('/api/rental/equipments', methods=['GET', 'POST'])
    @login_required
    def rental_equipments():
        if request.method == 'POST':
            data = request.get_json() or {}
            name = (data.get('name') or '').strip()
            if not name:
                return jsonify({"error": "El nombre del equipo es obligatorio."}), 400
            eq = RentalEquipment(
                code='ALQ-TEMP',
                name=name,
                equipment_type=(data.get('equipment_type') or 'MONTACARGA').strip().upper(),
                brand=(data.get('brand') or '').strip() or None,
                model=(data.get('model') or '').strip() or None,
                serial_number=(data.get('serial_number') or '').strip() or None,
                provider_name=(data.get('provider_name') or 'RDRENTAL').strip().upper() or 'RDRENTAL',
                location=(data.get('location') or '').strip() or None,
                replacement_hours=float(data.get('replacement_hours') or 4000),
                initial_horometer=float(data.get('initial_horometer') or 0),
                current_horometer=float(data.get('current_horometer')
                                        or data.get('initial_horometer') or 0),
                horometer_updated_at=data.get('horometer_updated_at') or None,
                start_date=data.get('start_date') or None,
                monthly_cost=float(data['monthly_cost']) if data.get('monthly_cost') else None,
                status=(data.get('status') or 'OPERATIVO').strip().upper(),
                notes=(data.get('notes') or '').strip() or None,
            )
            try:
                db.session.add(eq)
                db.session.flush()
                eq.code = f"ALQ-{eq.id:03d}"
                db.session.commit()
                logger.info(f"Rental equipment created: {eq.code} by "
                            f"{getattr(current_user, 'username', '?')}")
                return jsonify(eq.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
        qry = RentalEquipment.query
        if not show_inactive:
            qry = qry.filter_by(is_active=True)
        return jsonify([e.to_dict() for e in qry.order_by(RentalEquipment.code).all()])

    @app.route('/api/rental/equipments/<int:eq_id>', methods=['PUT', 'DELETE'])
    @login_required
    def rental_equipment_detail(eq_id):
        eq = RentalEquipment.query.get_or_404(eq_id)
        if request.method == 'DELETE':
            # Soft toggle: mantiene el historial de fallas para sustento.
            eq.is_active = not eq.is_active
            db.session.commit()
            return jsonify({"ok": True, "is_active": eq.is_active})

        data = request.get_json() or {}
        editable = ('name', 'equipment_type', 'brand', 'model', 'serial_number',
                    'provider_name', 'location', 'replacement_hours',
                    'initial_horometer', 'current_horometer', 'horometer_updated_at',
                    'start_date', 'monthly_cost', 'status', 'notes')
        try:
            for key in editable:
                if key in data:
                    val = data[key]
                    if isinstance(val, str):
                        val = val.strip() or None
                    setattr(eq, key, val)
            if eq.replacement_hours in (None, ''):
                eq.replacement_hours = 4000
            db.session.commit()
            return jsonify(eq.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── Horometros ─────────────────────────────────────────────────────────

    @app.route('/api/rental/equipments/<int:eq_id>/horometer', methods=['GET', 'POST'])
    @login_required
    def rental_horometer(eq_id):
        eq = RentalEquipment.query.get_or_404(eq_id)
        if request.method == 'GET':
            rows = (RentalHorometerReading.query.filter_by(rental_id=eq_id)
                    .order_by(RentalHorometerReading.reading_date.desc(),
                              RentalHorometerReading.id.desc()).limit(200).all())
            return jsonify([r.to_dict() for r in rows])

        data = request.get_json() or {}
        try:
            horometer = float(data.get('horometer'))
        except (TypeError, ValueError):
            return jsonify({"error": "Horometro invalido."}), 400
        reading_date = (data.get('reading_date') or datetime.now().strftime('%Y-%m-%d'))[:10]
        if horometer < (eq.current_horometer or 0):
            # Permitido (correccion / cambio de unidad) pero se deja constancia.
            logger.warning(f"Rental {eq.code}: lectura {horometer} menor a la actual "
                           f"{eq.current_horometer} (posible correccion o cambio de unidad)")
        reading = RentalHorometerReading(
            rental_id=eq_id,
            reading_date=reading_date,
            horometer=horometer,
            notes=(data.get('notes') or '').strip() or None,
            created_by=getattr(current_user, 'username', None),
        )
        try:
            db.session.add(reading)
            # La lectura mas reciente por fecha manda sobre el acumulado.
            if not eq.horometer_updated_at or reading_date >= eq.horometer_updated_at:
                eq.current_horometer = horometer
                eq.horometer_updated_at = reading_date
            db.session.commit()
            return jsonify(reading.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rental/horometer/<int:reading_id>', methods=['DELETE'])
    @login_required
    def rental_horometer_delete(reading_id):
        reading = RentalHorometerReading.query.get_or_404(reading_id)
        eq = reading.equipment
        try:
            db.session.delete(reading)
            db.session.flush()
            last = (RentalHorometerReading.query.filter_by(rental_id=eq.id)
                    .order_by(RentalHorometerReading.reading_date.desc(),
                              RentalHorometerReading.id.desc()).first())
            eq.current_horometer = last.horometer if last else (eq.initial_horometer or 0)
            eq.horometer_updated_at = last.reading_date if last else None
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── Fallas ─────────────────────────────────────────────────────────────

    @app.route('/api/rental/failures', methods=['GET', 'POST'])
    @login_required
    def rental_failures():
        if request.method == 'POST':
            data = request.get_json() or {}
            rental_id = data.get('rental_id')
            eq = RentalEquipment.query.get(rental_id) if rental_id else None
            if not eq:
                return jsonify({"error": "Selecciona un equipo valido."}), 400
            description = (data.get('description') or '').strip()
            if not description:
                return jsonify({"error": "Describe la falla."}), 400
            failure = RentalFailure(
                rental_id=eq.id,
                reported_date=(data.get('reported_date')
                               or datetime.now().strftime('%Y-%m-%d'))[:10],
                attended_date=data.get('attended_date') or None,
                resolved_date=data.get('resolved_date') or None,
                description=description,
                failure_system=(data.get('failure_system') or 'OTRO').strip().upper(),
                horometer_at_failure=(float(data['horometer_at_failure'])
                                      if data.get('horometer_at_failure') else None),
                downtime_hours=(float(data['downtime_hours'])
                                if data.get('downtime_hours') else None),
                production_stopped=bool(data.get('production_stopped')),
                production_impact=(data.get('production_impact') or '').strip() or None,
                provider_report_code=(data.get('provider_report_code') or '').strip() or None,
                provider_responsibility=(data.get('provider_responsibility')
                                         or 'SIN_DEFINIR').strip().upper(),
                our_assessment=(data.get('our_assessment') or 'SIN_DEFINIR').strip().upper(),
                our_assessment_notes=(data.get('our_assessment_notes') or '').strip() or None,
                status=(data.get('status') or 'REPORTADA').strip().upper(),
                created_by=getattr(current_user, 'username', None),
            )
            try:
                db.session.add(failure)
                # Estado del equipo segun el ciclo de la falla.
                if failure.status in ('REPORTADA', 'ATENDIDA') and eq.status == 'OPERATIVO':
                    eq.status = 'EN_FALLA'
                db.session.commit()
                return jsonify(failure.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        qry = RentalFailure.query
        rental_id = request.args.get('rental_id', type=int)
        if rental_id:
            qry = qry.filter_by(rental_id=rental_id)
        rows = qry.order_by(RentalFailure.reported_date.desc(),
                            RentalFailure.id.desc()).limit(500).all()
        return jsonify([_failure_with_repeat_flag(f) for f in rows])

    @app.route('/api/rental/failures/<int:f_id>', methods=['PUT', 'DELETE'])
    @login_required
    def rental_failure_detail(f_id):
        failure = RentalFailure.query.get_or_404(f_id)
        if request.method == 'DELETE':
            try:
                db.session.delete(failure)
                db.session.commit()
                return jsonify({"ok": True})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        data = request.get_json() or {}
        editable = ('reported_date', 'attended_date', 'resolved_date', 'description',
                    'failure_system', 'horometer_at_failure', 'downtime_hours',
                    'production_stopped', 'production_impact', 'provider_report_code',
                    'provider_responsibility', 'our_assessment',
                    'our_assessment_notes', 'status')
        try:
            for key in editable:
                if key in data:
                    val = data[key]
                    if isinstance(val, str):
                        val = val.strip() or None
                    setattr(failure, key, val)
            # Si se resolvio la falla y el equipo no tiene otras abiertas, vuelve operativo.
            eq = failure.equipment
            if failure.status == 'RESUELTA' and eq and eq.status in ('EN_FALLA', 'EN_REPARACION'):
                open_failures = RentalFailure.query.filter(
                    RentalFailure.rental_id == eq.id,
                    RentalFailure.id != failure.id,
                    RentalFailure.status != 'RESUELTA',
                ).count()
                if open_failures == 0:
                    eq.status = 'OPERATIVO'
            db.session.commit()
            return jsonify(failure.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    def _failure_with_repeat_flag(failure):
        """Marca la falla como repetida si el mismo equipo tuvo otra falla del
        mismo sistema dentro de la ventana REPEAT_WINDOW_DAYS anterior."""
        d = failure.to_dict()
        ref = _parse_date(failure.reported_date)
        d['is_repeat'] = False
        if ref:
            since = (ref - timedelta(days=REPEAT_WINDOW_DAYS)).strftime('%Y-%m-%d')
            prior = RentalFailure.query.filter(
                RentalFailure.rental_id == failure.rental_id,
                RentalFailure.failure_system == failure.failure_system,
                RentalFailure.id != failure.id,
                RentalFailure.reported_date >= since,
                RentalFailure.reported_date <= failure.reported_date,
            ).count()
            d['is_repeat'] = prior > 0
        return d

    # ── Dashboard / analitica ──────────────────────────────────────────────

    @app.route('/api/rental/dashboard', methods=['GET'])
    @login_required
    def rental_dashboard():
        today = datetime.now().date()
        d30 = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        d90 = (today - timedelta(days=90)).strftime('%Y-%m-%d')

        equipments = (RentalEquipment.query.filter_by(is_active=True)
                      .order_by(RentalEquipment.code).all())
        all_failures = RentalFailure.query.order_by(RentalFailure.reported_date).all()
        by_eq = {}
        for f in all_failures:
            by_eq.setdefault(f.rental_id, []).append(f)

        items, alerts = [], []
        for eq in equipments:
            fails = by_eq.get(eq.id, [])
            f30 = [f for f in fails if (f.reported_date or '') >= d30]
            f90 = [f for f in fails if (f.reported_date or '') >= d90]

            # Fallas repetidas: mismo sistema dentro de la ventana de 30 dias.
            repeats = []
            by_system = {}
            for f in fails:
                by_system.setdefault(f.failure_system, []).append(f)
            for system, group in by_system.items():
                group.sort(key=lambda x: x.reported_date or '')
                for prev, cur in zip(group, group[1:]):
                    dp, dc = _parse_date(prev.reported_date), _parse_date(cur.reported_date)
                    if dp and dc and (dc - dp).days <= REPEAT_WINDOW_DAYS:
                        repeats.append({
                            'system': system,
                            'dates': [prev.reported_date, cur.reported_date],
                            'gap_days': (dc - dp).days,
                        })

            # MTBF en horas de horometro: horas trabajadas / nro de fallas.
            hours_worked = max((eq.current_horometer or 0) - (eq.initial_horometer or 0), 0)
            mtbf_hours = round(hours_worked / len(fails), 1) if fails else None
            downtime = sum(f.downtime_hours or 0 for f in fails)
            downtime_90 = sum(f.downtime_hours or 0 for f in f90)
            stopped_production = sum(1 for f in fails if f.production_stopped)

            # Responsabilidad: version proveedor vs. nuestra evaluacion.
            resp_provider = {r: 0 for r in RESPONSIBILITIES}
            resp_ours = {r: 0 for r in RESPONSIBILITIES}
            for f in fails:
                resp_provider[f.provider_responsibility or 'SIN_DEFINIR'] = \
                    resp_provider.get(f.provider_responsibility or 'SIN_DEFINIR', 0) + 1
                resp_ours[f.our_assessment or 'SIN_DEFINIR'] = \
                    resp_ours.get(f.our_assessment or 'SIN_DEFINIR', 0) + 1
            disputed = sum(
                1 for f in fails
                if f.provider_responsibility == 'NUESTRA'
                and f.our_assessment in ('PROVEEDOR', 'COMPARTIDA')
            )

            life_pct = (round(100 * (eq.current_horometer or 0) / eq.replacement_hours, 1)
                        if eq.replacement_hours else None)
            hours_to_replacement = (round(eq.replacement_hours - (eq.current_horometer or 0), 0)
                                    if eq.replacement_hours else None)

            item = eq.to_dict()
            item.update({
                'hours_worked_here': round(hours_worked, 1),
                'failures_total': len(fails),
                'failures_30d': len(f30),
                'failures_90d': len(f90),
                'repeated_failures': repeats,
                'repeated_count': len(repeats),
                'mtbf_hours': mtbf_hours,
                'downtime_hours_total': round(downtime, 1),
                'downtime_hours_90d': round(downtime_90, 1),
                'production_stops': stopped_production,
                'responsibility_provider_says': resp_provider,
                'responsibility_we_say': resp_ours,
                'disputed_count': disputed,
                'life_pct': life_pct,
                'hours_to_replacement': hours_to_replacement,
            })
            items.append(item)

            # ── Alertas accionables ────────────────────────────────────────
            if life_pct is not None and life_pct >= 100:
                alerts.append({
                    'level': 'ROJO', 'rental_code': eq.code,
                    'message': (f"{eq.code} {eq.name}: horometro "
                                f"{eq.current_horometer:.0f} h — SUPERO las "
                                f"{eq.replacement_hours:.0f} h. Exigir cambio de unidad."),
                })
            elif life_pct is not None and life_pct >= 90:
                alerts.append({
                    'level': 'AMARILLO', 'rental_code': eq.code,
                    'message': (f"{eq.code} {eq.name}: {life_pct:.0f}% de vida util "
                                f"({eq.current_horometer:.0f}/{eq.replacement_hours:.0f} h). "
                                f"Coordinar cambio de unidad con el proveedor."),
                })
            if repeats:
                last = repeats[-1]
                alerts.append({
                    'level': 'ROJO', 'rental_code': eq.code,
                    'message': (f"{eq.code} {eq.name}: falla REPETIDA de "
                                f"{last['system']} con solo {last['gap_days']} dias entre "
                                f"eventos ({len(repeats)} repeticiones en total). "
                                f"Reclamar mala reparacion al proveedor."),
                })
            if len(f30) >= 3:
                alerts.append({
                    'level': 'ROJO', 'rental_code': eq.code,
                    'message': (f"{eq.code} {eq.name}: {len(f30)} fallas en los ultimos "
                                f"30 dias. Equipo fuera de control — solicitar cambio."),
                })
            if disputed:
                alerts.append({
                    'level': 'AMARILLO', 'rental_code': eq.code,
                    'message': (f"{eq.code} {eq.name}: {disputed} falla(s) que el proveedor "
                                f"atribuye a nosotros pero nuestra evaluacion difiere. "
                                f"Revisar sustento antes de firmar conformidad."),
                })

        level_order = {'ROJO': 0, 'AMARILLO': 1}
        alerts.sort(key=lambda a: level_order.get(a['level'], 2))

        total_f30 = sum(i['failures_30d'] for i in items)
        kpi = {
            'total': len(items),
            'operativos': sum(1 for i in items if i['status'] == 'OPERATIVO'),
            'en_falla': sum(1 for i in items
                            if i['status'] in ('EN_FALLA', 'EN_REPARACION')),
            'failures_30d': total_f30,
            'repeated_total': sum(i['repeated_count'] for i in items),
            'replacement_due': sum(1 for i in items
                                   if i['life_pct'] is not None and i['life_pct'] >= 90),
        }
        return jsonify({'kpi': kpi, 'items': items, 'alerts': alerts,
                        'failure_systems': FAILURE_SYSTEMS,
                        'responsibilities': RESPONSIBILITIES,
                        'repeat_window_days': REPEAT_WINDOW_DAYS})

    # ── Export Excel (sustento para el proveedor) ──────────────────────────

    @app.route('/api/rental/failures/export', methods=['GET'])
    @login_required
    def rental_failures_export():
        import pandas as pd
        rental_id = request.args.get('rental_id', type=int)
        qry = RentalFailure.query
        if rental_id:
            qry = qry.filter_by(rental_id=rental_id)
        failures = qry.order_by(RentalFailure.reported_date).all()

        RESP_LABEL = {'NUESTRA': 'Cliente (nosotros)', 'PROVEEDOR': 'Proveedor',
                      'COMPARTIDA': 'Compartida', 'SIN_DEFINIR': 'Sin definir'}
        rows = []
        for f in failures:
            d = _failure_with_repeat_flag(f)
            rows.append({
                'Equipo': d['rental_code'],
                'Nombre': d['rental_name'],
                'Fecha reporte': f.reported_date,
                'Fecha atencion': f.attended_date,
                'Fecha solucion': f.resolved_date,
                'Sistema': f.failure_system,
                'Descripcion': f.description,
                'Horometro': f.horometer_at_failure,
                'Horas parada': f.downtime_hours,
                'Paralizo produccion': 'SI' if f.production_stopped else 'NO',
                'Impacto': f.production_impact,
                'Formato proveedor': f.provider_report_code,
                'Responsable (segun proveedor)': RESP_LABEL.get(f.provider_responsibility, f.provider_responsibility),
                'Responsable (nuestra evaluacion)': RESP_LABEL.get(f.our_assessment, f.our_assessment),
                'Sustento nuestro': f.our_assessment_notes,
                'Falla repetida (<=30d mismo sistema)': 'SI' if d['is_repeat'] else 'NO',
                'Estado': f.status,
            })
        df = pd.DataFrame(rows)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Fallas Equipos Alquilados')
        output.seek(0)
        return send_file(
            output,
            download_name=f"Fallas_Equipos_Alquilados_{datetime.now().strftime('%Y%m%d')}.xlsx",
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
