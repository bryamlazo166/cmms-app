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


def resolve_ot_specialty(ot, equipment=None):
    """Resuelve la especialidad de una OT para la Hoja Diaria.

    Cascada:
      1. Aviso vinculado tiene specialty manual -> usar.
      2. Personal asignado / proveedor (specialty_for_ot).
      3. Inferencia por palabras clave (descripcion + tag de equipo).
    Devuelve uno de: MECANICO, ELECTRICO, MIXTO, SIN CLASIF.
    """
    notice = getattr(ot, 'notice', None)
    if notice is not None:
        manual = normalize_specialty_label(getattr(notice, 'specialty', None))
        if manual in ('MECANICO', 'ELECTRICO', 'MIXTO'):
            return manual

    sp = specialty_for_ot(ot)
    if sp in ('MECANICO', 'ELECTRICO', 'MIXTO'):
        return sp

    eq_tag = getattr(equipment, 'tag', None) if equipment is not None else None
    eq_name = getattr(equipment, 'name', None) if equipment is not None else None
    return infer_discipline_from_text(
        getattr(ot, 'description', None),
        getattr(ot, 'failure_mode', None),
        eq_tag, eq_name,
    )


def resolve_notice_specialty(notice, equipment=None):
    """Resuelve la especialidad de un Aviso para la Hoja Diaria.

    Si el campo manual existe, lo usa. Sino, infiere por palabras clave.
    """
    manual = normalize_specialty_label(getattr(notice, 'specialty', None))
    if manual in ('MECANICO', 'ELECTRICO', 'MIXTO'):
        return manual

    eq_tag = getattr(equipment, 'tag', None) if equipment is not None else None
    eq_name = getattr(equipment, 'name', None) if equipment is not None else None
    return infer_discipline_from_text(
        getattr(notice, 'description', None),
        getattr(notice, 'failure_mode', None),
        getattr(notice, 'blockage_object', None),
        eq_tag, eq_name,
    )


def specialty_matches_filter(item_specialty, wanted):
    """True si un item de `item_specialty` debe aparecer en el PDF filtrado por `wanted`.

    Reglas:
      - wanted vacio/None -> True (sin filtro).
      - MIXTO siempre aparece en ambos PDFs (mecanico y electrico).
      - SIN_CLASIF: aparece solo si wanted == 'SIN CLASIF' o sin filtro.
    """
    if not wanted:
        return True
    item = (item_specialty or '').upper().strip()
    target = (wanted or '').upper().strip().replace('_', ' ')
    if item == target:
        return True
    if item == 'MIXTO' and target in ('MECANICO', 'ELECTRICO'):
        return True
    return False


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
