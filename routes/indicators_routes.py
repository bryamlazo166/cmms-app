"""Indicadores para directorio: MTBF, MTTR, Disponibilidad y Confiabilidad con drill-down."""
import datetime as dt
import math
from flask import jsonify, request

from utils.kpi_helpers import (
    EQUIPMENT_CAPACITY,
    SERIES_AREAS,
    eq_capacity as _eq_capacity,
)


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

    def _shutdown_duration(sh):
        """Horas de una parada calculadas a partir de start_time/end_time.
        Si end < start asume cruce de medianoche (+24h)."""
        if not sh:
            return 0
        try:
            t_start = dt.datetime.strptime(sh.start_time or '07:00', '%H:%M').time()
            t_end = dt.datetime.strptime(sh.end_time or '19:00', '%H:%M').time()
            base = dt.date(1970, 1, 1)
            diff = (dt.datetime.combine(base, t_end) - dt.datetime.combine(base, t_start)).total_seconds() / 3600
            if diff < 0:
                diff += 24
            return max(0.0, diff)
        except Exception:
            return 0

    def _load_shutdown_map(ots):
        """Pre-carga el dict {id: Shutdown} para las OTs que tengan shutdown_id."""
        try:
            from models import Shutdown
        except Exception:
            return {}
        sh_ids = set()
        for ot in ots:
            sid = ot.get('shutdown_id') if isinstance(ot, dict) else getattr(ot, 'shutdown_id', None)
            if sid:
                sh_ids.add(sid)
        if not sh_ids:
            return {}
        return {s.id: s for s in Shutdown.query.filter(Shutdown.id.in_(sh_ids)).all()}

    def _calc_indicators(ots, total_hours, shutdown_map=None,
                         mode='operativa', unplanned_shutdown_ids=None):
        """Calcula MTBF, MTTR, Disponibilidad, Confiabilidad para un conjunto de OTs.

        CONSOLIDACIÓN POR PARADA: cuando varias OTs comparten shutdown_id sobre el
        mismo equipo (trabajos paralelos durante una parada programada), su downtime
        NO se suma — se cuenta UNA sola vez usando la duración de la parada.
        Esto evita inflar artificialmente el MTTR/Indisponibilidad cuando se
        aprovecha una parada para hacer múltiples mejorías.

        mode: 'operativa' (default) cuenta TODO downtime (planificado + averias).
              'inherente' cuenta solo correctivos y paradas NO planificadas
              (averias puras) — KPI de salud del activo según ISO 14224.
        """
        shutdown_map = shutdown_map or {}
        unplanned_shutdown_ids = unplanned_shutdown_ids or set()
        is_inherent = (str(mode).lower() == 'inherente')

        def _qualifies_inherent(ot):
            """OT cuenta como falla inherente si es correctiva Y
            (no esta vinculada a parada O esta vinculada a parada NO planificada)."""
            mt = (ot.get('maintenance_type') or '').strip().lower()
            if mt not in ('correctivo', 'correctiva', 'corrective'):
                return False
            sid = ot.get('shutdown_id')
            if not sid:
                return True
            return sid in unplanned_shutdown_ids

        # Paso 1: extraer todas las OTs con downtime > 0 (lista cruda para detalle)
        failures_raw = []
        for ot in ots:
            dh = 0
            if ot.get('caused_downtime') and ot.get('downtime_hours'):
                dh = float(ot['downtime_hours'])
            elif ot.get('real_duration') and ot.get('caused_downtime'):
                dh = float(ot['real_duration'])
            if dh <= 0:
                continue
            # Filtro de modo inherente: solo correctivos en averias.
            if is_inherent and not _qualifies_inherent(ot):
                continue
            failures_raw.append({
                'id': ot.get('id'),
                'code': ot.get('code'),
                'description': ot.get('description'),
                'downtime_hours': dh,
                'maintenance_type': ot.get('maintenance_type'),
                'status': ot.get('status'),
                'scheduled_date': ot.get('scheduled_date'),
                'equipment_name': ot.get('equipment_name', ''),
                'equipment_tag': ot.get('equipment_tag', ''),
                'shutdown_id': ot.get('shutdown_id'),
                'equipment_id': ot.get('equipment_id'),
            })

        # Paso 2: consolidar OTs que pertenecen a la misma parada (mismo equipo).
        # standalone = OTs sin shutdown_id (correctivos espontáneos) → se cuentan 1 a 1
        # in_shutdown = OTs con shutdown_id → se agrupan por (shutdown_id, equipment_id)
        standalone = [f for f in failures_raw if not f.get('shutdown_id')]
        in_shutdown = [f for f in failures_raw if f.get('shutdown_id')]

        groups = {}
        for f in in_shutdown:
            # Si la OT no tiene equipment_id, agrupar por shutdown únicamente
            key = (f['shutdown_id'], f.get('equipment_id') or 0)
            groups.setdefault(key, []).append(f)

        consolidated = list(standalone)
        for (sh_id, eq_id), group in groups.items():
            sh = shutdown_map.get(sh_id)
            sh_dur = _shutdown_duration(sh)
            # Preferir duración real de la parada; si no se conoce, usar el MAX
            # del downtime registrado en las OTs (NO la suma, asumimos paralelismo)
            dh = sh_dur if sh_dur > 0 else max(f['downtime_hours'] for f in group)
            consolidated.append({
                'id': group[0]['id'],
                'code': (sh.code if sh and sh.code else f'PP-{sh_id}'),
                'description': (sh.name if sh else f'Parada {sh_id}') + f' — {len(group)} OT(s) consolidada(s)',
                'downtime_hours': round(dh, 2),
                'maintenance_type': 'Parada Programada',
                'status': 'Cerrada',
                'scheduled_date': group[0].get('scheduled_date'),
                'equipment_name': group[0].get('equipment_name', ''),
                'equipment_tag': group[0].get('equipment_tag', ''),
                'shutdown_id': sh_id,
                'equipment_id': eq_id,
                'consolidated_count': len(group),
                'consolidated_ot_ids': [f['id'] for f in group],
                'consolidated_raw_total': round(sum(f['downtime_hours'] for f in group), 2),
            })

        n_failures = len(consolidated)
        total_downtime = sum(f['downtime_hours'] for f in consolidated)
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
            'failures': sorted(consolidated, key=lambda f: f['downtime_hours'], reverse=True),
            'failures_detail': sorted(failures_raw, key=lambda f: f['downtime_hours'], reverse=True),
            'consolidated_groups': len(groups),
        }

    def _load_unplanned_shutdown_ids():
        """Set de IDs de paradas marcadas como NO planificadas (averias).
        Usado para filtrar disponibilidad inherente."""
        try:
            from models import Shutdown
            rows = Shutdown.query.filter_by(is_planned=False).with_entities(Shutdown.id).all()
            return {r[0] for r in rows}
        except Exception as e:
            logger.warning(f"Shutdown.is_planned no disponible: {e}")
            return set()

    def _read_mode():
        m = (request.args.get('mode') or 'operativa').strip().lower()
        return m if m in ('operativa', 'inherente') else 'operativa'

    @app.route('/api/indicators/areas', methods=['GET'])
    def indicators_by_area():
        """Nivel 1: Indicadores por área con disponibilidad ponderada o en serie.
        Query: ?mode=operativa|inherente (default operativa)."""
        try:
            start = _parse_date(request.args.get('start_date')) or (dt.date.today().replace(day=1))
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24
            mode = _read_mode()
            unplanned_ids = _load_unplanned_shutdown_ids() if mode == 'inherente' else set()

            # Solo areas/equipos marcados como include_in_kpi=True. Esto excluye
            # cosas como "BAJA / FUERA DE SERVICIO", "UTILITIES", "RMP" o
            # equipos auxiliares (ej: hidrolavadora 4 de Coccion).
            areas = Area.query.filter_by(include_in_kpi=True).all()
            lines = Line.query.all()
            equips = Equipment.query.filter_by(include_in_kpi=True).all()
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
            ots_window = []
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
                ots_window.append(od)

            # Pre-cargar paradas referenciadas para consolidación de downtime
            shutdown_map = _load_shutdown_map(ots_window)

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
                            ind = _calc_indicators(eq_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                            equip_avails.append(ind['availability'] / 100)
                        series_avail = 1.0
                        for a in equip_avails:
                            series_avail *= a
                        area_indicators = _calc_indicators(area_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                        area_indicators['availability'] = round(series_avail * 100, 2)
                        area_indicators['calc_method'] = 'serie'
                    else:
                        area_indicators = _calc_indicators(area_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                        area_indicators['calc_method'] = 'simple'
                else:
                    # Ponderado por capacidad
                    area_equips = [e for e in equips if e.line_id and line_map.get(e.line_id) and line_map[e.line_id].area_id == area.id]
                    has_capacity = any(_eq_capacity(e) > 0 for e in area_equips)

                    if has_capacity and area_equips:
                        weighted_sum = 0
                        total_cap = 0
                        for eq in area_equips:
                            cap = _eq_capacity(eq)
                            if cap == 0:
                                continue
                            eq_ots = [o for o in area_ots if o.get('equipment_id') == eq.id]
                            ind = _calc_indicators(eq_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                            weighted_sum += ind['availability'] * cap
                            total_cap += cap
                        area_indicators = _calc_indicators(area_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                        if total_cap > 0:
                            area_indicators['availability'] = round(weighted_sum / total_cap, 2)
                        area_indicators['calc_method'] = 'ponderado'
                        area_indicators['total_capacity'] = total_cap
                    else:
                        area_indicators = _calc_indicators(area_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                        area_indicators['calc_method'] = 'simple'

                area_indicators['area_id'] = area.id
                area_indicators['area_name'] = area.name
                result.append(area_indicators)

            result.sort(key=lambda x: x['area_name'])
            return jsonify({
                'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days': window_days, 'hours': total_hours},
                'mode': mode,
                'areas': result,
            })
        except Exception as e:
            logger.error(f"indicators_by_area error: {e}")
            import traceback; traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/indicators/area/<int:area_id>/equipments', methods=['GET'])
    def indicators_by_equipment(area_id):
        """Nivel 2: Indicadores por equipo dentro de un área.
        Query: ?mode=operativa|inherente (default operativa)."""
        try:
            start = _parse_date(request.args.get('start_date')) or (dt.date.today().replace(day=1))
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24
            mode = _read_mode()
            unplanned_ids = _load_unplanned_shutdown_ids() if mode == 'inherente' else set()

            area = Area.query.get_or_404(area_id)
            lines = Line.query.filter_by(area_id=area_id).all()
            line_ids = [l.id for l in lines]
            # Solo equipos include_in_kpi=True (excluye p.ej. hidrolavadoras
            # auxiliares que no entran en los calculos de produccion).
            equips = (Equipment.query.filter(
                Equipment.line_id.in_(line_ids),
                Equipment.include_in_kpi == True  # noqa: E712
            ).all()) if line_ids else []
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

            # Pre-cargar paradas para consolidación de downtime
            relevant_ots = [ot for ot in all_ots if ot.equipment_id in {e.id for e in equips} and ot_in_window(ot)]
            shutdown_map = _load_shutdown_map(relevant_ots)

            result = []
            for eq in equips:
                eq_ots = [ot.to_dict() for ot in all_ots if ot.equipment_id == eq.id and ot_in_window(ot)]
                ind = _calc_indicators(eq_ots, total_hours, shutdown_map, mode=mode, unplanned_shutdown_ids=unplanned_ids)
                cap = _eq_capacity(eq)
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
                'mode': mode,
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
        """Nivel 3: Lista de fallas/OTs de un equipo en el periodo.
        Query: ?mode=operativa|inherente."""
        try:
            start = _parse_date(request.args.get('start_date')) or (dt.date.today().replace(day=1))
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24
            mode = _read_mode()
            unplanned_ids = _load_unplanned_shutdown_ids() if mode == 'inherente' else set()

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

            shutdown_map = _load_shutdown_map(ots_data)
            ind = _calc_indicators(ots_data, total_hours, shutdown_map,
                                   mode=mode, unplanned_shutdown_ids=unplanned_ids)
            ind['equipment_id'] = eq.id
            ind['equipment_name'] = eq.name
            ind['equipment_tag'] = eq.tag
            ind['capacity'] = EQUIPMENT_CAPACITY.get(eq.tag, 0)
            ind['mode'] = mode
            ind['all_ots'] = sorted(ots_data, key=lambda o: o.get('downtime_hours_calc', 0), reverse=True)

            return jsonify(ind)
        except Exception as e:
            logger.error(f"indicators_equipment_failures error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/indicators/pareto-fallas', methods=['GET'])
    def indicators_pareto_fallas():
        """Pareto de fallas (OTs correctivas) en la ventana de fechas.

        Query: start_date / end_date (default: ultimos 90 dias),
               group = mode | equipment | component (default mode),
               area_id opcional.
        Devuelve items ordenados desc por ocurrencias con % acumulado
        (analisis 80/20) y horas de parada asociadas a cada grupo.
        """
        try:
            end = _parse_date(request.args.get('end_date')) or dt.date.today()
            start = _parse_date(request.args.get('start_date')) or (end - dt.timedelta(days=89))
            group = (request.args.get('group') or 'mode').lower()
            area_id = request.args.get('area_id', type=int)

            q = WorkOrder.query.filter(WorkOrder.maintenance_type == 'Correctivo')
            if area_id:
                q = q.filter(WorkOrder.area_id == area_id)
            ots = q.all()

            def in_window(ot):
                d = ot.real_end_date or ot.real_start_date or ot.scheduled_date
                if not d:
                    return False
                try:
                    return start <= dt.date.fromisoformat(str(d)[:10]) <= end
                except Exception:
                    return False

            # Pre-cargar nombres para agrupar sin N+1
            eq_names, comp_names = {}, {}
            if group in ('equipment', 'component'):
                eq_ids = {o.equipment_id for o in ots if o.equipment_id}
                comp_ids = {o.component_id for o in ots if o.component_id}
                if eq_ids:
                    for e in Equipment.query.filter(Equipment.id.in_(eq_ids)).all():
                        eq_names[e.id] = f"[{e.tag}] {e.name}" if e.tag else e.name
                if comp_ids:
                    from models import Component
                    for c in Component.query.filter(Component.id.in_(comp_ids)).all():
                        comp_names[c.id] = c.name

            buckets = {}
            total = 0
            for ot in ots:
                if not in_window(ot):
                    continue
                total += 1
                if group == 'equipment':
                    key = eq_names.get(ot.equipment_id, 'SIN EQUIPO')
                elif group == 'component':
                    key = comp_names.get(ot.component_id, 'SIN COMPONENTE')
                else:
                    key = (ot.failure_mode or 'SIN MODO DE FALLA').strip().upper()
                b = buckets.setdefault(key, {'label': key, 'count': 0, 'downtime_hours': 0.0})
                b['count'] += 1
                dh = 0.0
                if getattr(ot, 'caused_downtime', None) and ot.downtime_hours:
                    dh = float(ot.downtime_hours)
                elif getattr(ot, 'caused_downtime', None) and ot.real_duration:
                    dh = float(ot.real_duration)
                b['downtime_hours'] += dh

            items = sorted(buckets.values(), key=lambda x: (-x['count'], -x['downtime_hours']))
            cum = 0
            for it in items:
                cum += it['count']
                it['downtime_hours'] = round(it['downtime_hours'], 1)
                it['pct'] = round(it['count'] / total * 100, 1) if total else 0
                it['cum_pct'] = round(cum / total * 100, 1) if total else 0

            return jsonify({
                'start_date': start.isoformat(),
                'end_date': end.isoformat(),
                'group': group,
                'total': total,
                'items': items,
            })
        except Exception as e:
            logger.error(f"indicators_pareto_fallas error: {e}")
            return jsonify({"error": str(e)}), 500
