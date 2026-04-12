"""Indicadores para directorio: MTBF, MTTR, Disponibilidad y Confiabilidad con drill-down."""
import datetime as dt
import math
from flask import jsonify, request


# Capacidades por equipo tag (TM)
EQUIPMENT_CAPACITY = {
    'D1': 8000, 'D2': 8000, 'D3': 8000, 'D4': 6000, 'D5': 7000,
    'D6': 12000, 'D7': 12000, 'D8': 12000, 'D9': 12000,
}

# Áreas con cálculo en serie (no ponderado)
SERIES_AREAS = {'MOLINO'}


def register_indicators_routes(app, db, logger, WorkOrder, Area, Line, Equipment):

    def _parse_date(raw):
        if not raw:
            return None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return dt.datetime.strptime(str(raw), fmt).date()
            except Exception:
                pass
        return None

    def _calc_indicators(ots, total_hours):
        """Calcula MTBF, MTTR, Disponibilidad, Confiabilidad para un conjunto de OTs."""
        failures = []
        for ot in ots:
            dh = 0
            if ot.get('caused_downtime') and ot.get('downtime_hours'):
                dh = float(ot['downtime_hours'])
            elif ot.get('real_duration') and ot.get('caused_downtime'):
                dh = float(ot['real_duration'])
            if dh > 0:
                failures.append({
                    'id': ot.get('id'),
                    'code': ot.get('code'),
                    'description': ot.get('description'),
                    'downtime_hours': dh,
                    'maintenance_type': ot.get('maintenance_type'),
                    'status': ot.get('status'),
                    'scheduled_date': ot.get('scheduled_date'),
                    'equipment_name': ot.get('equipment_name', ''),
                    'equipment_tag': ot.get('equipment_tag', ''),
                })

        n_failures = len(failures)
        total_downtime = sum(f['downtime_hours'] for f in failures)
        uptime = max(0, total_hours - total_downtime)

        mtbf = round(uptime / n_failures, 2) if n_failures > 0 else round(total_hours, 2)
        mttr = round(total_downtime / n_failures, 2) if n_failures > 0 else 0
        availability = round((uptime / total_hours) * 100, 2) if total_hours > 0 else 100
        # Confiabilidad R(t) = e^(-t/MTBF) para t = periodo analizado
        if mtbf > 0 and total_hours > 0:
            reliability = round(math.exp(-total_hours / mtbf) * 100, 2)
        else:
            reliability = round(math.exp(0) * 100, 2) if n_failures == 0 else 0

        return {
            'mtbf': mtbf,
            'mttr': mttr,
            'availability': availability,
            'reliability': reliability,
            'total_hours': total_hours,
            'downtime_hours': round(total_downtime, 2),
            'failure_count': n_failures,
            'total_ots': len(ots),
            'failures': sorted(failures, key=lambda f: f['downtime_hours'], reverse=True),
        }

    @app.route('/api/indicators/areas', methods=['GET'])
    def indicators_by_area():
        """Nivel 1: Indicadores por área con disponibilidad ponderada o en serie."""
        try:
            start = _parse_date(request.args.get('start_date')) or (dt.date.today().replace(day=1))
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24

            areas = Area.query.all()
            lines = Line.query.all()
            equips = Equipment.query.all()
            line_map = {l.id: l for l in lines}
            equip_map = {e.id: e for e in equips}
            area_map = {a.id: a for a in areas}

            # Cargar OTs cerradas en el periodo
            all_ots = WorkOrder.query.filter(
                WorkOrder.status == 'Cerrada'
            ).all()

            def ot_in_window(ot):
                d = ot.scheduled_date or ot.real_end_date or ot.real_start_date
                if not d:
                    return False
                try:
                    od = dt.date.fromisoformat(d[:10])
                    return start <= od <= end
                except Exception:
                    return False

            # Resolver area para cada OT
            def resolve_area_id(ot):
                if ot.area_id:
                    return ot.area_id
                if ot.line_id and ot.line_id in line_map:
                    return line_map[ot.line_id].area_id
                if ot.equipment_id and ot.equipment_id in equip_map:
                    eq = equip_map[ot.equipment_id]
                    if eq.line_id and eq.line_id in line_map:
                        return line_map[eq.line_id].area_id
                return None

            # Agrupar OTs por area
            ots_by_area = {}
            for ot in all_ots:
                if not ot_in_window(ot):
                    continue
                aid = resolve_area_id(ot)
                if aid not in ots_by_area:
                    ots_by_area[aid] = []
                od = ot.to_dict()
                eq = equip_map.get(ot.equipment_id)
                od['equipment_name'] = eq.name if eq else '-'
                od['equipment_tag'] = eq.tag if eq else '-'
                ots_by_area[aid].append(od)

            # Calcular por área
            result = []
            for area in areas:
                area_ots = ots_by_area.get(area.id, [])
                area_name = area.name.upper()
                is_series = area_name in SERIES_AREAS

                if is_series:
                    # Serie: calcular por equipo individual y multiplicar disponibilidades
                    area_equips = [e for e in equips if e.line_id and line_map.get(e.line_id) and line_map[e.line_id].area_id == area.id]
                    if area_equips:
                        equip_avails = []
                        for eq in area_equips:
                            eq_ots = [o for o in area_ots if o.get('equipment_id') == eq.id]
                            ind = _calc_indicators(eq_ots, total_hours)
                            equip_avails.append(ind['availability'] / 100)
                        series_avail = 1.0
                        for a in equip_avails:
                            series_avail *= a
                        area_indicators = _calc_indicators(area_ots, total_hours)
                        area_indicators['availability'] = round(series_avail * 100, 2)
                        area_indicators['calc_method'] = 'serie'
                    else:
                        area_indicators = _calc_indicators(area_ots, total_hours)
                        area_indicators['calc_method'] = 'simple'
                else:
                    # Ponderado por capacidad
                    area_equips = [e for e in equips if e.line_id and line_map.get(e.line_id) and line_map[e.line_id].area_id == area.id]
                    has_capacity = any(EQUIPMENT_CAPACITY.get(e.tag, 0) > 0 for e in area_equips)

                    if has_capacity and area_equips:
                        weighted_sum = 0
                        total_cap = 0
                        for eq in area_equips:
                            cap = EQUIPMENT_CAPACITY.get(eq.tag, 0)
                            if cap == 0:
                                continue
                            eq_ots = [o for o in area_ots if o.get('equipment_id') == eq.id]
                            ind = _calc_indicators(eq_ots, total_hours)
                            weighted_sum += ind['availability'] * cap
                            total_cap += cap
                        area_indicators = _calc_indicators(area_ots, total_hours)
                        if total_cap > 0:
                            area_indicators['availability'] = round(weighted_sum / total_cap, 2)
                        area_indicators['calc_method'] = 'ponderado'
                        area_indicators['total_capacity'] = total_cap
                    else:
                        area_indicators = _calc_indicators(area_ots, total_hours)
                        area_indicators['calc_method'] = 'simple'

                area_indicators['area_id'] = area.id
                area_indicators['area_name'] = area.name
                result.append(area_indicators)

            result.sort(key=lambda x: x['area_name'])
            return jsonify({
                'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days': window_days, 'hours': total_hours},
                'areas': result,
            })
        except Exception as e:
            logger.error(f"indicators_by_area error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/indicators/area/<int:area_id>/equipments', methods=['GET'])
    def indicators_by_equipment(area_id):
        """Nivel 2: Indicadores por equipo dentro de un área."""
        try:
            start = _parse_date(request.args.get('start_date')) or (dt.date.today().replace(day=1))
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24

            area = Area.query.get_or_404(area_id)
            lines = Line.query.filter_by(area_id=area_id).all()
            line_ids = [l.id for l in lines]
            equips = Equipment.query.filter(Equipment.line_id.in_(line_ids)).all() if line_ids else []
            line_map = {l.id: l for l in lines}

            all_ots = WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all()

            def ot_in_window(ot):
                d = ot.scheduled_date or ot.real_end_date or ot.real_start_date
                if not d:
                    return False
                try:
                    return start <= dt.date.fromisoformat(d[:10]) <= end
                except Exception:
                    return False

            result = []
            for eq in equips:
                eq_ots = [ot.to_dict() for ot in all_ots if ot.equipment_id == eq.id and ot_in_window(ot)]
                ind = _calc_indicators(eq_ots, total_hours)
                cap = EQUIPMENT_CAPACITY.get(eq.tag, 0)
                ln = line_map.get(eq.line_id)
                ind['equipment_id'] = eq.id
                ind['equipment_name'] = eq.name
                ind['equipment_tag'] = eq.tag
                ind['line_name'] = ln.name if ln else '-'
                ind['capacity'] = cap
                result.append(ind)

            result.sort(key=lambda x: (x['equipment_tag'] or ''), )
            return jsonify({
                'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days': window_days, 'hours': total_hours},
                'area_id': area_id,
                'area_name': area.name,
                'is_series': area.name.upper() in SERIES_AREAS,
                'equipments': result,
            })
        except Exception as e:
            logger.error(f"indicators_by_equipment error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/indicators/equipment/<int:equipment_id>/failures', methods=['GET'])
    def indicators_equipment_failures(equipment_id):
        """Nivel 3: Lista de fallas/OTs de un equipo en el periodo."""
        try:
            start = _parse_date(request.args.get('start_date')) or (dt.date.today().replace(day=1))
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24

            eq = Equipment.query.get_or_404(equipment_id)
            all_ots = WorkOrder.query.filter(
                WorkOrder.equipment_id == equipment_id,
                WorkOrder.status == 'Cerrada'
            ).all()

            def ot_in_window(ot):
                d = ot.scheduled_date or ot.real_end_date or ot.real_start_date
                if not d:
                    return False
                try:
                    return start <= dt.date.fromisoformat(d[:10]) <= end
                except Exception:
                    return False

            ots_data = []
            for ot in all_ots:
                if not ot_in_window(ot):
                    continue
                od = ot.to_dict()
                dh = 0
                if ot.caused_downtime and ot.downtime_hours:
                    dh = float(ot.downtime_hours)
                elif ot.real_duration and ot.caused_downtime:
                    dh = float(ot.real_duration)
                od['downtime_hours_calc'] = round(dh, 2)
                ots_data.append(od)

            ind = _calc_indicators(ots_data, total_hours)
            ind['equipment_id'] = eq.id
            ind['equipment_name'] = eq.name
            ind['equipment_tag'] = eq.tag
            ind['capacity'] = EQUIPMENT_CAPACITY.get(eq.tag, 0)
            ind['all_ots'] = sorted(ots_data, key=lambda o: o.get('downtime_hours_calc', 0), reverse=True)

            return jsonify(ind)
        except Exception as e:
            logger.error(f"indicators_equipment_failures error: {e}")
            return jsonify({"error": str(e)}), 500
