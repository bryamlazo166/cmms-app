"""Helpers para resolver el responsable efectivo de un punto preventivo.

Modelo hibrido (Opcion C):
- Equipment.default_responsible_party / default_provider_id = responsable
  por defecto del equipo (INTERNO o PROVEEDOR).
- LubricationPoint / InspectionRoute / MonitoringPoint pueden tener
  responsible_party_override / provider_id_override para sobrescribir el
  default del equipo en casos puntuales.
"""

INTERNO = 'INTERNO'
PROVEEDOR = 'PROVEEDOR'


def resolve_responsibility(point, equipment=None):
    """Devuelve (party, provider_id) efectivo de un punto preventivo.

    Orden de prioridad:
      1. point.responsible_party_override (si no NULL)
      2. equipment.default_responsible_party (si hay equipo)
      3. INTERNO (default global)
    """
    party = getattr(point, 'responsible_party_override', None)
    provider_id = getattr(point, 'provider_id_override', None)

    if party:
        return party, provider_id

    eq = equipment if equipment is not None else getattr(point, 'equipment', None)
    if eq is not None:
        eq_party = getattr(eq, 'default_responsible_party', None) or INTERNO
        eq_provider = getattr(eq, 'default_provider_id', None)
        return eq_party, eq_provider

    return INTERNO, None


def is_provider_point(point, equipment=None, provider_id=None):
    """True si el punto es responsabilidad del proveedor especificado.
    Si provider_id es None, True para CUALQUIER proveedor.
    """
    party, pid = resolve_responsibility(point, equipment)
    if party != PROVEEDOR:
        return False
    if provider_id is None:
        return True
    # Si el punto no especifica proveedor pero esta marcado como PROVEEDOR,
    # se asume que aplica al proveedor activo del plan.
    return pid is None or pid == provider_id


def is_internal_point(point, equipment=None):
    party, _ = resolve_responsibility(point, equipment)
    return party == INTERNO
