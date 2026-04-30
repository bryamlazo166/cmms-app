"""Helpers para clasificar OTs y tareas como MECANICO / ELECTRICO / MIXTO.

Estos helpers son la fuente unica de verdad para la "disciplina" de una
actividad. Los reportes (export OTs, programa nocturno PDF, plan semanal)
los reusan para mostrar la columna Disciplina/Especialidad consistente.
"""
import re

ELECTRICAL_KEYWORDS = (
    'ELECTR', 'MOTOR', 'TABLERO', 'VARIADOR', 'VFD', 'PLC',
    'CONTACTOR', 'BREAKER', 'TERMICO', 'AISLAMIENTO',
    'MEGADO', 'MEGGER', 'MEDICION ELECTRICA', 'CONEXION',
    'FUSIBLE', 'RELE', 'TRANSFORMADOR', 'CABLEADO',
    'SUBESTACION', 'INSTRUMENTACION', 'SENSOR', 'PT100',
)

MECHANICAL_KEYWORDS = (
    'MECANIC', 'RODAMIENT', 'CHUMACERA', 'FAJA', 'CADENA',
    'ACEITE', 'GRASA', 'LUBRIC', 'BOMBA', 'VALVULA',
    'COMPRESOR', 'REDUCTOR', 'TRIPODE', 'PALETA', 'EJE',
    'CHAQUETA', 'TAPA BOMBEADA', 'ESPESOR', 'ULTRASONIDO',
    'ALINEACION', 'TORQUE', 'SOLDADURA', 'CHAPA', 'PLANCHA',
    'TUBO', 'TUBERIA', 'RETEN', 'EMPAQUE', 'OBRA CIVIL',
)


def normalize_specialty_label(raw_value):
    """Normaliza un texto libre a una de: MECANICO, ELECTRICO, MIXTO, SIN ASIGNAR."""
    value = (raw_value or '').strip().upper()
    if not value:
        return 'SIN ASIGNAR'
    if 'ELECT' in value:
        return 'ELECTRICO'
    if 'MEC' in value:
        return 'MECANICO'
    if 'MIX' in value:
        return 'MIXTO'
    return value


def specialty_for_ot(ot):
    """Disciplina de una OT segun personal asignado, o proveedor.

    Devuelve MECANICO, ELECTRICO, MIXTO o SIN ASIGNAR.
    """
    specialties = []
    for assignment in getattr(ot, 'assigned_personnel', []) or []:
        candidate = assignment.specialty
        if not candidate and getattr(assignment, 'technician', None):
            candidate = assignment.technician.specialty
        normalized = normalize_specialty_label(candidate)
        if normalized and normalized != 'SIN ASIGNAR':
            specialties.append(normalized)

    if not specialties and getattr(ot, 'provider', None) and ot.provider.specialty:
        provider_specialty = normalize_specialty_label(ot.provider.specialty)
        if provider_specialty and provider_specialty != 'SIN ASIGNAR':
            specialties.append(provider_specialty)

    unique = sorted(set(specialties))
    if not unique:
        return 'SIN ASIGNAR'
    if 'MECANICO' in unique and 'ELECTRICO' in unique:
        return 'MIXTO'
    if 'MECANICO' in unique:
        return 'MECANICO'
    if 'ELECTRICO' in unique:
        return 'ELECTRICO'
    return unique[0]


def infer_discipline_from_text(*texts):
    """Cuando no hay personal asignado, inferir la disciplina por palabras
    clave en la descripcion / nombre del activo / origen.

    Mas conservador: si solo hay match electrico devuelve ELECTRICO,
    si solo hay match mecanico devuelve MECANICO, ambos -> MIXTO,
    nada -> SIN CLASIF.
    """
    blob = ' '.join(t for t in texts if t).upper()
    if not blob:
        return 'SIN CLASIF'
    elec = any(kw in blob for kw in ELECTRICAL_KEYWORDS)
    mech = any(kw in blob for kw in MECHANICAL_KEYWORDS)
    if elec and mech:
        return 'MIXTO'
    if elec:
        return 'ELECTRICO'
    if mech:
        return 'MECANICO'
    return 'SIN CLASIF'


def discipline_for_weekly_item(item):
    """Disciplina de un WeeklyPlanItem.
    1. Si la OT vinculada existe y tiene personal -> usar specialty_for_ot
    2. Sino, source_type='lubrication' -> MECANICO
    3. Sino, inferir por palabras clave en description/source_name/equipment_tag
    """
    work_order = getattr(item, 'work_order', None)
    if work_order is None and getattr(item, 'work_order_id', None):
        try:
            from models import WorkOrder
            work_order = WorkOrder.query.get(item.work_order_id)
        except Exception:
            work_order = None
    if work_order is not None:
        sp = specialty_for_ot(work_order)
        if sp != 'SIN ASIGNAR':
            return sp

    src = (item.source_type or '').lower()
    if src == 'lubrication':
        return 'MECANICO'

    return infer_discipline_from_text(
        item.description, item.source_name, item.source_code, item.equipment_tag,
    )
