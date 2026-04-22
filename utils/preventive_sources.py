"""Recolector unificado de puntos preventivos.

Centraliza la lógica que antes estaba duplicada en:
  - routes/work_orders_routes.py::generate_preventive_ots
  - routes/shutdown_routes.py::get_shutdown_preventive_sources

Exporta dos funciones principales:
  - build_description(source_type, obj): descripción estandarizada para la OT/Aviso
  - collect_sources(...): recolecta puntos de Lub/Insp/Mon con filtros

Los modelos se reciben como argumentos para evitar imports circulares.
"""


# ── Constructores de descripción ─────────────────────────────────────────────

def _lub_description(p):
    desc = f"[PREVENTIVO - LUBRICACION] {p.code or ''} {p.name or getattr(p, 'task_name', None) or ''}".strip()
    if p.lubricant_name:
        desc += f"\nLubricante: {p.lubricant_name}"
    if p.quantity_nominal:
        desc += f" | Cantidad: {p.quantity_nominal} {p.quantity_unit or 'L'}"
    desc += f"\nFrecuencia: cada {p.frequency_days} dias"
    if p.last_service_date:
        desc += f" | Ultimo servicio: {p.last_service_date}"
    return desc


def _insp_description(r):
    desc = f"[PREVENTIVO - INSPECCION] {r.code or ''} {r.name or ''}".strip()
    desc += f"\nFrecuencia: cada {r.frequency_days} dias"
    if r.last_execution_date:
        desc += f" | Ultima ejecucion: {r.last_execution_date}"
    # Checklist de items activos (primeros 8)
    if hasattr(r, 'items') and r.items:
        active_items = [i for i in r.items if i.is_active]
        if active_items:
            desc += "\nChecklist: " + " | ".join(
                f"{i.description}{' (' + i.unit + ')' if i.unit else ''}"
                for i in active_items[:8]
            )
    return desc


def _mon_description(p):
    desc = f"[PREVENTIVO - MONITOREO] {p.code or ''} {p.name or ''}".strip()
    if p.measurement_type:
        desc += f"\nTipo: {p.measurement_type}"
        if p.axis:
            desc += f" Eje: {p.axis}"
        desc += f" | Unidad: {p.unit or 'mm/s'}"
    if p.normal_min is not None or p.normal_max is not None:
        desc += f"\nRango normal: {p.normal_min or '-'} a {p.normal_max or '-'} {p.unit or ''}"
    if p.alarm_min is not None or p.alarm_max is not None:
        desc += f" | Alarma: {p.alarm_min or '-'} a {p.alarm_max or '-'}"
    desc += f"\nFrecuencia: cada {p.frequency_days} dias"
    if p.last_measurement_date:
        desc += f" | Ultima medicion: {p.last_measurement_date}"
    return desc


def build_description(source_type, obj):
    """Construye la descripción estándar para un punto preventivo."""
    if source_type == 'lubrication':
        return _lub_description(obj)
    if source_type == 'inspection':
        return _insp_description(obj)
    if source_type == 'monitoring':
        return _mon_description(obj)
    return ''


# ── Helpers de contexto jerárquico ───────────────────────────────────────────

def _resolve_area_id(point, line_map, equip_map):
    """Devuelve el area_id real del punto, subiendo por línea/equipo si hace falta."""
    if getattr(point, 'area_id', None):
        return point.area_id
    line_id = getattr(point, 'line_id', None)
    if line_id and line_id in line_map:
        return line_map[line_id].area_id
    equip_id = getattr(point, 'equipment_id', None)
    if equip_id and equip_id in equip_map:
        eq = equip_map[equip_id]
        if eq.line_id and eq.line_id in line_map:
            return line_map[eq.line_id].area_id
    return None


def _calc_semaphore(obj, source_type, _calc_lub, _calc_mon):
    """Calcula (o recupera) el semáforo actual del punto."""
    try:
        if source_type == 'lubrication' and _calc_lub:
            _, sem = _calc_lub(obj.last_service_date, obj.frequency_days, obj.warning_days)
            return sem
        if source_type == 'inspection' and _calc_lub:
            # Se usa el mismo calculador de fechas que lubricación (misma lógica)
            _, sem = _calc_lub(obj.last_execution_date, obj.frequency_days, obj.warning_days)
            return sem
        if source_type == 'monitoring' and _calc_mon:
            _, sem = _calc_mon(obj.last_measurement_date, obj.frequency_days, obj.warning_days)
            return sem
    except Exception:
        pass
    return getattr(obj, 'semaphore_status', 'VERDE') or 'VERDE'


# ── Función principal ────────────────────────────────────────────────────────

def collect_sources(
    LubricationPoint, InspectionRoute, MonitoringPoint,
    _calc_lub_schedule=None, _calc_mon_schedule=None,
    *,
    source_types=None,        # {'lubrication','inspection','monitoring'} o None (todas)
    area_ids=None,            # lista de area_ids para filtrar (None = todas)
    only_overdue=False,       # True → solo ROJO / AMARILLO
    exclude=None,             # set de tuplas (source_type, source_id) a omitir
    enrich_names=False,       # True → agrega area_name, line_name, equipment_tag/name
    area_map=None, line_map=None, equip_map=None,
):
    """Recolecta puntos preventivos lub/insp/mon con filtros.

    Retorna lista de dicts con estructura unificada:
        source_type, source_id, code, name, semaphore, frequency_days,
        next_due_date, last_execution,
        area_id, line_id, equipment_id, system_id, component_id,
        description,
        (si enrich_names=True) area_name, line_name, equipment_tag, equipment_name
    """
    if source_types is None:
        source_types = {'lubrication', 'inspection', 'monitoring'}
    exclude = exclude or set()

    # Mapas por defecto si no se pasan (permite reutilizar fuera)
    if line_map is None and enrich_names:
        from models import Line
        line_map = {l.id: l for l in Line.query.all()}
    if equip_map is None and enrich_names:
        from models import Equipment
        equip_map = {e.id: e for e in Equipment.query.all()}
    if area_map is None and enrich_names:
        from models import Area
        area_map = {a.id: a for a in Area.query.all()}
    line_map = line_map or {}
    equip_map = equip_map or {}
    area_map = area_map or {}

    def _should_include(semaphore):
        if not only_overdue:
            return True
        return semaphore in ('ROJO', 'AMARILLO')

    def _in_area(aid):
        if not area_ids:
            return True
        return aid in area_ids

    def _enrich(d, aid, line_id, eq_id):
        if not enrich_names:
            return d
        ln = line_map.get(line_id) if line_id else None
        if not ln and eq_id:
            eq = equip_map.get(eq_id)
            if eq and eq.line_id:
                ln = line_map.get(eq.line_id)
        eq = equip_map.get(eq_id) if eq_id else None
        ar = area_map.get(aid) if aid else None
        d['area_name'] = ar.name if ar else '-'
        d['line_name'] = ln.name if ln else '-'
        d['equipment_tag'] = eq.tag if eq else '-'
        d['equipment_name'] = eq.name if eq else '-'
        return d

    sources = []

    if 'lubrication' in source_types and LubricationPoint:
        for p in LubricationPoint.query.filter_by(is_active=True).all():
            sem = _calc_semaphore(p, 'lubrication', _calc_lub_schedule, _calc_mon_schedule)
            if not _should_include(sem):
                continue
            if ('lubrication', p.id) in exclude:
                continue
            aid = _resolve_area_id(p, line_map, equip_map)
            if not _in_area(aid):
                continue
            d = {
                'source_type': 'lubrication',
                'source_id': p.id,
                'code': p.code or '',
                'name': p.name or getattr(p, 'task_name', None) or '(sin nombre)',
                'semaphore': sem,
                'frequency_days': p.frequency_days,
                'next_due_date': p.next_due_date or '-',
                'last_execution': p.last_service_date or '-',
                'area_id': aid,
                'line_id': p.line_id or (equip_map.get(p.equipment_id).line_id if p.equipment_id and equip_map.get(p.equipment_id) else None),
                'equipment_id': p.equipment_id,
                'system_id': p.system_id,
                'component_id': p.component_id,
                'description': build_description('lubrication', p),
            }
            sources.append(_enrich(d, aid, d['line_id'], p.equipment_id))

    if 'inspection' in source_types and InspectionRoute:
        for r in InspectionRoute.query.filter_by(is_active=True).all():
            sem = _calc_semaphore(r, 'inspection', _calc_lub_schedule, _calc_mon_schedule)
            if not _should_include(sem):
                continue
            if ('inspection', r.id) in exclude:
                continue
            aid = _resolve_area_id(r, line_map, equip_map)
            if not _in_area(aid):
                continue
            d = {
                'source_type': 'inspection',
                'source_id': r.id,
                'code': r.code or '',
                'name': r.name or '(sin nombre)',
                'semaphore': sem,
                'frequency_days': r.frequency_days,
                'next_due_date': r.next_due_date or '-',
                'last_execution': r.last_execution_date or '-',
                'area_id': aid,
                'line_id': r.line_id or (equip_map.get(r.equipment_id).line_id if r.equipment_id and equip_map.get(r.equipment_id) else None),
                'equipment_id': r.equipment_id,
                'system_id': None,
                'component_id': None,
                'description': build_description('inspection', r),
            }
            sources.append(_enrich(d, aid, d['line_id'], r.equipment_id))

    if 'monitoring' in source_types and MonitoringPoint:
        for p in MonitoringPoint.query.filter_by(is_active=True).all():
            sem = _calc_semaphore(p, 'monitoring', _calc_lub_schedule, _calc_mon_schedule)
            if not _should_include(sem):
                continue
            if ('monitoring', p.id) in exclude:
                continue
            aid = _resolve_area_id(p, line_map, equip_map)
            if not _in_area(aid):
                continue
            d = {
                'source_type': 'monitoring',
                'source_id': p.id,
                'code': p.code or '',
                'name': p.name or '(sin nombre)',
                'semaphore': sem,
                'frequency_days': p.frequency_days,
                'next_due_date': p.next_due_date or '-',
                'last_execution': p.last_measurement_date or '-',
                'area_id': aid,
                'line_id': p.line_id or (equip_map.get(p.equipment_id).line_id if p.equipment_id and equip_map.get(p.equipment_id) else None),
                'equipment_id': p.equipment_id,
                'system_id': p.system_id,
                'component_id': p.component_id,
                'description': build_description('monitoring', p),
            }
            sources.append(_enrich(d, aid, d['line_id'], p.equipment_id))

    # Orden: ROJO primero, luego AMARILLO, luego VERDE
    sem_rank = {'ROJO': 0, 'AMARILLO': 1, 'VERDE': 2}
    sources.sort(key=lambda s: (sem_rank.get(s['semaphore'], 9), s['next_due_date'] or 'zzz'))
    return sources
