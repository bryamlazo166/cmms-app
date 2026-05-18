"""Operatividad Anual de Equipos.

Vista de grilla 12 meses x 4 semanas por equipo, coloreada por estado:
  - Verde:    al menos 1 dia operativo en la semana
  - Amarillo: los 7 dias de la semana inoperativos
  - Gris:     semana futura (sin datos esperables)

Un dia se considera "inoperativo" si hay una OT con caused_downtime=true
cuyo intervalo de paro cubre ese dia (mismo criterio que plant_flow).

Las semanas son fijas dentro del mes:
  S1 = dias 1-7, S2 = dias 8-14, S3 = dias 15-21, S4 = dias 22-fin de mes.
Esto da 48 celdas por equipo por año (no usamos semanas ISO porque cruzan
meses y rompen la grilla mensual que pidio el usuario).
"""
import datetime as dt

from flask import jsonify, render_template, request
from flask_login import login_required


def register_operatividad_routes(app, db, logger, Equipment, Area, Line, WorkOrder):

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _parse_ts(raw):
        """'YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM[:SS]' -> datetime. None si falla."""
        if not raw:
            return None
        try:
            s = str(raw)[:19]
            if 'T' in s:
                if len(s) == 16:
                    s += ':00'
                return dt.datetime.fromisoformat(s)
            return dt.datetime.fromisoformat(s + 'T00:00:00')
        except Exception:
            return None

    def _ot_interval(ot):
        """Mismo criterio que plant_flow_routes:
        1) real_start+real_end  2) real_start+downtime_hours  3) real_end-downtime_hours."""
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

    def _month_last_day(year, month):
        if month == 12:
            return 31
        return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day

    def _week_range(year, month, week):
        """Devuelve (date_inicio, date_fin) de la semana dentro del mes.
        Semanas fijas: S1=1-7, S2=8-14, S3=15-21, S4=22-fin.
        """
        start_day = (week - 1) * 7 + 1
        if week == 4:
            end_day = _month_last_day(year, month)
        else:
            end_day = start_day + 6
        return dt.date(year, month, start_day), dt.date(year, month, end_day)

    def _days_in_week(year, month, week):
        a, b = _week_range(year, month, week)
        return [(a + dt.timedelta(days=i)) for i in range((b - a).days + 1)]

    # ── Endpoints ────────────────────────────────────────────────────────────

    @app.route('/operatividad-anual', methods=['GET'])
    @login_required
    def operatividad_anual_page():
        return render_template('operatividad_anual.html')

    @app.route('/api/operatividad-anual/filters', methods=['GET'])
    @login_required
    def operatividad_filters():
        """Devuelve areas, lineas (con area_id) y equipos (con line_id, area_id)
        para alimentar los filtros en cascada. El area del equipo se deriva
        a traves de su linea (Equipment no tiene area_id directo)."""
        try:
            areas = [{"id": a.id, "name": a.name} for a in Area.query.order_by(Area.name).all()]
            lines_data = Line.query.order_by(Line.name).all()
            line_to_area = {l.id: l.area_id for l in lines_data}
            lines = [{"id": l.id, "name": l.name, "area_id": l.area_id} for l in lines_data]
            equipments = [{"id": e.id, "tag": e.tag, "name": e.name,
                           "line_id": e.line_id, "area_id": line_to_area.get(e.line_id)}
                          for e in Equipment.query.order_by(Equipment.tag).all()]
            return jsonify({"areas": areas, "lines": lines, "equipments": equipments})
        except Exception as e:
            logger.exception('operatividad_filters error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/operatividad-anual', methods=['GET'])
    @login_required
    def operatividad_anual_data():
        """Grilla anual de operatividad.

        Query params:
          year         (int, default = año actual)
          area_id      (opcional, filtra equipos por area)
          line_id      (opcional, filtra equipos por linea)
          equipment_id (opcional, devuelve un solo equipo)
        """
        try:
            year = int(request.args.get('year') or dt.date.today().year)
            area_id = request.args.get('area_id', type=int)
            line_id = request.args.get('line_id', type=int)
            equipment_id = request.args.get('equipment_id', type=int)

            # Mapa line_id -> area_id (Equipment no tiene area_id directo,
            # se deriva via su Line).
            line_to_area = {l.id: l.area_id for l in Line.query.all()}

            q = Equipment.query
            if equipment_id:
                q = q.filter(Equipment.id == equipment_id)
            elif line_id:
                q = q.filter(Equipment.line_id == line_id)
            elif area_id:
                # Filtrar por todas las lineas que pertenecen al area
                line_ids_of_area = [lid for lid, aid in line_to_area.items() if aid == area_id]
                if not line_ids_of_area:
                    return jsonify({"year": year, "equipments": [], "today": dt.date.today().isoformat()})
                q = q.filter(Equipment.line_id.in_(line_ids_of_area))
            equipments = q.order_by(Equipment.tag).all()

            year_start = dt.date(year, 1, 1)
            year_end = dt.date(year, 12, 31)
            today = dt.date.today()

            # OTs con caused_downtime=true en cualquier estado, que solapen el año.
            # No restringimos a 'Cerrada' porque OTs En Progreso con downtime tambien
            # cuentan como inoperativo.
            eq_ids = [e.id for e in equipments]
            if not eq_ids:
                return jsonify({"year": year, "equipments": [], "today": today.isoformat()})

            ots = WorkOrder.query.filter(
                WorkOrder.caused_downtime == True,  # noqa: E712
                WorkOrder.equipment_id.in_(eq_ids),
            ).all()

            # Pre-bucket: eq_id -> set de fechas inoperativas en el año
            inop_days = {eid: set() for eid in eq_ids}
            for ot in ots:
                ini, fin = _ot_interval(ot)
                if not (ini and fin):
                    continue
                a = max(ini.date(), year_start)
                b = min(fin.date(), year_end)
                if b < a:
                    continue
                d = a
                while d <= b:
                    inop_days[ot.equipment_id].add(d)
                    d += dt.timedelta(days=1)

            # Construir grilla 12 x 4 por equipo
            result_equipments = []
            for eq in equipments:
                cells = []
                total_year_days = 0
                total_year_down = 0
                for month in range(1, 13):
                    for week in range(1, 5):
                        days = _days_in_week(year, month, week)
                        n_total = len(days)
                        n_down = sum(1 for d in days if d in inop_days[eq.id])
                        # Estado segun cuantos dias de la semana ya pasaron
                        days_past = [d for d in days if d <= today]
                        if not days_past:
                            status = 'future'
                        elif n_down >= n_total:
                            status = 'inoperative'  # 7/7 dias caidos (en S4 puede ser 6-10/X)
                        else:
                            status = 'operative'
                        cells.append({
                            "month": month, "week": week,
                            "status": status, "down_days": n_down, "total_days": n_total,
                            "start": days[0].isoformat(), "end": days[-1].isoformat(),
                        })
                        if days_past:
                            total_year_days += len(days_past)
                            total_year_down += sum(1 for d in days_past if d in inop_days[eq.id])

                avail = 100.0 if total_year_days == 0 else round(
                    (total_year_days - total_year_down) / total_year_days * 100, 1)
                result_equipments.append({
                    "id": eq.id,
                    "tag": eq.tag,
                    "name": eq.name,
                    "area_id": line_to_area.get(eq.line_id),
                    "line_id": eq.line_id,
                    "cells": cells,
                    "availability": avail,
                    "down_days_ytd": total_year_down,
                })

            return jsonify({
                "year": year,
                "today": today.isoformat(),
                "equipments": result_equipments,
            })
        except Exception as e:
            logger.exception('operatividad_anual_data error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/operatividad-anual/cell', methods=['GET'])
    @login_required
    def operatividad_cell_detail():
        """Detalle de una celda (semana): lista de OTs con downtime que tocan
        ese rango para el equipo dado. Util para drill-down al hacer click."""
        try:
            year = int(request.args.get('year') or dt.date.today().year)
            month = int(request.args.get('month'))
            week = int(request.args.get('week'))
            equipment_id = int(request.args.get('equipment_id'))

            a, b = _week_range(year, month, week)
            a_dt = dt.datetime.combine(a, dt.time(0, 0))
            b_dt = dt.datetime.combine(b, dt.time(23, 59, 59))

            ots = WorkOrder.query.filter(
                WorkOrder.equipment_id == equipment_id,
                WorkOrder.caused_downtime == True,  # noqa: E712
            ).all()

            rows = []
            for ot in ots:
                ini, fin = _ot_interval(ot)
                if not (ini and fin):
                    continue
                if fin < a_dt or ini > b_dt:
                    continue
                horas = round((fin - ini).total_seconds() / 3600.0, 1)
                rows.append({
                    "code": ot.code,
                    "id": ot.id,
                    "description": (ot.description or '')[:200],
                    "maintenance_type": ot.maintenance_type,
                    "status": ot.status,
                    "start": ini.isoformat(timespec='minutes'),
                    "end": fin.isoformat(timespec='minutes'),
                    "downtime_hours": horas,
                })
            rows.sort(key=lambda r: r['start'])
            return jsonify({
                "year": year, "month": month, "week": week,
                "start": a.isoformat(), "end": b.isoformat(),
                "equipment_id": equipment_id, "ots": rows,
            })
        except Exception as e:
            logger.exception('operatividad_cell_detail error')
            return jsonify({"error": str(e)}), 500
