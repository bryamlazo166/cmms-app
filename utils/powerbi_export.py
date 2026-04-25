"""Power BI export — Excel master + JSON endpoint helpers.

Centraliza toda la logica de extraccion para Power BI en un solo
modulo. Consumido por routes/reports_routes.py:

- build_workbook() -> BytesIO con el Excel multi-hoja
- query_*(lookups) -> lista de dicts lista para jsonify o pd.DataFrame
- get_kpis() -> dict de indicadores resumidos
- list_endpoints() -> directorio para descubrimiento desde Power BI

Ningun query toca request/response: son funciones puras que reciben
SQLAlchemy session/models y devuelven datos. Esto facilita testing
y reutilizacion (por ejemplo para tareas programadas o scripts).
"""
from io import BytesIO


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────

def _build_lookups():
    """Precarga maps de referencia. Llamar una sola vez por request."""
    from models import (
        Area, Line, Equipment, System, Component, Technician, Provider,
        Shutdown, MaintenanceNotice, WorkOrder, WarehouseItem,
    )
    return {
        'areas':     {a.id: a for a in Area.query.all()},
        'lines':     {l.id: l for l in Line.query.all()},
        'equips':    {e.id: e for e in Equipment.query.all()},
        'systems':   {s.id: s for s in System.query.all()},
        'comps':     {c.id: c for c in Component.query.all()},
        'techs':     {t.id: t for t in Technician.query.all()},
        'provs':     {p.id: p for p in Provider.query.all()},
        'shutdowns': {s.id: s for s in Shutdown.query.all()},
        'notices':   {n.id: n for n in MaintenanceNotice.query.all()},
        'wos':       {o.id: o for o in WorkOrder.query.all()},
        'wh_items':  {w.id: w for w in WarehouseItem.query.all()},
    }


def _name(d, key):
    obj = d.get(key)
    return obj.name if obj else None


def _attr(d, key, attr):
    obj = d.get(key)
    return getattr(obj, attr, None) if obj else None


def _yn(b):
    return 'Si' if b else 'No'


def _safe_duration_hours(value):
    """Replicates the helper from app.py — robust parser of duration."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ────────────────────────────────────────────────────────────────
# Domain queries — devuelven listas de dicts
# ────────────────────────────────────────────────────────────────

def query_work_orders(lookups):
    """Ordenes de Trabajo enriquecidas con jerarquia, aviso vinculado
    y datos de parada (shutdown)."""
    from models import WorkOrder
    from datetime import datetime

    rows = []
    for o in WorkOrder.query.order_by(WorkOrder.id).all():
        eq = lookups['equips'].get(o.equipment_id)
        sh = lookups['shutdowns'].get(getattr(o, 'shutdown_id', None))
        nt = lookups['notices'].get(o.notice_id) if o.notice_id else None

        duration_h = _safe_duration_hours(o.real_duration)
        # On-time flag
        on_time = None
        if o.scheduled_date and o.real_end_date:
            try:
                sched = datetime.fromisoformat(str(o.scheduled_date)[:10]).date()
                rend = datetime.fromisoformat(str(o.real_end_date)[:10]).date()
                on_time = 'Si' if rend <= sched else 'No'
            except Exception:
                on_time = None
        elif o.scheduled_date and o.status == 'Cerrada' and not o.real_end_date:
            on_time = 'Sin fecha cierre'

        rows.append({
            'Codigo_OT': o.code,
            'Codigo_Aviso': nt.code if nt else None,
            'Aviso_ID': o.notice_id,
            'Estado': o.status,
            'Tipo_Mantenimiento': o.maintenance_type,
            'Modo_Falla': o.failure_mode,
            'Descripcion': o.description,
            'Prioridad': getattr(o, 'priority', None),
            'Area': _name(lookups['areas'], o.area_id),
            'Linea': _name(lookups['lines'], o.line_id),
            'Equipo': eq.name if eq else None,
            'TAG': eq.tag if eq else None,
            'Criticidad_Equipo': eq.criticality if eq else None,
            'Sistema': _name(lookups['systems'], o.system_id),
            'Componente': _name(lookups['comps'], o.component_id),
            'Tecnico': _name(lookups['techs'], _safe_int(o.technician_id)),
            'Proveedor': _name(lookups['provs'], o.provider_id),
            'Fecha_Programada': o.scheduled_date,
            'Fecha_Inicio_Real': o.real_start_date,
            'Fecha_Fin_Real': o.real_end_date,
            'Duracion_Horas': duration_h,
            'Duracion_Estimada': o.estimated_duration,
            'Cant_Tecnicos': o.tech_count,
            'A_Tiempo': on_time,
            'Comentarios_Ejecucion': o.execution_comments,
            'Causo_Parada': _yn(getattr(o, 'caused_downtime', False)),
            'Horas_Parada': getattr(o, 'downtime_hours', None),
            'Origen_Tipo': getattr(o, 'source_type', None),
            'Origen_ID': getattr(o, 'source_id', None),
            'Parada_ID': getattr(o, 'shutdown_id', None),
            'Parada_Codigo': sh.code if sh else None,
            'Parada_Fecha': sh.shutdown_date if sh else None,
            'Reporte_Requerido': _yn(getattr(o, 'report_required', False)),
            'Reporte_Estado': getattr(o, 'report_status', None),
            'Reporte_Fecha_Limite': getattr(o, 'report_due_date', None),
        })
    return rows


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def query_notices(lookups):
    """Avisos enriquecidos con scope, free_location, failure_*, etc."""
    from models import MaintenanceNotice
    from datetime import datetime

    rows = []
    for n in MaintenanceNotice.query.order_by(MaintenanceNotice.id).all():
        eq = lookups['equips'].get(n.equipment_id)

        # Dias de respuesta (request -> treatment)
        response_days = None
        try:
            if n.request_date and n.treatment_date:
                req = datetime.fromisoformat(str(n.request_date)[:10]).date()
                tre = datetime.fromisoformat(str(n.treatment_date)[:10]).date()
                response_days = (tre - req).days
        except Exception:
            pass

        # Dias hasta cierre
        days_to_close = None
        try:
            if n.request_date and getattr(n, 'closed_date', None):
                req = datetime.fromisoformat(str(n.request_date)[:10]).date()
                clo = datetime.fromisoformat(str(n.closed_date)[:10]).date()
                days_to_close = (clo - req).days
        except Exception:
            pass

        rows.append({
            'Codigo_Aviso': n.code,
            'Estado': n.status,
            'Alcance': getattr(n, 'scope', 'PLAN'),
            'Tipo_Mantenimiento': n.maintenance_type,
            'Descripcion': n.description,
            'Prioridad': n.priority,
            'Criticidad': n.criticality,
            'Modo_Falla': getattr(n, 'failure_mode', None),
            'Categoria_Falla': getattr(n, 'failure_category', None),
            'Objeto_Bloqueo': getattr(n, 'blockage_object', None),
            'Especialidad': n.specialty,
            'Turno': n.shift,
            'Reportado_Por': n.reporter_name,
            'Tipo_Reportante': n.reporter_type,
            'Area': _name(lookups['areas'], n.area_id),
            'Linea': _name(lookups['lines'], n.line_id),
            'Equipo': eq.name if eq else None,
            'TAG': eq.tag if eq else None,
            'Sistema': _name(lookups['systems'], n.system_id),
            'Componente': _name(lookups['comps'], n.component_id),
            'Ubicacion_Libre': getattr(n, 'free_location', None),
            'Fecha_Solicitud': n.request_date,
            'Fecha_Tratamiento': n.treatment_date,
            'Fecha_Planificacion': n.planning_date,
            'Fecha_Cierre': getattr(n, 'closed_date', None),
            'Dias_Respuesta': response_days,
            'Dias_Hasta_Cierre': days_to_close,
            'OT_Asociada': n.ot_number,
            'Motivo_Cancelacion': n.cancellation_reason,
            'Origen_Tipo': getattr(n, 'source_type', None),
            'Origen_ID': getattr(n, 'source_id', None),
        })
    return rows


def query_ot_personnel(lookups):
    from models import OTPersonnel
    rows = []
    for p in OTPersonnel.query.order_by(OTPersonnel.id).all():
        wo = lookups['wos'].get(p.work_order_id)
        rows.append({
            'Codigo_OT': wo.code if wo else None,
            'OT_ID': p.work_order_id,
            'Tecnico': _name(lookups['techs'], p.technician_id),
            'Especialidad': p.specialty,
            'Horas_Asignadas': p.hours_assigned,
            'Horas_Trabajadas': p.hours_worked,
        })
    return rows


def query_ot_materials(lookups):
    from models import OTMaterial
    rows = []
    for m in OTMaterial.query.order_by(OTMaterial.id).all():
        wo = lookups['wos'].get(m.work_order_id)
        item_name = m.item_name_free or '-'
        item_code = '-'
        unit_cost = 0
        if m.item_type == 'warehouse':
            wi = lookups['wh_items'].get(m.item_id)
            if wi:
                item_name = item_name if item_name and item_name != '-' else wi.name
                item_code = wi.code or '-'
                unit_cost = wi.unit_cost or 0
        rows.append({
            'Codigo_OT': wo.code if wo else None,
            'OT_ID': m.work_order_id,
            'Tipo_Item': m.item_type,
            'Subtipo': getattr(m, 'subtype', None),
            'Codigo_Item': item_code,
            'Nombre_Item': item_name,
            'Cantidad': m.quantity,
            'Unidad': getattr(m, 'unit', None),
            'Costo_Unitario': unit_cost,
            'Costo_Total': round((m.quantity or 0) * (unit_cost or 0), 2),
            'Instalado': _yn(getattr(m, 'is_installed', True)),
        })
    return rows


def query_ot_log_entries(lookups):
    """Bitacora de OTs."""
    try:
        from models import OTLogEntry
    except ImportError:
        return []
    rows = []
    for e in OTLogEntry.query.order_by(OTLogEntry.id.desc()).all():
        wo = lookups['wos'].get(e.work_order_id)
        rows.append({
            'Codigo_OT': wo.code if wo else f'OT-{e.work_order_id}',
            'OT_ID': e.work_order_id,
            'Fecha': getattr(e, 'log_date', None) or getattr(e, 'entry_date', None),
            'Tipo': getattr(e, 'log_type', None) or getattr(e, 'entry_type', None),
            'Autor': getattr(e, 'author', None),
            'Comentario': getattr(e, 'comment', None),
            'Creado': e.created_at.isoformat() if e.created_at else None,
        })
    return rows


def query_lubrication_points(lookups):
    from models import LubricationPoint
    rows = []
    for p in LubricationPoint.query.order_by(LubricationPoint.id).all():
        eq = lookups['equips'].get(p.equipment_id)
        rows.append({
            'Codigo': p.code,
            'Nombre': p.name,
            'Activo': _yn(p.is_active),
            'Area': _name(lookups['areas'], p.area_id),
            'Linea': _name(lookups['lines'], p.line_id),
            'Equipo': eq.name if eq else None,
            'TAG': eq.tag if eq else None,
            'Sistema': _name(lookups['systems'], p.system_id),
            'Componente': _name(lookups['comps'], p.component_id),
            'Lubricante': p.lubricant_name,
            'Cantidad_Nominal': p.quantity_nominal,
            'Unidad': p.quantity_unit,
            'Frecuencia_Dias': p.frequency_days,
            'Ultimo_Servicio': p.last_service_date,
            'Proximo_Vencimiento': p.next_due_date,
            'Semaforo': p.semaphore_status,
        })
    return rows


def query_lubrication_executions(lookups):
    from models import LubricationExecution, LubricationPoint
    point_map = {p.id: p for p in LubricationPoint.query.all()}
    rows = []
    for e in LubricationExecution.query.order_by(LubricationExecution.id).all():
        p = point_map.get(e.point_id)
        eq = lookups['equips'].get(p.equipment_id) if p else None
        rows.append({
            'Codigo_Punto': p.code if p else None,
            'Nombre_Punto': p.name if p else None,
            'TAG': eq.tag if eq else None,
            'Equipo': eq.name if eq else None,
            'Area': _name(lookups['areas'], p.area_id) if p else None,
            'Fecha_Ejecucion': e.execution_date,
            'Accion': e.action_type,
            'Cantidad': e.quantity_used,
            'Unidad': e.quantity_unit,
            'Ejecutado_Por': e.executed_by,
            'Fuga_Detectada': _yn(e.leak_detected),
            'Anomalia': _yn(e.anomaly_detected),
            'Comentario': e.comments,
            'Aviso_Generado_ID': e.created_notice_id,
        })
    return rows


def query_monitoring_points(lookups):
    from models import MonitoringPoint
    rows = []
    for p in MonitoringPoint.query.order_by(MonitoringPoint.id).all():
        eq = lookups['equips'].get(p.equipment_id)
        rows.append({
            'Codigo': p.code,
            'Nombre': p.name,
            'Activo': _yn(p.is_active),
            'Tipo_Medicion': p.measurement_type,
            'Eje': p.axis,
            'Unidad': p.unit,
            'Area': _name(lookups['areas'], p.area_id),
            'Linea': _name(lookups['lines'], p.line_id),
            'Equipo': eq.name if eq else None,
            'TAG': eq.tag if eq else None,
            'Sistema': _name(lookups['systems'], p.system_id),
            'Componente': _name(lookups['comps'], p.component_id),
            'Normal_Min': p.normal_min,
            'Normal_Max': p.normal_max,
            'Alarma_Min': p.alarm_min,
            'Alarma_Max': p.alarm_max,
            'Frecuencia_Dias': p.frequency_days,
            'Ultima_Medicion': p.last_measurement_date,
            'Proximo_Vencimiento': p.next_due_date,
            'Semaforo': p.semaphore_status,
        })
    return rows


def query_monitoring_readings(lookups):
    from models import MonitoringReading, MonitoringPoint
    point_map = {p.id: p for p in MonitoringPoint.query.all()}
    rows = []
    for r in MonitoringReading.query.order_by(MonitoringReading.id).all():
        p = point_map.get(r.point_id)
        eq = lookups['equips'].get(p.equipment_id) if p else None
        rows.append({
            'Codigo_Punto': p.code if p else None,
            'Nombre_Punto': p.name if p else None,
            'TAG': eq.tag if eq else None,
            'Equipo': eq.name if eq else None,
            'Fecha_Lectura': r.reading_date,
            'Valor': r.value,
            'Unidad': p.unit if p else None,
            'Ejecutado_Por': r.executed_by,
            'Regularizacion': _yn(r.is_regularization),
            'Notas': r.notes,
            'Aviso_Generado_ID': r.created_notice_id,
        })
    return rows


def query_inspection_routes(lookups):
    from models import InspectionRoute
    rows = []
    for r in InspectionRoute.query.order_by(InspectionRoute.id).all():
        eq = lookups['equips'].get(r.equipment_id)
        rows.append({
            'Codigo': r.code,
            'Nombre': r.name,
            'Descripcion': r.description,
            'Activa': _yn(r.is_active),
            'Area': _name(lookups['areas'], r.area_id),
            'Linea': _name(lookups['lines'], r.line_id),
            'Equipo': eq.name if eq else None,
            'TAG': eq.tag if eq else None,
            'Frecuencia_Dias': r.frequency_days,
            'Ultima_Ejecucion': r.last_execution_date,
            'Proximo_Vencimiento': r.next_due_date,
            'Semaforo': r.semaphore_status,
        })
    return rows


def query_inspection_executions(lookups):
    """Una fila por resultado de item (no agregado por ejecucion)."""
    from models import InspectionExecution, InspectionResult, InspectionRoute, InspectionItem
    route_map = {r.id: r for r in InspectionRoute.query.all()}
    item_map = {i.id: i for i in InspectionItem.query.all()}
    rows = []
    for e in InspectionExecution.query.order_by(InspectionExecution.id).all():
        r = route_map.get(e.route_id)
        eq = lookups['equips'].get(r.equipment_id) if r else None
        results = InspectionResult.query.filter_by(execution_id=e.id).all()
        if not results:
            rows.append({
                'Codigo_Ruta': r.code if r else None,
                'Nombre_Ruta': r.name if r else None,
                'TAG': eq.tag if eq else None,
                'Equipo': eq.name if eq else None,
                'Fecha_Ejecucion': e.execution_date,
                'Inspector': e.executed_by,
                'Resultado_General': e.overall_result,
                'Hallazgos': e.findings_count,
                'Item': None, 'Tipo_Item': None, 'Resultado_Item': None,
                'Valor': None, 'Texto': None, 'Observacion': None,
                'Aviso_Generado_ID': e.created_notice_id,
                'Comentario': e.comments,
            })
        else:
            for res in results:
                it = item_map.get(res.item_id)
                rows.append({
                    'Codigo_Ruta': r.code if r else None,
                    'Nombre_Ruta': r.name if r else None,
                    'TAG': eq.tag if eq else None,
                    'Equipo': eq.name if eq else None,
                    'Fecha_Ejecucion': e.execution_date,
                    'Inspector': e.executed_by,
                    'Resultado_General': e.overall_result,
                    'Hallazgos': e.findings_count,
                    'Item': it.description if it else None,
                    'Tipo_Item': it.item_type if it else None,
                    'Resultado_Item': res.result,
                    'Valor': res.value,
                    'Texto': res.text_value,
                    'Observacion': res.observation,
                    'Aviso_Generado_ID': e.created_notice_id,
                    'Comentario': e.comments,
                })
    return rows


def query_thickness(lookups):
    """Inspecciones de espesores con lecturas planas (1 fila por punto)."""
    try:
        from models import ThicknessInspection, ThicknessPoint, ThicknessReading
    except ImportError:
        return []
    point_map = {p.id: p for p in ThicknessPoint.query.all()}
    rows = []
    for ins in ThicknessInspection.query.order_by(ThicknessInspection.id).all():
        readings = ThicknessReading.query.filter_by(inspection_id=ins.id).all()
        eq = lookups['equips'].get(ins.equipment_id)
        # Linea/Area derivadas del equipo
        line = lookups['lines'].get(eq.line_id) if eq else None
        area = lookups['areas'].get(line.area_id) if line else None

        if not readings:
            rows.append({
                'Inspeccion_ID': ins.id,
                'Fecha_Inspeccion': ins.inspection_date,
                'Proxima_Inspeccion': ins.next_due_date,
                'Inspector': ins.inspector_name,
                'Estado_Inspeccion': ins.status,
                'Semaforo': ins.semaphore_status,
                'Total_Puntos': ins.total_points,
                'Puntos_Criticos': ins.critical_points,
                'Puntos_Alerta': ins.alert_points,
                'Equipo': eq.name if eq else None,
                'TAG': eq.tag if eq else None,
                'Area': area.name if area else None,
                'Linea': line.name if line else None,
                'Observaciones': ins.observations,
                'PDF_URL': ins.pdf_url,
                'Punto_Grupo': None, 'Punto_Posicion': None,
                'Espesor_mm': None, 'Espesor_Nominal_mm': None,
                'Espesor_Alarma_mm': None, 'Espesor_Scrap_mm': None,
                'Desgaste_mm': None, 'Estado_Punto': None,
            })
            continue
        for rd in readings:
            pt = point_map.get(rd.point_id)
            nominal = getattr(pt, 'nominal_thickness', None) if pt else None
            current = rd.value
            wear = (nominal - current) if (nominal is not None and current is not None) else None
            rows.append({
                'Inspeccion_ID': ins.id,
                'Fecha_Inspeccion': ins.inspection_date,
                'Proxima_Inspeccion': ins.next_due_date,
                'Inspector': ins.inspector_name,
                'Estado_Inspeccion': ins.status,
                'Semaforo': ins.semaphore_status,
                'Total_Puntos': ins.total_points,
                'Puntos_Criticos': ins.critical_points,
                'Puntos_Alerta': ins.alert_points,
                'Equipo': eq.name if eq else None,
                'TAG': eq.tag if eq else None,
                'Area': area.name if area else None,
                'Linea': line.name if line else None,
                'Observaciones': ins.observations,
                'PDF_URL': ins.pdf_url,
                'Punto_Grupo': pt.group_name if pt else None,
                'Punto_Posicion': pt.position if pt else None,
                'Espesor_mm': current,
                'Espesor_Nominal_mm': nominal,
                'Espesor_Alarma_mm': pt.alarm_thickness if pt else None,
                'Espesor_Scrap_mm': pt.scrap_thickness if pt else None,
                'Desgaste_mm': round(wear, 2) if wear is not None else None,
                'Estado_Punto': pt.status if pt else None,
            })
    return rows


def query_shutdowns(lookups):
    """Cabecera de paradas."""
    from models import Shutdown
    rows = []
    for s in Shutdown.query.order_by(Shutdown.id).all():
        # Areas afectadas (M2M via shutdown_areas)
        try:
            area_names = ', '.join(sa.area.name for sa in s.areas if sa.area)
        except Exception:
            area_names = None
        rows.append({
            'ID': s.id,
            'Codigo_Parada': s.code,
            'Nombre': s.name,
            'Tipo': s.shutdown_type,
            'Estado': s.status,
            'Fecha': s.shutdown_date,
            'Hora_Inicio': s.start_time,
            'Hora_Fin': s.end_time,
            'Areas_Afectadas': area_names,
            'Responsable': getattr(s, 'created_by', None),
            'Requerimientos_Produccion': getattr(s, 'production_requirements', None),
            'Observaciones': getattr(s, 'observations', None),
        })
    return rows


def query_shutdown_ots(lookups):
    """OTs ligadas a paradas — para cumplimiento por parada."""
    from models import WorkOrder
    rows = []
    for o in WorkOrder.query.filter(WorkOrder.shutdown_id.isnot(None)).order_by(WorkOrder.id).all():
        sh = lookups['shutdowns'].get(o.shutdown_id)
        eq = lookups['equips'].get(o.equipment_id)
        rows.append({
            'Parada_Codigo': sh.code if sh else None,
            'Parada_Nombre': sh.name if sh else None,
            'Parada_Fecha': sh.shutdown_date if sh else None,
            'Parada_Tipo': sh.shutdown_type if sh else None,
            'Codigo_OT': o.code,
            'Estado_OT': o.status,
            'Tipo_Mantenimiento': o.maintenance_type,
            'Area': _name(lookups['areas'], o.area_id),
            'Linea': _name(lookups['lines'], o.line_id),
            'Equipo': eq.name if eq else None,
            'TAG': eq.tag if eq else None,
            'Componente': _name(lookups['comps'], o.component_id),
            'Descripcion': o.description,
            'Horas_Estimadas': o.estimated_duration,
            'Horas_Reales': o.real_duration,
            'Cerrada': _yn(o.status == 'Cerrada'),
        })
    return rows


def query_purchases(lookups):
    """Requisiciones de compra (PurchaseRequest) con info de la OC vinculada
    cuando existe. La fuente principal es PurchaseRequest porque es el
    detalle por item; PurchaseOrder es la cabecera del proveedor."""
    rows = []
    try:
        from models import PurchaseRequest
    except ImportError:
        return rows

    for pr in PurchaseRequest.query.order_by(PurchaseRequest.id).all():
        wo = lookups['wos'].get(pr.work_order_id) if pr.work_order_id else None
        po = pr.purchase_order
        item_name = None
        item_code = None
        if pr.warehouse_item_id and pr.warehouse_item:
            item_name = pr.warehouse_item.name
            item_code = pr.warehouse_item.code
        elif pr.spare_part_id and pr.spare_part:
            item_name = pr.spare_part.name
            item_code = pr.spare_part.code
        rows.append({
            'Codigo_Requisicion': pr.req_code,
            'Estado_Requisicion': pr.status,
            'Tipo_Item': pr.item_type,
            'Codigo_Item': item_code,
            'Nombre_Item': item_name,
            'Descripcion': pr.description,
            'Cantidad': pr.quantity,
            'OT_Codigo': wo.code if wo else None,
            'OT_Estado': wo.status if wo else None,
            'OC_Codigo': po.po_code if po else None,
            'OC_Estado': po.status if po else None,
            'OC_Proveedor': po.provider_name if po else None,
            'OC_Fecha_Emision': po.issue_date.isoformat() if (po and po.issue_date) else None,
            'OC_Fecha_Entrega': po.delivery_date.isoformat() if (po and po.delivery_date) else None,
            'Fecha_Creacion': pr.created_at.isoformat() if pr.created_at else None,
        })
    return rows


def query_warehouse(lookups):
    """Stock actual del almacen."""
    from models import WarehouseItem
    rows = []
    for w in WarehouseItem.query.order_by(WarehouseItem.id).all():
        unit_cost = w.unit_cost or 0
        rows.append({
            'Codigo': w.code,
            'Nombre': w.name,
            'Categoria': w.category,
            'Familia': w.family,
            'Marca': w.brand,
            'Codigo_Fabricante': w.manufacturer_code,
            'Stock_Actual': w.stock,
            'Stock_Minimo': w.min_stock,
            'Stock_Maximo': w.max_stock,
            'ROP': w.rop,
            'Stock_Seguridad': w.safety_stock,
            'Lead_Time_Dias': w.lead_time,
            'Clase_ABC': w.abc_class,
            'Clase_XYZ': w.xyz_class,
            'Criticidad': w.criticality,
            'Unidad': w.unit,
            'Costo_Unitario': unit_cost,
            'Costo_Promedio': w.average_cost,
            'Valor_Total': round((w.stock or 0) * unit_cost, 2),
            'Ubicacion': w.location,
            'Activo': _yn(w.is_active),
        })
    return rows


def query_warehouse_movements(lookups):
    """Movimientos de almacen (entradas/salidas)."""
    try:
        from models import WarehouseMovement
    except ImportError:
        return []
    rows = []
    for m in WarehouseMovement.query.order_by(WarehouseMovement.id.desc()).all():
        wi = lookups['wh_items'].get(m.item_id)
        # reference_id puede apuntar a una OT
        ref_wo = lookups['wos'].get(m.reference_id) if m.reference_id else None
        unit_cost = (wi.unit_cost or 0) if wi else 0
        rows.append({
            'ID': m.id,
            'Fecha': m.date,
            'Tipo': m.movement_type,
            'Codigo_Item': wi.code if wi else None,
            'Nombre_Item': wi.name if wi else None,
            'Cantidad': m.quantity,
            'Costo_Unitario': unit_cost,
            'Total': round((m.quantity or 0) * unit_cost, 2),
            'Referencia_ID': m.reference_id,
            'OT_Codigo': ref_wo.code if ref_wo else None,
            'Motivo': m.reason,
        })
    return rows


def query_equipment_tree(lookups):
    """Arbol completo Area > Linea > Equipo > Sistema > Componente."""
    from models import Component
    from sqlalchemy import text as _t
    from database import db
    rows = db.session.execute(_t("""
        SELECT a.name AS area, l.name AS linea, e.name AS equipo, e.tag,
               e.criticality AS equipo_criticidad,
               s.name AS sistema, c.name AS componente,
               c.criticality AS componente_criticidad
        FROM components c
        JOIN systems s ON c.system_id = s.id
        JOIN equipments e ON s.equipment_id = e.id
        JOIN lines l ON e.line_id = l.id
        JOIN areas a ON l.area_id = a.id
        ORDER BY a.name, l.name, e.name, s.name, c.name
    """)).fetchall()
    cols = ['Area','Linea','Equipo','TAG','Criticidad_Equipo',
            'Sistema','Componente','Criticidad_Componente']
    return [dict(zip(cols, r)) for r in rows]


def query_activities(lookups):
    """Seguimiento de actividades + hitos (un fila por hito)."""
    from models import Activity
    rows = []
    for a in Activity.query.order_by(Activity.id.desc()).all():
        ms_list = [m for m in (a.milestones or []) if getattr(m, 'is_active', True)]
        done = sum(1 for m in ms_list if m.status == 'COMPLETADO')
        total = len(ms_list)
        progress = round((done / total) * 100) if total > 0 else 0
        if not ms_list:
            rows.append({
                'ID_Actividad': a.id,
                'Titulo': a.title,
                'Tipo': a.activity_type,
                'Responsable': a.responsible,
                'Prioridad': a.priority,
                'Estado_Actividad': a.status,
                'Fecha_Inicio': a.start_date,
                'Fecha_Objetivo': a.target_date,
                'Fecha_Completado': a.completion_date,
                'Progreso_%': progress,
                'Hito': None,
                'Hito_Objetivo': None,
                'Hito_Completado': None,
                'Hito_Estado': None,
                'Hito_Comentario': None,
            })
        else:
            for m in ms_list:
                rows.append({
                    'ID_Actividad': a.id,
                    'Titulo': a.title,
                    'Tipo': a.activity_type,
                    'Responsable': a.responsible,
                    'Prioridad': a.priority,
                    'Estado_Actividad': a.status,
                    'Fecha_Inicio': a.start_date,
                    'Fecha_Objetivo': a.target_date,
                    'Fecha_Completado': a.completion_date,
                    'Progreso_%': progress,
                    'Hito': m.description,
                    'Hito_Objetivo': m.target_date,
                    'Hito_Completado': m.completion_date,
                    'Hito_Estado': m.status,
                    'Hito_Comentario': m.comment,
                })
    return rows


def query_rotative_assets(lookups):
    """Activos rotativos + BOM (1 fila por componente del BOM)."""
    try:
        from models import RotativeAsset, RotativeAssetBOM
    except ImportError:
        return []
    rows = []
    for a in RotativeAsset.query.order_by(RotativeAsset.id).all():
        loc = ' / '.join(filter(None, [
            a.area.name if a.area else None,
            a.line.name if a.line else None,
            a.equipment.name if a.equipment else None,
        ]))
        bom_items = RotativeAssetBOM.query.filter_by(asset_id=a.id).all() if RotativeAssetBOM else []
        if not bom_items:
            rows.append({
                'Codigo_Activo': a.code,
                'Nombre_Activo': a.name,
                'Categoria': a.category,
                'Marca': a.brand,
                'Modelo': a.model,
                'Serie': a.serial_number,
                'Estado': a.status,
                'Ubicacion': loc,
                'Repuesto_Codigo': None,
                'Repuesto_Nombre': None,
                'Repuesto_Categoria': None,
                'Repuesto_Cantidad': None,
                'Repuesto_Nota': None,
            })
        else:
            for b in bom_items:
                rows.append({
                    'Codigo_Activo': a.code,
                    'Nombre_Activo': a.name,
                    'Categoria': a.category,
                    'Marca': a.brand,
                    'Modelo': a.model,
                    'Serie': a.serial_number,
                    'Estado': a.status,
                    'Ubicacion': loc,
                    'Repuesto_Codigo': b.warehouse_item.code if b.warehouse_item else None,
                    'Repuesto_Nombre': b.warehouse_item.name if b.warehouse_item else (getattr(b, 'free_text', None) or None),
                    'Repuesto_Categoria': b.category,
                    'Repuesto_Cantidad': b.quantity,
                    'Repuesto_Nota': b.notes,
                })
    return rows


def query_equipos_flat(lookups):
    """Tabla plana de equipos para filtros en Power BI."""
    rows = []
    for e in lookups['equips'].values():
        line = lookups['lines'].get(e.line_id)
        area = lookups['areas'].get(line.area_id) if line else None
        rows.append({
            'ID': e.id,
            'TAG': e.tag,
            'Nombre': e.name,
            'Criticidad': e.criticality,
            'Linea': line.name if line else None,
            'Area': area.name if area else None,
        })
    rows.sort(key=lambda r: ((r['Area'] or '').upper(), (r['Linea'] or '').upper(), (r['TAG'] or '').upper()))
    return rows


# ────────────────────────────────────────────────────────────────
# KPI summary y discovery endpoint
# ────────────────────────────────────────────────────────────────

def get_kpis():
    """Resumen de KPIs para Power BI dashboard tile."""
    from sqlalchemy import text as _t
    from database import db

    def scalar(sql):
        try:
            return db.session.execute(_t(sql)).scalar() or 0
        except Exception:
            return 0

    total_ot       = scalar("SELECT count(*) FROM work_orders")
    open_ot        = scalar("SELECT count(*) FROM work_orders WHERE status != 'Cerrada'")
    closed_ot      = scalar("SELECT count(*) FROM work_orders WHERE status = 'Cerrada'")
    corrective     = scalar("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Correctivo'")
    preventive     = scalar("SELECT count(*) FROM work_orders WHERE maintenance_type = 'Preventivo'")
    notices_pend   = scalar("SELECT count(*) FROM maintenance_notices WHERE status = 'Pendiente'")
    notices_total  = scalar("SELECT count(*) FROM maintenance_notices")
    lub_red        = scalar("SELECT count(*) FROM lubrication_points WHERE is_active = true AND semaphore_status = 'ROJO'")
    insp_red       = scalar("SELECT count(*) FROM inspection_routes WHERE is_active = true AND semaphore_status = 'ROJO'")
    mon_red        = scalar("SELECT count(*) FROM monitoring_points WHERE is_active = true AND semaphore_status = 'ROJO'")
    shutdowns_plan = scalar("SELECT count(*) FROM shutdowns WHERE status = 'PLANIFICADA'")
    purchases_open = scalar("SELECT count(*) FROM purchase_orders WHERE status NOT IN ('CERRADA','RECIBIDA','CANCELADA')")

    total_mt = (corrective or 0) + (preventive or 0)
    return {
        'total_ot':       total_ot,
        'open_ot':        open_ot,
        'closed_ot':      closed_ot,
        'corrective':     corrective,
        'preventive':     preventive,
        'corrective_pct': round(corrective / total_mt * 100, 1) if total_mt > 0 else 0,
        'preventive_pct': round(preventive / total_mt * 100, 1) if total_mt > 0 else 0,
        'notices_total':   notices_total,
        'notices_pending': notices_pend,
        'lub_overdue':     lub_red,
        'insp_overdue':    insp_red,
        'mon_overdue':     mon_red,
        'shutdowns_planned': shutdowns_plan,
        'purchases_open':    purchases_open,
    }


def list_endpoints():
    """Directorio de endpoints Power BI para descubrimiento."""
    return {
        'excel': {
            'url': '/api/reports/powerbi-export',
            'description': 'Excel multi-hoja con todos los datos del CMMS para Power BI',
        },
        'json': {
            'work_orders':            {'url': '/api/powerbi/work-orders',            'description': 'OTs con jerarquia y aviso vinculado'},
            'notices':                {'url': '/api/powerbi/notices',                'description': 'Avisos enriquecidos (scope, modo falla, fechas)'},
            'personnel':              {'url': '/api/powerbi/personnel',              'description': 'Personal asignado a cada OT'},
            'materials':              {'url': '/api/powerbi/materials',              'description': 'Materiales/repuestos por OT con costos'},
            'log_entries':            {'url': '/api/powerbi/ot-log',                 'description': 'Bitacora de OTs'},
            'equipment_tree':         {'url': '/api/powerbi/equipment-tree',         'description': 'Arbol completo de activos'},
            'equipments':             {'url': '/api/powerbi/equipments',             'description': 'Tabla plana de equipos'},
            'lubrication_points':     {'url': '/api/powerbi/lubrication-points',     'description': 'Puntos de lubricacion + semaforo'},
            'lubrication_executions': {'url': '/api/powerbi/lubrication-executions', 'description': 'Ejecuciones historicas de lubricacion'},
            'inspection_routes':      {'url': '/api/powerbi/inspection-routes',      'description': 'Rutas de inspeccion + semaforo'},
            'inspection_executions':  {'url': '/api/powerbi/inspection-executions',  'description': 'Ejecuciones de inspeccion (1 fila por item evaluado)'},
            'monitoring_points':      {'url': '/api/powerbi/monitoring-points',      'description': 'Puntos de monitoreo + umbrales'},
            'monitoring_readings':    {'url': '/api/powerbi/monitoring-readings',    'description': 'Lecturas historicas de monitoreo'},
            'thickness':              {'url': '/api/powerbi/thickness',              'description': 'Espesores por punto y por inspeccion'},
            'shutdowns':              {'url': '/api/powerbi/shutdowns',              'description': 'Cabecera de paradas de planta'},
            'shutdown_ots':           {'url': '/api/powerbi/shutdown-ots',           'description': 'OTs vinculadas a cada parada'},
            'purchases':              {'url': '/api/powerbi/purchases',              'description': 'OCs y requisiciones de compra'},
            'warehouse':              {'url': '/api/powerbi/warehouse',              'description': 'Stock actual del almacen'},
            'warehouse_movements':    {'url': '/api/powerbi/warehouse-movements',    'description': 'Entradas/salidas de almacen'},
            'activities':             {'url': '/api/powerbi/activities',             'description': 'Seguimiento de actividades + hitos'},
            'rotative_assets':        {'url': '/api/powerbi/rotative-assets',        'description': 'Activos rotativos + BOM'},
            'failure_analysis':       {'url': '/api/powerbi/failure-analysis',       'description': 'Solo correctivos para analisis de modos de falla'},
            'kpis':                   {'url': '/api/powerbi/kpis',                   'description': 'Indicadores agregados para tarjetas'},
        }
    }


# ────────────────────────────────────────────────────────────────
# Excel master workbook
# ────────────────────────────────────────────────────────────────

def build_workbook():
    """Construye el Excel master con todas las hojas y devuelve BytesIO."""
    import pandas as pd

    lookups = _build_lookups()

    # Mapa hoja -> queryfn. Mantener nombres cortos (Excel limita a 31).
    sheets = [
        ('OTs',                query_work_orders(lookups)),
        ('Avisos',             query_notices(lookups)),
        ('Personal_OT',        query_ot_personnel(lookups)),
        ('Materiales_OT',      query_ot_materials(lookups)),
        ('OT_Bitacora',        query_ot_log_entries(lookups)),
        ('Equipos',            query_equipos_flat(lookups)),
        ('Arbol_Activos',      query_equipment_tree(lookups)),
        ('Lub_Puntos',         query_lubrication_points(lookups)),
        ('Lub_Ejecuciones',    query_lubrication_executions(lookups)),
        ('Insp_Rutas',         query_inspection_routes(lookups)),
        ('Insp_Ejecuciones',   query_inspection_executions(lookups)),
        ('Mon_Puntos',         query_monitoring_points(lookups)),
        ('Mon_Lecturas',       query_monitoring_readings(lookups)),
        ('Espesores',          query_thickness(lookups)),
        ('Paradas',            query_shutdowns(lookups)),
        ('Paradas_OTs',        query_shutdown_ots(lookups)),
        ('Compras',            query_purchases(lookups)),
        ('Almacen',            query_warehouse(lookups)),
        ('Almacen_Movimientos',query_warehouse_movements(lookups)),
        ('Actividades',        query_activities(lookups)),
        ('Activos_Rotativos',  query_rotative_assets(lookups)),
    ]

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, rows in sheets:
            df = pd.DataFrame(rows or [])
            # Si esta vacio escribir cabecera placeholder para evitar
            # 'sheet sin columnas' que rompe Power BI
            if df.empty:
                df = pd.DataFrame([{'_empty': '(sin datos)'}])
            df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    output.seek(0)
    return output
