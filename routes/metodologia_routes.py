"""Metodologia de los indicadores — como sale cada numero.

Este modulo existe para una conversacion concreta: sentarse con la jefatura
de mantenimiento, mostrar la formula de cada indicador y decidir si se acepta
o se cambia. Por eso no es un documento estatico.

Cada indicador se presenta en tres capas:

    1. LA FORMULA, escrita como se escribe en la norma.
    2. LA SUSTITUCION con los numeros reales del periodo elegido — el mismo
       equipo, las mismas horas y el mismo resultado que muestran las demas
       pantallas.
    3. LAS ORDENES que alimentaron ese numero, para poder cuadrarlo a mano.

Si el numero de la lamina no se puede reconstruir aqui paso a paso, el
indicador no esta listo para presentarse.
"""
import calendar
import datetime as dt

from flask import jsonify, render_template, request


AREAS_PROCESO = ['COCCION', 'SECADO', 'MOLINO']
MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre']


def register_metodologia_routes(app, db, logger):
    from models import Area, Equipment, Line, WorkOrder

    def _rango(month, desde, hasta):
        if desde and hasta:
            ini = dt.date.fromisoformat(desde[:10])
            fin = dt.date.fromisoformat(hasta[:10])
        else:
            y, m = int(month[:4]), int(month[5:7])
            ini = dt.date(y, m, 1)
            fin = dt.date(y, m, calendar.monthrange(y, m)[1])
        dias = (fin - ini).days + 1
        etiqueta = (f'{MESES[ini.month]} {ini.year}'
                    if ini.day == 1 and fin.day == calendar.monthrange(fin.year, fin.month)[1]
                    and ini.month == fin.month
                    else f'{ini.isoformat()} a {fin.isoformat()}')
        return {'ini': ini, 'fin': fin, 'desde': ini.isoformat(),
                'hasta': fin.isoformat(), 'dias': dias, 'tep': dias * 24,
                'etiqueta': etiqueta}

    def _ots_del_rango(per):
        """OTs cerradas del periodo con el nombre del equipo, como dicts."""
        equipos = {e.id: e for e in Equipment.query.all()}
        filas = WorkOrder.query.with_entities(
            WorkOrder.id, WorkOrder.code, WorkOrder.description,
            WorkOrder.maintenance_type, WorkOrder.status, WorkOrder.equipment_id,
            WorkOrder.shutdown_id, WorkOrder.caused_downtime,
            WorkOrder.downtime_hours, WorkOrder.downtime_planned,
            WorkOrder.real_duration, WorkOrder.scheduled_date,
            WorkOrder.real_start_date, WorkOrder.real_end_date
        ).filter(WorkOrder.status == 'Cerrada').all()

        por_equipo = {}
        for f in filas:
            fecha = str(f.real_end_date or f.real_start_date
                        or f.scheduled_date or '')[:10]
            if not fecha or not (per['desde'] <= fecha <= per['hasta']):
                continue
            if not f.equipment_id:
                continue
            e = equipos.get(f.equipment_id)
            por_equipo.setdefault(f.equipment_id, []).append({
                'id': f.id, 'code': f.code, 'description': f.description,
                'maintenance_type': f.maintenance_type, 'status': f.status,
                'equipment_id': f.equipment_id, 'shutdown_id': f.shutdown_id,
                'caused_downtime': f.caused_downtime,
                'downtime_hours': f.downtime_hours,
                'downtime_planned': f.downtime_planned,
                'real_duration': f.real_duration,
                'scheduled_date': f.scheduled_date,
                'equipment_name': (e.name if e else ''),
                'equipment_tag': (e.tag if e else ''),
                'fecha': fecha,
            })
        return equipos, por_equipo

    def _nombre(e):
        return (e.tag or e.name or f'EQ-{e.id}') if e else '—'

    @app.route('/metodologia-indicadores', methods=['GET'])
    def metodologia_page():
        return render_template('metodologia.html')

    @app.route('/api/metodologia/data', methods=['GET'])
    def metodologia_data():
        """month=YYYY-MM (o desde/hasta) · modo=inherente|operativa

        Devuelve la formula de cada indicador junto a su sustitucion con los
        numeros reales del periodo, tomando como ejemplo el equipo de proceso
        que mas horas de parada acumulo — el ejemplo interesante, no uno con
        todo en cero.
        """
        try:
            from routes.indicators_routes import (RELIABILITY_HOURS,
                                                  _calc_indicators)
            from utils.kpi_helpers import (eq_capacity_basis, eq_harina_tm_day,
                                           eq_is_batch, eq_produces,
                                           plant_yield_factor)

            hoy = dt.date.today()
            defecto = (dt.date(hoy.year, hoy.month, 1) - dt.timedelta(days=1)).strftime('%Y-%m')
            per = _rango((request.args.get('month') or defecto)[:7],
                         request.args.get('desde'), request.args.get('hasta'))
            modo = (request.args.get('modo') or 'inherente').lower()
            horizonte = request.args.get('horizonte', default=RELIABILITY_HOURS, type=float)

            areas = {a.id: a for a in Area.query.all()}
            lines = {l.id: l for l in Line.query.all()}
            equipos, por_equipo = _ots_del_rango(per)
            rend = plant_yield_factor(list(equipos.values()))

            # Capacidad por equipo (el peso de la ponderacion)
            cap_eq, eq_de_area = {}, {}
            for e in equipos.values():
                if not e.include_in_kpi or e.line_id not in lines:
                    continue
                cap_eq[e.id] = (eq_harina_tm_day(e, rend)
                                if eq_produces(e) and e.in_service else 0.0)
                eq_de_area.setdefault(lines[e.line_id].area_id, []).append(e.id)

            proceso = [aid for aid, a in areas.items()
                       if (a.name or '').upper() in AREAS_PROCESO]

            # ── Ejemplo: el equipo de proceso con mas horas de parada ────
            candidatos = []
            for aid in proceso:
                for eid in eq_de_area.get(aid, []):
                    ind = _calc_indicators(por_equipo.get(eid, []), per['tep'],
                                           mode=modo, reliability_hours=horizonte)
                    candidatos.append((ind['downtime_hours'], eid, aid, ind))
            candidatos.sort(key=lambda x: (-x[0], x[1]))
            if not candidatos:
                return jsonify({'error': 'No hay equipos de proceso configurados '
                                         'en Alcance de Indicadores.'}), 200

            _h, eid, aid, ind = candidatos[0]
            eq = equipos[eid]
            area = areas[aid]
            ots_eq = sorted(por_equipo.get(eid, []),
                            key=lambda o: -(float(o.get('downtime_hours') or 0)))

            ejemplo = {
                'equipo': _nombre(eq),
                'equipo_nombre': eq.name or '',
                'area': area.name,
                'dias': per['dias'],
                'tep': per['tep'],
                'paro_planificado': ind['downtime_planned_hours'],
                'paro_averia': ind['downtime_unplanned_hours'],
                'uptime': round(per['tep'] - ind['downtime_planned_hours']
                                - ind['downtime_unplanned_hours'], 2),
                'base_inherente': round(per['tep'] - ind['downtime_planned_hours'], 2),
                'fallas': ind['failure_count'],
                'paro_del_modo': ind['downtime_hours'],
                'mtbf': ind['mtbf'], 'mttr': ind['mttr'],
                'disp_operativa': ind['availability_operativa'],
                'disp_inherente': ind['availability_inherente'],
                'confiabilidad': ind['reliability'],
                'horizonte': horizonte,
                'ots': [{
                    'code': o.get('code') or f"OT-{o['id']}",
                    'tipo': o.get('maintenance_type') or '—',
                    'fecha': o.get('fecha'),
                    'descripcion': (o.get('description') or '')[:150],
                    'horas': round(float(o.get('downtime_hours')
                                         or o.get('real_duration') or 0), 2)
                             if o.get('caused_downtime') else 0.0,
                    'cuenta': bool(o.get('caused_downtime')
                                   and (o.get('downtime_hours') or o.get('real_duration'))),
                } for o in ots_eq],
            }

            # ── Ponderacion del area de ese equipo ──────────────────────
            filas, num, den = [], 0.0, 0.0
            for otro in eq_de_area.get(aid, []):
                cap = cap_eq.get(otro, 0.0)
                i2 = _calc_indicators(por_equipo.get(otro, []), per['tep'],
                                      mode=modo, reliability_hours=horizonte)
                filas.append({
                    'equipo': _nombre(equipos.get(otro)),
                    'capacidad': round(cap, 2),
                    'disponibilidad': i2['availability'],
                    'aporte': round(i2['availability'] * cap, 2),
                    'pesa': cap > 0,
                })
                if cap > 0:
                    num += i2['availability'] * cap
                    den += cap
            filas.sort(key=lambda x: (-x['capacidad'], x['equipo']))
            ponderacion = {
                'area': area.name,
                'filas': filas,
                'numerador': round(num, 2),
                'denominador': round(den, 2),
                'resultado': round(num / den, 2) if den else None,
                'promedio_simple': (round(sum(f['disponibilidad'] for f in filas if f['pesa'])
                                          / max(1, len([f for f in filas if f['pesa']])), 2)
                                    if den else None),
            }

            # ── Capacidad: la formula de llenadas sobre un digestor real ─
            batch = next((e for e in equipos.values()
                          if eq_is_batch(e) and e.include_in_kpi and e.in_service), None)
            capacidad = None
            if batch:
                from utils.kpi_helpers import (DEFAULT_BATCHES_PER_DAY,
                                               DEFAULT_FILL_PCT,
                                               eq_capacity_tm_day)
                capacidad = {
                    'equipo': _nombre(batch),
                    'kg': batch.batch_capacity_kg,
                    'llenado': batch.fill_pct if batch.fill_pct is not None else DEFAULT_FILL_PCT,
                    'llenadas': (batch.batches_per_day if batch.batches_per_day is not None
                                 else DEFAULT_BATCHES_PER_DAY),
                    'tm_mp': round(eq_capacity_tm_day(batch), 2),
                    'rendimiento': round(rend * 100, 1),
                    'tm_harina': round(eq_harina_tm_day(batch, rend), 2),
                    'base': eq_capacity_basis(batch),
                }

            return jsonify({
                'meta': {
                    'periodo': per['etiqueta'], 'desde': per['desde'],
                    'hasta': per['hasta'], 'dias': per['dias'], 'tep': per['tep'],
                    'modo': modo, 'horizonte_h': horizonte,
                    'rendimiento_pct': round(rend * 100, 1),
                    'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                },
                'ejemplo': ejemplo,
                'ponderacion': ponderacion,
                'capacidad': capacidad,
            })
        except Exception as e:
            logger.exception('metodologia_data error')
            return jsonify({'error': str(e)}), 500
