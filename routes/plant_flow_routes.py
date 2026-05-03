"""Plant Flow / Diagrama de Flujo de Planta.

Devuelve el flujo de proceso de la planta (equipos conectados aguas arriba/abajo)
con KPI de disponibilidad por equipo en un periodo dado. Por defecto: desde el
primer dia del mes anterior hasta hoy.

Tambien expone Sankey de perdidas de produccion (Sprint 2): horas perdidas por
equipo y modo de falla en el periodo.
"""
import datetime as dt
import math

from flask import jsonify, render_template, request


def register_plant_flow_routes(app, db, logger, Equipment, Area, Line, WorkOrder, EquipmentFlowEdge):

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

    def _calc_equipment_availability(eq_id, ots_in_period, total_hours):
        """Disponibilidad simple: (total_hours - sum(downtime)) / total_hours * 100"""
        downtime = 0.0
        n_failures = 0
        for ot in ots_in_period:
            if ot.equipment_id != eq_id:
                continue
            if not (ot.caused_downtime and ot.downtime_hours):
                continue
            downtime += float(ot.downtime_hours)
            n_failures += 1
        if total_hours <= 0:
            return 100.0, 0, 0
        avail = max(0.0, (total_hours - downtime) / total_hours * 100)
        return round(avail, 2), round(downtime, 2), n_failures

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
            total_hours = window_days * 24

            # Equipos KPI-relevantes con su jerarquia
            equipments = Equipment.query.filter_by(include_in_kpi=True).all()
            areas = {a.id: a for a in Area.query.all()}
            lines = {l.id: l for l in Line.query.all()}

            # OTs cerradas en el periodo con downtime
            all_ots = WorkOrder.query.filter(
                WorkOrder.status == 'Cerrada',
                WorkOrder.caused_downtime == True,  # noqa: E712
            ).all()

            def in_window(ot):
                d = ot.real_end_date or ot.scheduled_date or ot.real_start_date
                if not d:
                    return False
                try:
                    od = dt.date.fromisoformat(d[:10])
                    return start <= od <= end
                except Exception:
                    return False

            ots_in_period = [o for o in all_ots if in_window(o)]

            # Construir nodos
            nodes = []
            for eq in equipments:
                line = lines.get(eq.line_id)
                area = areas.get(line.area_id) if line else None
                avail, downtime, fails = _calc_equipment_availability(
                    eq.id, ots_in_period, total_hours)
                # Color semaforo
                if avail >= 95:
                    color = 'green'
                elif avail >= 85:
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
                    'availability': avail,
                    'downtime_hours': downtime,
                    'failure_count': fails,
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
            bypass_rows = EquipmentFlowEdge.query.filter_by(is_active=True).all()
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

            # Disponibilidad por linea (producto de los equipos en serie)
            line_kpi = {}
            for line_id, line in lines.items():
                line_eqs = [n for n in nodes if n['line_id'] == line_id]
                if not line_eqs:
                    continue
                # Producto de disponibilidades (modelo serie)
                prod = 1.0
                for n in line_eqs:
                    prod *= (n['availability'] / 100.0)
                line_kpi[line_id] = {
                    'line_id': line_id,
                    'line_name': line.name,
                    'area_id': line.area_id,
                    'area_name': areas[line.area_id].name if areas.get(line.area_id) else None,
                    'equipment_count': len(line_eqs),
                    'availability': round(prod * 100, 2),
                    'total_downtime': round(sum(n['downtime_hours'] for n in line_eqs), 2),
                    'total_failures': sum(n['failure_count'] for n in line_eqs),
                }

            # Disponibilidad por area (promedio ponderado simple)
            area_kpi = {}
            for area_id, area in areas.items():
                area_lines = [lk for lk in line_kpi.values() if lk['area_id'] == area_id]
                if not area_lines:
                    continue
                avg_avail = sum(lk['availability'] for lk in area_lines) / len(area_lines)
                area_kpi[area_id] = {
                    'area_id': area_id,
                    'area_name': area.name,
                    'line_count': len(area_lines),
                    'availability': round(avg_avail, 2),
                    'total_downtime': round(sum(lk['total_downtime'] for lk in area_lines), 2),
                }

            return jsonify({
                'period': {
                    'start': start.isoformat(),
                    'end': end.isoformat(),
                    'days': window_days,
                    'hours': total_hours,
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
