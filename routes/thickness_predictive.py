"""Predictivo de espesores — tasa de desgaste y vida remanente proyectada.

Sobre las mediciones UT que ya registra el módulo de espesores, calcula por
cada punto (criterio API 570/510):

    tasa de desgaste [mm/año] = regresión lineal sobre las campañas
    vida remanente             = (espesor actual − espesor de retiro) / tasa

Detecta INTERVENCIONES automáticamente: si el espesor SUBE entre campañas
(≥ +2 mm) es que la pieza fue reparada/reemplazada — la regresión se reinicia
desde ese punto (caso real: tapa conducida del D9, 3.4 mm → 25.4 mm).

Escalable por diseño: trabaja sobre thickness_points/inspections/readings del
árbol de equipos — un digestor nuevo entra solo con darlo de alta y medir.

Permisos: cae bajo el módulo 'espesores' existente (páginas /espesores*,
API /api/thickness*). El análisis narrativo usa DeepSeek (DEEPSEEK_API_KEY).
"""
import os
import datetime as dt
import logging

import requests
from flask import jsonify, request, render_template

logger = logging.getLogger(__name__)

# ── Parámetros del modelo ──────────────────────────────────────────────────
RENEWAL_JUMP_MM = 2.0     # subida entre campañas ≥ esto = reparación/cambio
MIN_RATE_MM_YR = 0.15     # por debajo se considera "estable" (ruido de medición)
MIN_SPAN_DAYS = 14        # separación mínima entre campañas para calcular tasa
RED_MONTHS = 6            # vida remanente < 6 meses  -> ROJO
AMBER_MONTHS = 18         # vida remanente < 18 meses -> AMBAR
OVER_NOMINAL_TOL = 1.10   # lectura > nominal×1.10 = físicamente imposible → se descarta

SEVERITY = {'CRITICO': 0, 'ROJO': 1, 'AMBAR': 2, 'VERDE': 3,
            'ESTABLE': 4, 'SIN_TENDENCIA': 5, 'DATO_DUDOSO': 6}

DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'


def _parse_date(s):
    if isinstance(s, dt.date):
        return s
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def compute_point_forecast(readings, alarm, scrap, nominal=None, today=None):
    """Proyección de un punto de medición.

    readings: lista [(fecha, valor_mm)] en cualquier orden.
    Si se pasa `nominal`, las lecturas físicamente imposibles (> nominal×1.10,
    p.ej. campañas cargadas con valores de relleno) se DESCARTAN y se reportan
    en `discarded` para que el usuario corrija la medición o el nominal.
    Devuelve dict con current/last_date/rate_mm_yr/months_to_alarm/
    months_to_scrap/scrap_date/status/interventions/n_segment, o None sin datos.
    """
    today = today or dt.date.today()
    clean = []
    discarded = 0
    for d, v in readings or []:
        pd = _parse_date(d)
        if pd is None or v is None:
            continue
        v = float(v)
        if nominal and v > float(nominal) * OVER_NOMINAL_TOL:
            discarded += 1
            continue
        clean.append((pd, v))
    if not clean:
        if discarded:
            # Hubo mediciones pero TODAS son imposibles: pedir revisión del dato
            return {"current": None, "last_date": None, "n_total": 0,
                    "n_segment": 0, "interventions": [], "rate_mm_yr": None,
                    "months_to_alarm": None, "months_to_scrap": None,
                    "scrap_date": None, "discarded": discarded,
                    "status": 'DATO_DUDOSO'}
        return None
    clean.sort(key=lambda x: x[0])

    # Intervenciones: subida de espesor = reparación/cambio de la pieza
    interventions = []
    seg_start = 0
    for i in range(1, len(clean)):
        if clean[i][1] - clean[i - 1][1] >= RENEWAL_JUMP_MM:
            interventions.append({
                "date": clean[i][0].isoformat(),
                "from_mm": round(clean[i - 1][1], 1),
                "to_mm": round(clean[i][1], 1),
            })
            seg_start = i
    segment = clean[seg_start:]

    last_date, current = segment[-1]
    out = {
        "current": round(current, 2),
        "last_date": last_date.isoformat(),
        "n_total": len(clean),
        "n_segment": len(segment),
        "interventions": interventions,
        "rate_mm_yr": None,
        "months_to_alarm": None,
        "months_to_scrap": None,
        "scrap_date": None,
        "discarded": discarded,
        "status": None,
    }

    # Tasa: regresión lineal por mínimos cuadrados sobre el segmento vigente
    rate = None
    span_days = (segment[-1][0] - segment[0][0]).days
    if len(segment) >= 2 and span_days >= MIN_SPAN_DAYS:
        xs = [(d - segment[0][0]).days for d, _ in segment]
        ys = [v for _, v in segment]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den > 0:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            rate = -slope * 365.25  # mm/año perdidos (positivo = desgaste)

    if rate is not None and rate > MIN_RATE_MM_YR:
        out["rate_mm_yr"] = round(rate, 2)
        m_scrap = max(0.0, (current - scrap) / rate * 12.0)
        m_alarm = max(0.0, (current - alarm) / rate * 12.0)
        out["months_to_scrap"] = round(m_scrap, 1)
        out["months_to_alarm"] = round(m_alarm, 1)
        out["scrap_date"] = (last_date + dt.timedelta(days=m_scrap * 30.44)).isoformat()

    # Estado (precedencia: ya bajo retiro > proyección > cerca de alarma > sin datos)
    if current <= scrap:
        out["status"] = 'CRITICO'
    elif out["rate_mm_yr"] is not None:
        m = out["months_to_scrap"]
        out["status"] = 'ROJO' if m < RED_MONTHS else ('AMBAR' if m < AMBER_MONTHS else 'VERDE')
    elif current <= alarm:
        out["status"] = 'AMBAR'
    elif rate is None:
        out["status"] = 'SIN_TENDENCIA'
    else:
        out["status"] = 'ESTABLE'
    return out


def register_thickness_predictive_routes(app, db, logger,
                                         ThicknessPoint, ThicknessInspection,
                                         ThicknessReading, Equipment):

    def _load_equipment_data(equipment_id=None):
        """Carga puntos + lecturas (con fecha de campaña) en bloque.

        Devuelve dict equipment_id -> {equipment, points: {point_id: {point, readings}}}
        """
        from sqlalchemy import text as sql_text
        params = {}
        eq_filter = ""
        if equipment_id:
            eq_filter = "AND p.equipment_id = :eq"
            params["eq"] = equipment_id
        rows = db.session.execute(sql_text(f"""
            SELECT p.equipment_id, p.id, p.group_name, p.section, p.position,
                   p.nominal_thickness, p.alarm_thickness, p.scrap_thickness,
                   i.inspection_date, r.value_mm
            FROM thickness_points p
            LEFT JOIN thickness_readings r ON r.point_id = p.id
            LEFT JOIN thickness_inspections i
                   ON i.id = r.inspection_id AND i.status = 'COMPLETA'
            WHERE p.is_active = TRUE {eq_filter}
            ORDER BY p.equipment_id, p.group_name, p.section, p.order_index
        """), params).fetchall()

        data = {}
        for (eq_id, pid, group, section, position,
             nominal, alarm, scrap, insp_date, value) in rows:
            eq = data.setdefault(eq_id, {"points": {}})
            pt = eq["points"].setdefault(pid, {
                "point_id": pid, "group_name": group, "section": section,
                "position": position, "nominal": nominal,
                "alarm": alarm, "scrap": scrap, "readings": [],
            })
            if insp_date is not None and value is not None:
                pt["readings"].append((insp_date, value))
        return data

    def _campaigns_info(equipment_id):
        insps = ThicknessInspection.query.filter_by(
            equipment_id=equipment_id, status='COMPLETA').all()
        dates = sorted({i.inspection_date for i in insps if i.inspection_date})
        return len(dates), (dates[-1] if dates else None)

    def _analyze_equipment(eq_id, eq_data):
        """Corre el forecast de todos los puntos de un equipo y agrega."""
        points_out = []
        for pt in eq_data["points"].values():
            fc = compute_point_forecast(pt["readings"], pt["alarm"], pt["scrap"],
                                        nominal=pt["nominal"])
            row = {k: pt[k] for k in ("point_id", "group_name", "section",
                                      "position", "nominal", "alarm", "scrap")}
            if fc:
                row.update(fc)
            else:
                row.update({"status": None, "current": None, "n_total": 0})
            points_out.append(row)

        with_status = [p for p in points_out if p.get("status")]
        counts = {}
        for p in with_status:
            counts[p["status"]] = counts.get(p["status"], 0) + 1

        # Peor punto: primero por severidad, luego por meses restantes
        def _sort_key(p):
            sev = SEVERITY.get(p.get("status"), 9)
            months = p.get("months_to_scrap")
            return (sev, months if months is not None else 9999)
        with_status.sort(key=_sort_key)
        worst = with_status[0] if with_status else None

        semaforo = worst["status"] if worst else 'SIN_DATOS'
        interventions = sum(len(p.get("interventions") or []) for p in points_out)
        return points_out, counts, worst, semaforo, interventions

    # ── Página ─────────────────────────────────────────────────────────────
    @app.route('/espesores/predictivo')
    def thickness_predictive_page():
        return render_template('thickness_predictive.html')

    # ── Resumen: todos los equipos con puntos de espesor ───────────────────
    @app.route('/api/thickness/predictive/summary', methods=['GET'])
    def thickness_predictive_summary():
        try:
            data = _load_equipment_data()
            eq_map = {e.id: e for e in Equipment.query.filter(
                Equipment.id.in_(list(data.keys()))).all()} if data else {}
            out = []
            for eq_id, eq_data in data.items():
                eq = eq_map.get(eq_id)
                points, counts, worst, semaforo, n_interv = _analyze_equipment(eq_id, eq_data)
                n_campaigns, last_date = _campaigns_info(eq_id)
                measured = [p for p in points if p.get("n_total")]
                with_rate = [p for p in points if p.get("rate_mm_yr")]
                out.append({
                    "equipment_id": eq_id,
                    "tag": eq.tag if eq else None,
                    "name": eq.name if eq else f"Equipo {eq_id}",
                    "campaigns": n_campaigns,
                    "last_inspection": last_date,
                    "points_total": len(points),
                    "points_measured": len(measured),
                    "points_with_rate": len(with_rate),
                    "status_counts": counts,
                    "interventions": n_interv,
                    "semaforo": semaforo,
                    "worst": ({
                        "group_name": worst["group_name"],
                        "position": worst["position"],
                        "section": worst["section"],
                        "current": worst.get("current"),
                        "scrap": worst.get("scrap"),
                        "rate_mm_yr": worst.get("rate_mm_yr"),
                        "months_to_scrap": worst.get("months_to_scrap"),
                        "scrap_date": worst.get("scrap_date"),
                        "status": worst.get("status"),
                    } if worst else None),
                })
            out.sort(key=lambda e: (SEVERITY.get(e["semaforo"], 8),
                                    -(e["campaigns"] or 0)))
            return jsonify(out)
        except Exception as e:
            logger.exception('thickness predictive summary error')
            return jsonify({"error": str(e)}), 500

    # ── Detalle por equipo: zonas y puntos ─────────────────────────────────
    @app.route('/api/thickness/predictive/<int:equipment_id>', methods=['GET'])
    def thickness_predictive_detail(equipment_id):
        try:
            eq = Equipment.query.get(equipment_id)
            if not eq:
                return jsonify({"error": "Equipo no encontrado"}), 404
            data = _load_equipment_data(equipment_id)
            if equipment_id not in data:
                return jsonify({"error": "El equipo no tiene puntos de espesor"}), 404
            points, counts, worst, semaforo, n_interv = _analyze_equipment(
                equipment_id, data[equipment_id])
            n_campaigns, last_date = _campaigns_info(equipment_id)

            zones = {}
            for p in points:
                zones.setdefault(p["group_name"], []).append(p)
            zones_out = []
            for group, pts in zones.items():
                pts.sort(key=lambda p: (SEVERITY.get(p.get("status"), 9),
                                        p.get("months_to_scrap") if p.get("months_to_scrap") is not None else 9999))
                zworst = next((p for p in pts if p.get("status")), None)
                zones_out.append({
                    "group_name": group,
                    "points": pts,
                    "worst_status": zworst.get("status") if zworst else None,
                    "worst_months": zworst.get("months_to_scrap") if zworst else None,
                })
            zones_out.sort(key=lambda z: SEVERITY.get(z["worst_status"], 9))

            return jsonify({
                "equipment_id": equipment_id,
                "tag": eq.tag, "name": eq.name,
                "campaigns": n_campaigns, "last_inspection": last_date,
                "semaforo": semaforo, "status_counts": counts,
                "interventions": n_interv, "zones": zones_out,
                "params": {"red_months": RED_MONTHS, "amber_months": AMBER_MONTHS,
                           "renewal_jump_mm": RENEWAL_JUMP_MM},
            })
        except Exception as e:
            logger.exception('thickness predictive detail error')
            return jsonify({"error": str(e)}), 500

    # ── Análisis narrativo IA (DeepSeek) ───────────────────────────────────
    def _narrative_llm(summary_text):
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            return None
        prompt = (
            "Eres un ingeniero de confiabilidad de una planta de harina proteica. "
            "Recibes la proyección de desgaste (espesores UT) de un digestor que opera a 3 bar y 120 °C "
            "con fuerte abrasión. Redacta un análisis ejecutivo BREVE en español (max 250 palabras) para el "
            "jefe de mantenimiento: 1) estado general, 2) zonas que exigen acción y cuándo (usa las fechas "
            "proyectadas), 3) recomendación concreta para la próxima parada. Tono directo, sin relleno. "
            "Si hay puntos ya bajo el espesor de retiro, dilo primero y con urgencia."
        )
        try:
            r = requests.post(DEEPSEEK_URL, headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }, json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': summary_text},
                ],
                'max_tokens': 700, 'temperature': 0.3,
            }, timeout=90)
            if r.status_code != 200:
                logger.error(f"narrativa espesores HTTP {r.status_code}: {r.text[:200]}")
                return None
            return r.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.error(f"narrativa espesores error: {e}")
            return None

    @app.route('/api/thickness/predictive/<int:equipment_id>/narrative', methods=['POST'])
    def thickness_predictive_narrative(equipment_id):
        try:
            eq = Equipment.query.get(equipment_id)
            if not eq:
                return jsonify({"error": "Equipo no encontrado"}), 404
            data = _load_equipment_data(equipment_id)
            if equipment_id not in data:
                return jsonify({"error": "Sin puntos de espesor"}), 404
            points, counts, worst, semaforo, n_interv = _analyze_equipment(
                equipment_id, data[equipment_id])

            lines = [f"EQUIPO: [{eq.tag}] {eq.name} — semáforo {semaforo}",
                     f"Conteo por estado: {counts}"]
            ranked = sorted([p for p in points if p.get("status")],
                            key=lambda p: (SEVERITY.get(p["status"], 9),
                                           p.get("months_to_scrap") if p.get("months_to_scrap") is not None else 9999))
            for p in ranked[:15]:
                seg = f" sec {p['section']}" if p.get('section') else ""
                extra = ""
                if p.get("rate_mm_yr"):
                    extra = (f" tasa {p['rate_mm_yr']} mm/año, llega al retiro en "
                             f"{p['months_to_scrap']} meses ({p.get('scrap_date')})")
                if p.get("interventions"):
                    extra += f" [reemplazada el {p['interventions'][-1]['date']}]"
                lines.append(f"- {p['group_name']}{seg} {p['position']}: {p.get('current')} mm "
                             f"(retiro {p['scrap']}) estado {p['status']}.{extra}")
            text = '\n'.join(lines)

            narrative = _narrative_llm(text)
            if not narrative:
                return jsonify({"error": "IA no disponible (falta DEEPSEEK_API_KEY o error de red)"}), 503
            return jsonify({"narrative": narrative})
        except Exception as e:
            logger.exception('thickness predictive narrative error')
            return jsonify({"error": str(e)}), 500
