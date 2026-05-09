"""Plant Flow / Diagrama de Flujo de Planta.

Devuelve el flujo de proceso de la planta (equipos conectados aguas arriba/abajo)
con KPI de disponibilidad por equipo en un periodo dado. Por defecto: desde el
primer dia del mes anterior hasta hoy.

Tambien expone Sankey de perdidas de produccion (Sprint 2): horas perdidas por
equipo y modo de falla en el periodo.

DISPONIBILIDAD:
- Operativa  (Ao): incluye TODO paro (preventivo + correctivo + parada planificada).
                   Refleja "% del tiempo que el equipo realmente produjo".
- Inherente  (Ai): solo correctivos no programados (sin shutdown_id).
                   Refleja "que tan confiable es el equipo per se" (ISO 14224).

Ambas se calculan FUSIONANDO intervalos solapados — dos OTs paralelas en el
mismo periodo cuentan UNA sola vez (su union, no su suma). Las horas teoricas
respetan shift_hours_per_day y work_days_per_week del equipo.
"""
import datetime as dt
import math

from flask import jsonify, render_template, request

from utils.kpi_helpers import (
    calendar_hours_for_equipment,
    eq_capacity,
)


def register_plant_flow_routes(app, db, logger, Equipment, Area, Line, WorkOrder, EquipmentFlowEdge, Shutdown=None):

    def _default_period():
        """Desde el primer dia del mes anterior hasta hoy."""
        today = dt.date.today()
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - dt.timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        return first_of_prev_month, today

    def _parse_date(raw, default):
        if not raw:
            return default
        try:
            return dt.date.fromisoformat(raw[:10])
        except Exception:
            return default

    def _parse_ts(raw):
        """Convierte un string 'YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM[:SS]' a datetime.
        Devuelve None si no se puede interpretar."""
        if not raw:
            return None
        try:
            s = str(raw)[:19]
            if 'T' in s:
                # ISO con tiempo: '2026-04-08T16:40' o '2026-04-08T16:40:00'
                if len(s) == 16:
                    s += ':00'
                return dt.datetime.fromisoformat(s)
            # Solo fecha
            return dt.datetime.fromisoformat(s + 'T00:00:00')
        except Exception:
            return None

    def _ot_interval(ot):
        """Extrae (inicio, fin) de paro de una OT con varias estrategias:
          1. real_start_date + real_end_date (preferido)
          2. real_start_date + downtime_hours
          3. real_end_date - downtime_hours
        Devuelve (None, None) si no hay datos suficientes.
        """
        ini = _parse_ts(ot.real_start_date)
        fin = _parse_ts(ot.real_end_date)
        dh = float(ot.downtime_hours or 0)

        if ini and fin and fin > ini:
            return ini, fin
        if ini and dh > 0:
            return ini, ini + dt.timedelta(hours=dh)
        if fin and dh > 0:
            return fin - dt.timedelta(hours=dh), fin
        return None, None

    def _merge_and_total_hours(intervals, period_start_dt, period_end_dt):
        """Acota cada intervalo al periodo, ordena, fusiona los solapados
        y devuelve el total de horas resultante.

        Ej: dos OTs paralelas de 8h en el mismo dia se fusionan en una
        sola ventana de 8h (no 16h). Esto evita el sobrecont eo cuando
        varios equipos de mantenimiento trabajan en paralelo en una parada.
        """
        clipped = []
        for ini, fin in intervals:
            if not (ini and fin):
                continue
            a = max(ini, period_start_dt)
            b = min(fin, period_end_dt)
            if b > a:
                clipped.append((a, b))

        if not clipped:
            return 0.0

        clipped.sort(key=lambda x: x[0])
        merged = [clipped[0]]
        for a, b in clipped[1:]:
            last_a, last_b = merged[-1]
            if a <= last_b:
                merged[-1] = (last_a, max(last_b, b))
            else:
                merged.append((a, b))

        return sum((b - a).total_seconds() / 3600.0 for a, b in merged)

    def _calc_equipment_availability(eq, ots_in_period, period_start, period_end,
                                     unplanned_shutdown_ids=None):
        """Disponibilidad operativa e inherente con fusion de intervalos.

        - theoretical: horas en que el equipo DEBIA producir, respetando
          shift_hours_per_day y work_days_per_week (no asume 24/7).
        - downtime_op: paro total (cualquier OT con caused_downtime).
        - downtime_inh: confiabilidad pura — cuenta correctivos que NO esten
          en parada PLANIFICADA. Una OT correctiva vinculada a una parada
          marcada como "no planificada" (shutdown.is_planned=False) SI cuenta
          en inherente, porque la parada misma fue causada por una averia.
        - Aplica cap defensivo: downtime nunca supera theoretical.

        Devuelve dict con ambos KPIs.
        """
        theoretical = calendar_hours_for_equipment(eq, period_start, period_end)
        if theoretical <= 0:
            return {
                'availability_op': 100.0, 'availability_inh': 100.0,
                'downtime_op_hours': 0.0, 'downtime_inh_hours': 0.0,
                'n_failures': 0, 'theoretical_hours': 0.0,
            }

        p_start_dt = dt.datetime.combine(period_start, dt.time(0, 0))
        p_end_dt = dt.datetime.combine(period_end, dt.time(23, 59, 59))

        unplanned_shutdown_ids = unplanned_shutdown_ids or set()

        intervals_all = []
        intervals_inh = []
        n_failures = 0

        for ot in ots_in_period:
            if ot.equipment_id != eq.id:
                continue
            if not (ot.caused_downtime and ot.downtime_hours):
                continue
            ini, fin = _ot_interval(ot)
            if not (ini and fin):
                continue
            intervals_all.append((ini, fin))
            n_failures += 1

            mt = (ot.maintenance_type or '').strip().lower()
            is_corrective = mt in ('correctivo', 'correctiva', 'corrective')
            # Inherente: la OT correctiva cuenta si:
            #   - no esta vinculada a parada (averia espontanea), O
            #   - esta vinculada a una parada NO PLANIFICADA (averia que
            #     obligo a parar, aunque despues se haya creado un Shutdown
            #     para gestionar las OTs adicionales).
            if is_corrective:
                no_shutdown = not ot.shutdown_id
                shutdown_unplanned = ot.shutdown_id in unplanned_shutdown_ids
                if no_shutdown or shutdown_unplanned:
                    intervals_inh.append((ini, fin))

        downtime_op = _merge_and_total_hours(intervals_all, p_start_dt, p_end_dt)
        downtime_inh = _merge_and_total_hours(intervals_inh, p_start_dt, p_end_dt)

        # Cap defensivo: si por dato sucio el paro excede las horas teoricas,
        # se acota a 100% de paro (disponibilidad 0%) en lugar de negativo.
        downtime_op = min(downtime_op, theoretical)
        downtime_inh = min(downtime_inh, theoretical)

        avail_op = max(0.0, (theoretical - downtime_op) / theoretical * 100)
        avail_inh = max(0.0, (theoretical - downtime_inh) / theoretical * 100)

        return {
            'availability_op': round(avail_op, 2),
            'availability_inh': round(avail_inh, 2),
            'downtime_op_hours': round(downtime_op, 2),
            'downtime_inh_hours': round(downtime_inh, 2),
            'n_failures': n_failures,
            'theoretical_hours': round(theoretical, 2),
        }

    @app.route('/flujo-planta', methods=['GET'])
    def plant_flow_page():
        return render_template('plant_flow.html')

    @app.route('/perdidas-produccion', methods=['GET'])
    def production_losses_page():
        return render_template('production_losses.html')

    @app.route('/api/plant-flow', methods=['GET'])
    def api_plant_flow():
        """Devuelve nodos (equipos) + aristas (feeds_into) + KPI por equipo.
        Query params: ?start=YYYY-MM-DD&end=YYYY-MM-DD (default: mes anterior a hoy)
        """
        try:
            d_start, d_end = _default_period()
            start = _parse_date(request.args.get('start'), d_start)
            end = _parse_date(request.args.get('end'), d_end)
            window_days = max(1, (end - start).days + 1)
            # total_hours_24x7 se mantiene en la respuesta para referencia,
            # pero el calculo por equipo usa calendar_hours_for_equipment().
            total_hours_24x7 = window_days * 24

            # Equipos KPI-relevantes con su jerarquia
            equipments = Equipment.query.filter_by(include_in_kpi=True).all()
            areas = {a.id: a for a in Area.query.all()}
            lines = {l.id: l for l in Line.query.all()}

            # OTs cerradas en el periodo con downtime. Se cargan TODAS las
            # OTs con caused_downtime=true y se filtran luego por ventana,
            # porque una OT puede empezar antes del periodo y terminar dentro.
            all_ots = WorkOrder.query.filter(
                WorkOrder.status == 'Cerrada',
                WorkOrder.caused_downtime == True,  # noqa: E712
            ).all()

            def overlaps_window(ot):
                """Una OT cuenta si su intervalo de paro toca el periodo."""
                ini, fin = _ot_interval(ot)
                if not (ini and fin):
                    # Fallback: si no podemos armar intervalo, usar fechas sueltas
                    d = ot.real_end_date or ot.scheduled_date or ot.real_start_date
                    if not d:
                        return False
                    try:
                        od = dt.date.fromisoformat(d[:10])
                        return start <= od <= end
                    except Exception:
                        return False
                p_start_dt = dt.datetime.combine(start, dt.time(0, 0))
                p_end_dt = dt.datetime.combine(end, dt.time(23, 59, 59))
                return ini <= p_end_dt and fin >= p_start_dt

            ots_in_period = [o for o in all_ots if overlaps_window(o)]

            # Pre-cargar IDs de paradas marcadas como NO planificadas (averias).
            # Las OTs correctivas vinculadas a estas paradas SI cuentan en
            # disponibilidad inherente (la parada misma fue causada por falla).
            unplanned_shutdown_ids = set()
            if Shutdown is not None:
                try:
                    rows = Shutdown.query.filter_by(is_planned=False).with_entities(
                        Shutdown.id).all()
                    unplanned_shutdown_ids = {r[0] for r in rows}
                except Exception as _e:
                    # Si la columna aun no existe (migracion pendiente), tratar
                    # todas las paradas como planificadas (comportamiento previo).
                    logger.warning(f"Shutdown.is_planned no disponible: {_e}")

            # Bypass: pre-cargar para flag de equipos con redundancia
            bypass_rows = EquipmentFlowEdge.query.filter_by(is_active=True).all()
            bypass_in_ids = {b.to_equipment_id for b in bypass_rows}
            bypass_out_ids = {b.from_equipment_id for b in bypass_rows}
            equipos_con_bypass = bypass_in_ids | bypass_out_ids

            # Construir nodos
            nodes = []
            for eq in equipments:
                line = lines.get(eq.line_id)
                area = areas.get(line.area_id) if line else None
                kpi = _calc_equipment_availability(eq, ots_in_period, start, end,
                                                   unplanned_shutdown_ids=unplanned_shutdown_ids)
                avail_op = kpi['availability_op']
                avail_inh = kpi['availability_inh']
                # Color semaforo basado en disponibilidad operativa (la mas conservadora)
                if avail_op >= 95:
                    color = 'green'
                elif avail_op >= 85:
                    color = 'amber'
                else:
                    color = 'red'
                nodes.append({
                    'id': eq.id,
                    'tag': eq.tag,
                    'name': eq.name,
                    'line_id': eq.line_id,
                    'line_name': line.name if line else None,
                    'area_id': area.id if area else None,
                    'area_name': area.name if area else None,
                    'process_order': eq.process_order,
                    'feeds_into_equipment_id': eq.feeds_into_equipment_id,
                    'capacity_tm': eq_capacity(eq),
                    # Doble KPI: operativa (todo) e inherente (solo correctivos)
                    'availability': avail_op,         # legacy: alias de operativa
                    'availability_op': avail_op,
                    'availability_inh': avail_inh,
                    'downtime_hours': kpi['downtime_op_hours'],
                    'downtime_op_hours': kpi['downtime_op_hours'],
                    'downtime_inh_hours': kpi['downtime_inh_hours'],
                    'theoretical_hours': kpi['theoretical_hours'],
                    'failure_count': kpi['n_failures'],
                    'has_bypass': eq.id in equipos_con_bypass,
                    'color': color,
                    'criticality': eq.criticality,
                })

            # Aristas: solo si feeds_into existe y es un equipo en la lista
            valid_ids = {n['id'] for n in nodes}
            edges = [
                {'from': n['id'], 'to': n['feeds_into_equipment_id'],
                 'from_tag': n['tag'],
                 'to_tag': next((m['tag'] for m in nodes
                                 if m['id'] == n['feeds_into_equipment_id']), None)}
                for n in nodes
                if n['feeds_into_equipment_id'] and n['feeds_into_equipment_id'] in valid_ids
            ]

            # Bypass / rutas alternativas (lineas punteadas en el diagrama)
            tag_by_id = {n['id']: n['tag'] for n in nodes}
            bypass_edges = [
                {
                    'id': b.id,
                    'from': b.from_equipment_id,
                    'to': b.to_equipment_id,
                    'from_tag': tag_by_id.get(b.from_equipment_id),
                    'to_tag': tag_by_id.get(b.to_equipment_id),
                    'edge_type': b.edge_type,
                    'note': b.note,
                }
                for b in bypass_rows
                if b.from_equipment_id in valid_ids and b.to_equipment_id in valid_ids
            ]

            # ── Disponibilidad por LINEA (modelo serie, pero suaviza bypass) ──
            # A_linea = producto de A_equipo. Equipos con bypass aportan un
            # promedio entre su A_eq y 100% (aproximacion de que la linea no
            # se detiene si el bypass esta operativo).
            line_kpi = {}
            for line_id, line in lines.items():
                line_eqs = [n for n in nodes if n['line_id'] == line_id]
                if not line_eqs:
                    continue
                prod_op = 1.0
                prod_inh = 1.0
                for n in line_eqs:
                    contrib_op = n['availability_op']
                    contrib_inh = n['availability_inh']
                    if n['has_bypass']:
                        # Aproximacion: equipo con bypass no penaliza la linea al 100%.
                        # Su contribucion efectiva es el promedio con disponibilidad
                        # plena del bypass. Para un calculo exacto habria que
                        # modelar disponibilidad del bypass (info que aun no tenemos).
                        contrib_op = (contrib_op + 100.0) / 2.0
                        contrib_inh = (contrib_inh + 100.0) / 2.0
                    prod_op *= (contrib_op / 100.0)
                    prod_inh *= (contrib_inh / 100.0)

                line_kpi[line_id] = {
                    'line_id': line_id,
                    'line_name': line.name,
                    'area_id': line.area_id,
                    'area_name': areas[line.area_id].name if areas.get(line.area_id) else None,
                    'equipment_count': len(line_eqs),
                    'availability': round(prod_op * 100, 2),         # legacy alias
                    'availability_op': round(prod_op * 100, 2),
                    'availability_inh': round(prod_inh * 100, 2),
                    'total_downtime': round(sum(n['downtime_hours'] for n in line_eqs), 2),
                    'total_failures': sum(n['failure_count'] for n in line_eqs),
                    # Suma de capacidades de los equipos de la linea (para
                    # ponderar el area por capacidad de produccion).
                    'capacity_tm': sum(n.get('capacity_tm') or 0 for n in line_eqs),
                    'has_bypass': any(n['has_bypass'] for n in line_eqs),
                }

            # ── Disponibilidad por AREA (promedio ponderado por capacity_tm) ──
            # Una linea grande (digestores 12000 TM/mes) pesa mas que una
            # pequena (auxiliar 500 TM/mes). Si todas las lineas tienen 0 de
            # capacidad, fallback a promedio aritmetico.
            area_kpi = {}
            for area_id, area in areas.items():
                area_lines = [lk for lk in line_kpi.values() if lk['area_id'] == area_id]
                if not area_lines:
                    continue
                total_cap = sum(lk['capacity_tm'] for lk in area_lines)
                if total_cap > 0:
                    weighted_op = sum(
                        lk['availability_op'] * lk['capacity_tm'] for lk in area_lines
                    ) / total_cap
                    weighted_inh = sum(
                        lk['availability_inh'] * lk['capacity_tm'] for lk in area_lines
                    ) / total_cap
                    weighting = 'capacity_tm'
                else:
                    n_lines = len(area_lines)
                    weighted_op = sum(lk['availability_op'] for lk in area_lines) / n_lines
                    weighted_inh = sum(lk['availability_inh'] for lk in area_lines) / n_lines
                    weighting = 'simple_mean'

                area_kpi[area_id] = {
                    'area_id': area_id,
                    'area_name': area.name,
                    'line_count': len(area_lines),
                    'availability': round(weighted_op, 2),         # legacy alias
                    'availability_op': round(weighted_op, 2),
                    'availability_inh': round(weighted_inh, 2),
                    'total_downtime': round(sum(lk['total_downtime'] for lk in area_lines), 2),
                    'capacity_tm': round(total_cap, 2),
                    'weighting': weighting,
                }

            return jsonify({
                'period': {
                    'start': start.isoformat(),
                    'end': end.isoformat(),
                    'days': window_days,
                    'hours': total_hours_24x7,
                },
                'nodes': nodes,
                'edges': edges,
                'bypass_edges': bypass_edges,
                'line_kpi': list(line_kpi.values()),
                'area_kpi': list(area_kpi.values()),
            })
        except Exception as e:
            logger.exception(f"plant_flow error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/plant-flow/bulk-update', methods=['POST'])
    def api_plant_flow_bulk_update():
        """Actualiza process_order y feeds_into_equipment_id para multiples equipos.
        Body: { updates: [{equipment_id, process_order, feeds_into_equipment_id}] }
        """
        try:
            data = request.get_json() or {}
            updates = data.get('updates') or []
            if not updates:
                return jsonify({"error": "updates requerido"}), 400

            updated = 0
            for u in updates:
                eq = Equipment.query.get(u.get('equipment_id'))
                if not eq:
                    continue
                if 'process_order' in u:
                    eq.process_order = u.get('process_order')
                if 'feeds_into_equipment_id' in u:
                    eq.feeds_into_equipment_id = u.get('feeds_into_equipment_id') or None
                updated += 1
            db.session.commit()
            return jsonify({"ok": True, "updated": updated})
        except Exception as e:
            db.session.rollback()
            logger.exception(f"plant_flow bulk_update error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/production-losses', methods=['GET'])
    def api_production_losses():
        """Datos para el Sankey de pérdidas de producción.

        Estructura de salida:
          { period, total_capacity_hours, total_downtime, total_uptime,
            losses_by_area: [{area_name, hours, pct}],
            losses_by_equipment: [{equipment_tag, equipment_name, area_name, hours, pct}],
            losses_by_failure_mode: [{mode, hours, pct}],
            sankey: { nodes: [...], links: [...] }
          }

        El Sankey representa: Capacidad Teorica → Areas → Equipos → Modos de
        falla → "Tiempo perdido total" (lado derecho).
        """
        try:
            d_start, d_end = _default_period()
            start = _parse_date(request.args.get('start'), d_start)
            end = _parse_date(request.args.get('end'), d_end)
            window_days = max(1, (end - start).days + 1)
            total_hours = window_days * 24

            equipments = Equipment.query.filter_by(include_in_kpi=True).all()
            areas = {a.id: a for a in Area.query.all()}
            lines = {l.id: l for l in Line.query.all()}

            # Capacidad teorica = N equipos × horas del periodo (24/7 simplificado)
            total_capacity_hours = len(equipments) * total_hours

            # OTs cerradas con downtime en el periodo
            all_ots = WorkOrder.query.filter(
                WorkOrder.status == 'Cerrada',
                WorkOrder.caused_downtime == True,  # noqa: E712
            ).all()

            def in_window(ot):
                d = ot.real_end_date or ot.scheduled_date or ot.real_start_date
                if not d:
                    return False
                try:
                    return start <= dt.date.fromisoformat(d[:10]) <= end
                except Exception:
                    return False

            ots = [o for o in all_ots if in_window(o) and o.downtime_hours]
            kpi_eq_ids = {e.id for e in equipments}
            ots = [o for o in ots if o.equipment_id in kpi_eq_ids]

            total_downtime = sum(float(o.downtime_hours) for o in ots)
            total_uptime = max(0.0, total_capacity_hours - total_downtime)

            # Agrupaciones
            by_eq = {}
            by_area = {}
            by_mode = {}
            for o in ots:
                eq = next((e for e in equipments if e.id == o.equipment_id), None)
                if not eq:
                    continue
                line = lines.get(eq.line_id)
                area = areas.get(line.area_id) if line else None
                area_name = area.name if area else 'Sin Area'
                mode = (o.failure_mode or 'Sin clasificar').strip() or 'Sin clasificar'
                hh = float(o.downtime_hours)

                by_eq[eq.id] = by_eq.get(eq.id, 0) + hh
                by_area[area_name] = by_area.get(area_name, 0) + hh
                by_mode[mode] = by_mode.get(mode, 0) + hh

            # Top equipos (max 15 para no sobrecargar el sankey)
            eq_list = sorted([
                {
                    'equipment_id': eid,
                    'equipment_tag': next((e.tag for e in equipments if e.id == eid), '?'),
                    'equipment_name': next((e.name for e in equipments if e.id == eid), '?'),
                    'area_name': next(
                        (areas.get(lines.get(e.line_id).area_id).name
                         if e.line_id and lines.get(e.line_id) and areas.get(lines.get(e.line_id).area_id)
                         else 'Sin Area' for e in equipments if e.id == eid), 'Sin Area'),
                    'hours': round(h, 2),
                    'pct': round(h / total_downtime * 100, 1) if total_downtime else 0,
                }
                for eid, h in by_eq.items()
            ], key=lambda x: x['hours'], reverse=True)

            top_eqs = eq_list[:15]
            other_eq_hours = sum(e['hours'] for e in eq_list[15:])

            # Top modos (max 8)
            mode_list = sorted([
                {'mode': m, 'hours': round(h, 2),
                 'pct': round(h / total_downtime * 100, 1) if total_downtime else 0}
                for m, h in by_mode.items()
            ], key=lambda x: x['hours'], reverse=True)
            top_modes = mode_list[:8]
            other_mode_hours = sum(m['hours'] for m in mode_list[8:])

            # Construir nodos y enlaces para el Sankey
            # Esquema: AREA -> EQUIPO -> MODO DE FALLA
            nodes = []
            node_idx = {}
            def add_node(name, category):
                if name in node_idx:
                    return node_idx[name]
                idx = len(nodes)
                nodes.append({'name': name, 'category': category})
                node_idx[name] = idx
                return idx

            # Agregar areas
            for an in by_area.keys():
                add_node(f"AREA: {an}", 'area')
            # Agregar equipos
            for e in top_eqs:
                add_node(f"{e['equipment_tag']} - {e['equipment_name']}", 'equipment')
            if other_eq_hours > 0:
                add_node('Otros equipos', 'equipment')
            # Agregar modos
            for m in top_modes:
                add_node(m['mode'], 'mode')
            if other_mode_hours > 0:
                add_node('Otros modos', 'mode')

            # Enlaces AREA -> EQUIPO
            links = []
            for e in top_eqs:
                src_name = f"AREA: {e['area_name']}"
                tgt_name = f"{e['equipment_tag']} - {e['equipment_name']}"
                if src_name in node_idx and tgt_name in node_idx:
                    links.append({
                        'source': node_idx[src_name],
                        'target': node_idx[tgt_name],
                        'value': e['hours'],
                    })

            # Enlaces EQUIPO -> MODO (proporcional al downtime de cada equipo)
            for o in ots:
                eq = next((e for e in equipments if e.id == o.equipment_id), None)
                if not eq:
                    continue
                eq_label = f"{eq.tag} - {eq.name}"
                if eq_label not in node_idx:
                    eq_label = 'Otros equipos'
                mode = (o.failure_mode or 'Sin clasificar').strip() or 'Sin clasificar'
                if mode not in node_idx:
                    mode = 'Otros modos'
                if eq_label in node_idx and mode in node_idx:
                    links.append({
                        'source': node_idx[eq_label],
                        'target': node_idx[mode],
                        'value': float(o.downtime_hours),
                    })

            return jsonify({
                'period': {'start': start.isoformat(), 'end': end.isoformat(),
                           'days': window_days, 'hours': total_hours},
                'total_capacity_hours': round(total_capacity_hours, 2),
                'total_downtime_hours': round(total_downtime, 2),
                'total_uptime_hours': round(total_uptime, 2),
                'overall_availability_pct': round(total_uptime / total_capacity_hours * 100, 2) if total_capacity_hours else 100,
                'losses_by_area': [{'area_name': k, 'hours': round(v, 2),
                                    'pct': round(v / total_downtime * 100, 1) if total_downtime else 0}
                                   for k, v in sorted(by_area.items(), key=lambda x: -x[1])],
                'losses_by_equipment': eq_list,
                'losses_by_failure_mode': mode_list,
                'sankey': {'nodes': nodes, 'links': links},
            })
        except Exception as e:
            logger.exception(f"production_losses error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/plant-flow/seed-from-pdf', methods=['POST'])
    def api_plant_flow_seed_from_pdf():
        """Pre-carga el flujo del PDF del usuario. Idempotente — solo setea
        feeds_into_equipment_id si esta vacio (no sobrescribe configuracion
        manual). Match por TAG del equipo.

        Mapa derivado del diagrama de la planta (Triturado, Coccion,
        parte de Secado): TH POZA -> TH ALIMENTADOR -> TRITURADOR 100HP -> ...
        Cuando el usuario completa el resto, agrega aqui o usa la UI.
        """
        try:
            # (tag_origen, tag_destino, process_order_origen)
            FLOW_MAP = [
                # AREA TRITURADO - Linea Triturador Grande
                ('TH-POZA', 'TH-ALIM-TG', 1),
                ('TH-ALIM-TG', 'TRIT-100HP', 2),
                ('TRIT-100HP', 'TH-SAL-TG', 3),
                ('TH-SAL-TG', None, 4),  # punto de apilamiento
                # AREA TRITURADO - Linea Triturador Pequeño
                ('TRIT-75HP', 'TH-SAL-TP', 1),
                ('TH-SAL-TP', None, 2),  # punto de apilamiento
                # AREA COCCION
                ('TH1', 'D1', 1), ('TH2', 'D2', 1), ('TH3', 'D3', 1),
                ('TH4', 'D4', 1), ('TH5', 'D5', 1), ('TH6', 'D6', 1),
                ('TH7', 'D7', 1), ('TH8', 'D8', 1), ('TH9', 'D9', 1),
                ('D1', 'PER1', 2), ('D2', 'PER1', 2), ('D3', 'PER1', 2),
                ('D4', 'PER1', 2), ('D5', 'PER1', 2), ('D6', 'PER1', 2),
                ('D7', 'PER2', 2), ('D8', 'PER2', 2), ('D9', 'PER2', 2),
                # AREA SECADO - Linea Secador #2 (PER1 alimenta)
                ('PER1', 'SEC2-TH1', 3),
                ('SEC2-TH1', 'SEC2-TH2', 1),
                ('SEC2-TH2', 'SEC2', 2),
                ('SEC2', 'SEC2-TH3', 3),
                ('SEC2-TH3', 'SEC2-TH4', 4),
                ('SEC2-TH4', 'SEC2-TH5', 5),
                ('SEC2-TH5', 'SEC2-TH6', 6),
                ('SEC2-TH6', 'SEC2-TH7', 7),
                ('SEC2-TH7', 'SEC2-TH8', 8),
                ('SEC2-TH8', 'SEC2-TH9', 9),
                ('SEC2-TH9', 'SEC2-TH10', 10),
                ('SEC2-TH10', None, 11),  # punto de apilamiento
                # AREA SECADO - Linea Secador #1 (PER2 alimenta)
                ('PER2', 'TH-ALIM-SEC1', 3),
                ('TH-ALIM-SEC1', 'SEC1', 1),
                ('SEC1', 'TH-SAL-SEC1', 2),
                ('TH-SAL-SEC1', 'SEC1-TH1-SAL', 3),
                ('SEC1-TH1-SAL', 'TH2-ENF', 4),
                ('TH2-ENF', 'TH-REPRO', 5),
            ]

            updated = 0
            skipped_not_found = []
            skipped_existing = []
            # Buscar equipos por tag (case-insensitive y permitiendo espacios)
            all_eqs = Equipment.query.all()
            by_tag = {(e.tag or '').upper().replace(' ', '').replace('-', ''): e
                      for e in all_eqs}

            def lookup(tag):
                if not tag:
                    return None
                key = tag.upper().replace(' ', '').replace('-', '')
                return by_tag.get(key)

            for src_tag, dst_tag, p_order in FLOW_MAP:
                src = lookup(src_tag)
                if not src:
                    skipped_not_found.append(src_tag)
                    continue
                # Solo escribir si no esta seteado (idempotente)
                if src.process_order is None:
                    src.process_order = p_order
                else:
                    skipped_existing.append(f"{src_tag}.process_order")

                if src.feeds_into_equipment_id is None and dst_tag:
                    dst = lookup(dst_tag)
                    if dst:
                        src.feeds_into_equipment_id = dst.id
                        updated += 1
                    else:
                        skipped_not_found.append(dst_tag)
                elif src.feeds_into_equipment_id is not None:
                    skipped_existing.append(f"{src_tag}.feeds_into")

            db.session.commit()
            return jsonify({
                "ok": True,
                "edges_created": updated,
                "tags_not_found": sorted(set(skipped_not_found)),
                "fields_already_set": len(skipped_existing),
                "hint": "Si hay tags_not_found, ajustalos en /jerarquia (el match es por TAG normalizado)."
            })
        except Exception as e:
            db.session.rollback()
            logger.exception(f"seed_from_pdf error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Bypass / rutas alternativas ───────────────────────────────────────────
    @app.route('/api/plant-flow/bypass', methods=['GET'])
    def api_bypass_list():
        try:
            rows = EquipmentFlowEdge.query.order_by(EquipmentFlowEdge.id.desc()).all()
            return jsonify([r.to_dict() for r in rows])
        except Exception as e:
            logger.exception(f"bypass_list error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/plant-flow/bypass', methods=['POST'])
    def api_bypass_create():
        try:
            data = request.get_json() or {}
            from_id = data.get('from_equipment_id')
            to_id = data.get('to_equipment_id')
            if not from_id or not to_id:
                return jsonify({"error": "from_equipment_id y to_equipment_id requeridos"}), 400
            if int(from_id) == int(to_id):
                return jsonify({"error": "origen y destino no pueden ser el mismo equipo"}), 400
            if not Equipment.query.get(from_id) or not Equipment.query.get(to_id):
                return jsonify({"error": "equipo no encontrado"}), 404
            # Evitar duplicados
            exists = EquipmentFlowEdge.query.filter_by(
                from_equipment_id=from_id, to_equipment_id=to_id).first()
            if exists:
                exists.is_active = True
                exists.edge_type = (data.get('edge_type') or exists.edge_type or 'BYPASS').upper()
                exists.note = data.get('note') or exists.note
                db.session.commit()
                return jsonify({"ok": True, "id": exists.id, "reactivated": True})
            edge = EquipmentFlowEdge(
                from_equipment_id=int(from_id),
                to_equipment_id=int(to_id),
                edge_type=(data.get('edge_type') or 'BYPASS').upper(),
                note=data.get('note'),
                is_active=True,
            )
            db.session.add(edge)
            db.session.commit()
            return jsonify({"ok": True, "id": edge.id})
        except Exception as e:
            db.session.rollback()
            logger.exception(f"bypass_create error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/plant-flow/bypass/<int:edge_id>', methods=['DELETE'])
    def api_bypass_delete(edge_id):
        try:
            edge = EquipmentFlowEdge.query.get(edge_id)
            if not edge:
                return jsonify({"error": "no encontrado"}), 404
            db.session.delete(edge)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            logger.exception(f"bypass_delete error: {e}")
            return jsonify({"error": str(e)}), 500
