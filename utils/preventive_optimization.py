"""Optimización del plan preventivo.

Analiza cada punto preventivo (lub/insp/mon) contra el historial de OTs
correctivas del mismo equipo/sistema/componente y recomienda:

  - Sobre-mantenimiento: muchas ejecuciones sin fallas → alargar intervalo
  - Sub-mantenimiento: muchas fallas con pocas ejecuciones → acortar intervalo
  - Normal: ratio balanceado, sin cambios

La lógica es pura (no depende de Flask). Recibe modelos como argumentos.
"""
import datetime as dt
from collections import defaultdict


def _date_in_window(date_str, cutoff_iso):
    """True si la fecha (YYYY-MM-DD) es >= cutoff."""
    if not date_str:
        return False
    return str(date_str)[:10] >= cutoff_iso


def analyze_preventive_plan(
    LubricationPoint, LubricationExecution,
    InspectionRoute, InspectionExecution,
    MonitoringPoint, MonitoringReading,
    WorkOrder,
    *,
    window_days=90,
    min_executions_over=3,
    min_failures_under=2,
):
    """Analiza todos los puntos activos y devuelve lista de recomendaciones.

    Args:
        window_days: ventana de análisis (default 90 días)
        min_executions_over: umbral mínimo para sobre-mantenimiento
        min_failures_under: umbral mínimo para sub-mantenimiento

    Returns:
        dict con:
          - 'recommendations': lista de recomendaciones
          - 'summary': {'over': N, 'under': N, 'normal': N, 'total_active': N}
          - 'window_days', 'cutoff_date'
    """
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=window_days)
    cutoff_iso = cutoff.isoformat()

    # ── 1. Cargar OTs correctivas cerradas en la ventana ────────────────────
    corrective_ots = WorkOrder.query.filter(
        WorkOrder.status == 'Cerrada',
    ).all()
    corr_in_window = [
        ot for ot in corrective_ots
        if (ot.maintenance_type or '').lower().startswith('corr')
        and _date_in_window(ot.real_end_date or ot.scheduled_date, cutoff_iso)
    ]

    # Indexar por (equipment_id, system_id, component_id) para lookup rápido
    corr_by_equip = defaultdict(list)
    corr_by_sys = defaultdict(list)
    corr_by_comp = defaultdict(list)
    for ot in corr_in_window:
        if ot.equipment_id:
            corr_by_equip[ot.equipment_id].append(ot)
        if ot.system_id:
            corr_by_sys[ot.system_id].append(ot)
        if ot.component_id:
            corr_by_comp[ot.component_id].append(ot)

    def _related_failures(point):
        """Cuenta OTs correctivas del mismo componente/sistema/equipo.
        Algunos tipos de punto (InspectionRoute) solo tienen equipment_id, asi
        que usamos getattr para tolerar atributos ausentes.
        """
        seen = set()
        comp_id = getattr(point, 'component_id', None)
        sys_id = getattr(point, 'system_id', None)
        eq_id = getattr(point, 'equipment_id', None)
        if comp_id:
            for ot in corr_by_comp.get(comp_id, []):
                seen.add(ot.id)
        if sys_id:
            for ot in corr_by_sys.get(sys_id, []):
                seen.add(ot.id)
        if eq_id:
            for ot in corr_by_equip.get(eq_id, []):
                seen.add(ot.id)
        return len(seen)

    # ── 2. Procesar cada tipo de punto ──────────────────────────────────────
    recommendations = []
    summary = {'over': 0, 'under': 0, 'normal': 0, 'insufficient_data': 0, 'total_active': 0}

    # 2a. Lubrication points
    lub_points = LubricationPoint.query.filter_by(is_active=True).all() if LubricationPoint else []
    lub_ids = [p.id for p in lub_points]
    lub_execs_by_point = defaultdict(list)
    if lub_ids:
        for e in LubricationExecution.query.filter(
            LubricationExecution.point_id.in_(lub_ids)
        ).all():
            lub_execs_by_point[e.point_id].append(e)

    for p in lub_points:
        summary['total_active'] += 1
        execs = [e for e in lub_execs_by_point.get(p.id, [])
                 if _date_in_window(e.execution_date, cutoff_iso)]
        execs_count = len(execs)
        failures = _related_failures(p)
        rec = _build_recommendation(
            p, 'lubrication', execs_count, failures,
            min_executions_over, min_failures_under,
            point_label=p.name or p.code or f"LUB-{p.id}",
        )
        if rec:
            recommendations.append(rec)
            summary[rec['category']] += 1

    # 2b. Inspection routes
    insp_routes = InspectionRoute.query.filter_by(is_active=True).all() if InspectionRoute else []
    insp_ids = [r.id for r in insp_routes]
    insp_execs_by_route = defaultdict(list)
    if insp_ids:
        for e in InspectionExecution.query.filter(
            InspectionExecution.route_id.in_(insp_ids)
        ).all():
            insp_execs_by_route[e.route_id].append(e)

    for r in insp_routes:
        summary['total_active'] += 1
        execs = [e for e in insp_execs_by_route.get(r.id, [])
                 if _date_in_window(e.execution_date, cutoff_iso)]
        execs_count = len(execs)
        failures = _related_failures(r)
        rec = _build_recommendation(
            r, 'inspection', execs_count, failures,
            min_executions_over, min_failures_under,
            point_label=r.name or r.code or f"INSP-{r.id}",
        )
        if rec:
            recommendations.append(rec)
            summary[rec['category']] += 1

    # 2c. Monitoring points
    mon_points = MonitoringPoint.query.filter_by(is_active=True).all() if MonitoringPoint else []
    mon_ids = [p.id for p in mon_points]
    mon_reads_by_point = defaultdict(list)
    if mon_ids:
        for r in MonitoringReading.query.filter(
            MonitoringReading.point_id.in_(mon_ids)
        ).all():
            mon_reads_by_point[r.point_id].append(r)

    for p in mon_points:
        summary['total_active'] += 1
        reads = [r for r in mon_reads_by_point.get(p.id, [])
                 if _date_in_window(r.reading_date, cutoff_iso)]
        execs_count = len(reads)
        failures = _related_failures(p)
        rec = _build_recommendation(
            p, 'monitoring', execs_count, failures,
            min_executions_over, min_failures_under,
            point_label=p.name or p.code or f"MON-{p.id}",
        )
        if rec:
            recommendations.append(rec)
            summary[rec['category']] += 1

    # ── 3. Ordenar por impacto: sub-mantenidos primero, luego sobre ─────────
    priority_order = {'under': 0, 'over': 1, 'normal': 2, 'insufficient_data': 3}
    recommendations.sort(key=lambda r: (
        priority_order.get(r['category'], 9),
        -r.get('failures_in_window', 0),
        -r.get('executions_in_window', 0),
    ))

    return {
        'recommendations': recommendations,
        'summary': summary,
        'window_days': window_days,
        'cutoff_date': cutoff_iso,
        'analyzed_at': dt.datetime.now().isoformat(),
    }


def _build_recommendation(
    point, source_type, execs_count, failures_count,
    min_executions_over, min_failures_under,
    point_label,
):
    """Clasifica el punto y genera recomendación si aplica."""
    current_freq = point.frequency_days or 0

    base = {
        'source_type': source_type,
        'source_id': point.id,
        'code': getattr(point, 'code', None) or '',
        'name': point_label,
        'equipment_id': getattr(point, 'equipment_id', None),
        'area_id': getattr(point, 'area_id', None),
        'current_frequency_days': current_freq,
        'executions_in_window': execs_count,
        'failures_in_window': failures_count,
        'last_execution': (
            getattr(point, 'last_service_date', None)
            or getattr(point, 'last_execution_date', None)
            or getattr(point, 'last_measurement_date', None)
            or '-'
        ),
    }

    # Sub-mantenimiento: muchas fallas + pocas ejecuciones
    if failures_count >= min_failures_under and execs_count < min_executions_over:
        new_freq = max(7, int(current_freq * 0.7)) if current_freq > 7 else current_freq
        reduction_pct = round((current_freq - new_freq) / current_freq * 100, 1) if current_freq else 0
        return {**base,
            'category': 'under',
            'severity': 'HIGH' if failures_count >= 3 else 'MEDIUM',
            'recommended_frequency_days': new_freq,
            'change_delta_days': new_freq - current_freq,
            'reduction_pct': reduction_pct,
            'reason': (
                f"{failures_count} fallas correctivas en ventana de análisis con "
                f"solo {execs_count} ejecuciones preventivas. Considerar acortar "
                f"intervalo y priorizar próxima ejecución."
            ),
            'action': f"Reducir frecuencia de {current_freq} → {new_freq} días",
        }

    # Sobre-mantenimiento: muchas ejecuciones + cero fallas
    if execs_count >= min_executions_over and failures_count == 0:
        new_freq = int(current_freq * 1.5) if current_freq > 0 else current_freq
        # Tope razonable: no más de 180 días
        new_freq = min(new_freq, 180)
        saving_pct = round((new_freq - current_freq) / current_freq * 100, 1) if current_freq else 0
        return {**base,
            'category': 'over',
            'severity': 'HIGH' if execs_count >= 5 else 'MEDIUM',
            'recommended_frequency_days': new_freq,
            'change_delta_days': new_freq - current_freq,
            'saving_pct': saving_pct,
            'reason': (
                f"{execs_count} ejecuciones preventivas sin ninguna falla correctiva "
                f"en ventana de análisis. Se puede alargar el intervalo sin aumentar "
                f"riesgo de falla."
            ),
            'action': f"Extender frecuencia de {current_freq} → {new_freq} días",
        }

    # Datos insuficientes (sin ejecuciones ni fallas en ventana)
    if execs_count == 0 and failures_count == 0:
        return {**base,
            'category': 'insufficient_data',
            'severity': 'INFO',
            'recommended_frequency_days': current_freq,
            'reason': "Sin ejecuciones ni fallas en la ventana de análisis. Espera más data histórica.",
            'action': 'Esperar más datos',
        }

    # Balanceado: ratio ejecuciones/fallas aceptable
    return {**base,
        'category': 'normal',
        'severity': 'OK',
        'recommended_frequency_days': current_freq,
        'reason': f"{execs_count} ejecuciones y {failures_count} fallas. Plan balanceado.",
        'action': 'Mantener frecuencia',
    }


def apply_recommendation(
    source_type, source_id, new_frequency_days,
    *, LubricationPoint, InspectionRoute, MonitoringPoint,
    db,
):
    """Aplica una recomendación cambiando la frecuencia del punto."""
    model_map = {
        'lubrication': LubricationPoint,
        'inspection': InspectionRoute,
        'monitoring': MonitoringPoint,
    }
    Model = model_map.get(source_type)
    if not Model:
        raise ValueError(f"source_type inválido: {source_type}")

    point = Model.query.get(source_id)
    if not point:
        raise ValueError(f"Punto {source_type}/{source_id} no existe")

    old_freq = point.frequency_days
    point.frequency_days = int(new_frequency_days)
    db.session.commit()

    return {
        'ok': True,
        'source_type': source_type,
        'source_id': source_id,
        'old_frequency_days': old_freq,
        'new_frequency_days': point.frequency_days,
    }
