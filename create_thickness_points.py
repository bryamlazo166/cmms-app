"""Crear los puntos de medición de espesor para los 9 digestores.

Estructura por digestor (90 puntos):
- TRIPODE INTERNO:
    - Paletas: 5 secciones × 3 (A, B, C) = 15
    - Refuerzo: 5 secciones × 3 (X, Y, Z) = 15
    - Ejes: 5 secciones × 4 (A, B, C, EJE_CENTRAL) = 20
- CHAQUETA INTERNA: 5 secciones × 4 (SUPERIOR, DERECHO, INFERIOR, IZQUIERDO) = 20
- TAPA BOMBEADA MOTRIZ: 10 puntos perimetrales (P1..P10)
- TAPA BOMBEADA CONDUCIDA: 10 puntos perimetrales (P1..P10)

Espesores por defecto:
- Paleta de trípode: 11.0 mm nominal, 9.5 alarma, 8.0 scrap (a confirmar)
- Refuerzo trípode: 8.5 mm nominal, 8.5 alarma, 8.0 scrap (a confirmar)
- Eje trípode: 14.5 mm nominal, 10.0 alarma, 8.0 scrap (a confirmar)
- Chaqueta interna: 25.4 mm nominal, 10.0 alarma, 8.0 scrap (CONFIRMADO)
- Tapas: 25.4 mm nominal, 10.0 alarma, 8.0 scrap (CONFIRMADO)
"""
import os
os.environ['DB_MODE'] = 'supabase'
os.environ['DATABASE_URL'] = 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ['SUPABASE_PROBE_TIMEOUT_SEC'] = '5'
os.environ['ALLOW_LOCAL_FALLBACK'] = '0'
os.environ['SUPABASE_URL'] = 'https://zxgksjwszqqvwoyfrekw.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'x'

from app import app, db
from sqlalchemy import text

# Espesores por componente (mm)
SPECS = {
    'PALETA':         {'nominal': 11.0, 'alarm': 9.5,  'scrap': 8.0},
    'REFUERZO':       {'nominal': 8.5,  'alarm': 8.5,  'scrap': 8.0},
    'EJE':            {'nominal': 14.5, 'alarm': 10.0, 'scrap': 8.0},
    'CHAQUETA':       {'nominal': 25.4, 'alarm': 10.0, 'scrap': 8.0},
    'TAPA_MOTRIZ':    {'nominal': 25.4, 'alarm': 10.0, 'scrap': 8.0},
    'TAPA_CONDUCIDA': {'nominal': 25.4, 'alarm': 10.0, 'scrap': 8.0},
}


def get_or_create_component(equipment_id, system_id, name):
    """Obtiene o crea un componente dentro del sistema."""
    r = db.session.execute(text(
        "SELECT id FROM components WHERE system_id = :s AND UPPER(name) = :n"
    ), {"s": system_id, "n": name.upper()}).fetchone()
    if r:
        return r[0]
    db.session.execute(text(
        "INSERT INTO components (name, system_id) VALUES (:n, :s)"
    ), {"n": name, "s": system_id})
    db.session.commit()
    r = db.session.execute(text(
        "SELECT id FROM components WHERE system_id = :s AND UPPER(name) = :n"
    ), {"s": system_id, "n": name.upper()}).fetchone()
    return r[0] if r else None


def insert_point(equipment_id, component_id, group_name, section, position, order_index):
    """Inserta un punto si no existe."""
    spec = SPECS[group_name]
    # Check si existe
    exists = db.session.execute(text(
        "SELECT id FROM thickness_points WHERE equipment_id = :e AND group_name = :g "
        "AND COALESCE(section, 0) = :s AND position = :p"
    ), {"e": equipment_id, "g": group_name, "s": section or 0, "p": position}).fetchone()
    if exists:
        return False
    db.session.execute(text("""
        INSERT INTO thickness_points (
            equipment_id, component_id, group_name, section, position,
            nominal_thickness, alarm_thickness, scrap_thickness,
            status, is_active, order_index
        ) VALUES (
            :e, :c, :g, :s, :p,
            :n, :a, :sc,
            'NORMAL', true, :oi
        )
    """), {
        "e": equipment_id, "c": component_id, "g": group_name, "s": section, "p": position,
        "n": spec['nominal'], "a": spec['alarm'], "sc": spec['scrap'], "oi": order_index,
    })
    return True


def create_points_for_equipment(eq_id, eq_tag, eq_name):
    """Crea los 90 puntos para un digestor."""
    print(f"\n=== {eq_tag} ({eq_name}) ===")

    # Buscar SISTEMA: TANQUE DIGESTOR (o similar)
    sys_row = db.session.execute(text(
        "SELECT id FROM systems WHERE equipment_id = :e AND UPPER(name) LIKE '%TANQUE%'"
    ), {"e": eq_id}).fetchone()
    if not sys_row:
        # Intentar con otro nombre
        sys_row = db.session.execute(text(
            "SELECT id FROM systems WHERE equipment_id = :e AND UPPER(name) LIKE '%DIGESTOR%'"
        ), {"e": eq_id}).fetchone()
    if not sys_row:
        # Crear sistema TANQUE DIGESTOR
        db.session.execute(text(
            "INSERT INTO systems (name, equipment_id) VALUES ('TANQUE DIGESTOR', :e)"
        ), {"e": eq_id})
        db.session.commit()
        sys_row = db.session.execute(text(
            "SELECT id FROM systems WHERE equipment_id = :e AND UPPER(name) = 'TANQUE DIGESTOR'"
        ), {"e": eq_id}).fetchone()
        print(f"  Creado sistema TANQUE DIGESTOR")
    sys_id = sys_row[0]

    # Componentes
    c_tripode = get_or_create_component(eq_id, sys_id, 'TRIPODE INTERNO')
    c_chaqueta = get_or_create_component(eq_id, sys_id, 'CHAQUETA INTERNA')
    c_tapa_motriz = get_or_create_component(eq_id, sys_id, 'TAPA BOMBEADA MOTRIZ')
    c_tapa_conducida = get_or_create_component(eq_id, sys_id, 'TAPA BOMBEADA CONDUCIDA')

    created = 0
    order = 0

    # PALETAS DE TRIPODE: 5 secciones × 3 posiciones (A, B, C)
    for sec in range(1, 6):
        for pos in ['A', 'B', 'C']:
            order += 1
            if insert_point(eq_id, c_tripode, 'PALETA', sec, pos, order):
                created += 1

    # REFUERZO DE TRIPODE: 5 secciones × 3 posiciones (X, Y, Z)
    for sec in range(1, 6):
        for pos in ['X', 'Y', 'Z']:
            order += 1
            if insert_point(eq_id, c_tripode, 'REFUERZO', sec, pos, order):
                created += 1

    # EJES DE TRIPODE: 5 secciones × 4 posiciones (A, B, C, EJE_CENTRAL)
    for sec in range(1, 6):
        for pos in ['A', 'B', 'C', 'EJE_CENTRAL']:
            order += 1
            if insert_point(eq_id, c_tripode, 'EJE', sec, pos, order):
                created += 1

    # CHAQUETA INTERNA: 5 secciones × 4 ángulos (SUPERIOR, DERECHO, INFERIOR, IZQUIERDO)
    for sec in range(1, 6):
        for pos in ['SUPERIOR', 'DERECHO', 'INFERIOR', 'IZQUIERDO']:
            order += 1
            if insert_point(eq_id, c_chaqueta, 'CHAQUETA', sec, pos, order):
                created += 1

    # TAPA BOMBEADA MOTRIZ: 10 puntos
    for i in range(1, 11):
        order += 1
        if insert_point(eq_id, c_tapa_motriz, 'TAPA_MOTRIZ', None, f'P{i}', order):
            created += 1

    # TAPA BOMBEADA CONDUCIDA: 10 puntos
    for i in range(1, 11):
        order += 1
        if insert_point(eq_id, c_tapa_conducida, 'TAPA_CONDUCIDA', None, f'P{i}', order):
            created += 1

    db.session.commit()
    print(f"  {created} puntos creados (de 90 esperados)")
    return created


with app.app_context():
    try:
        # Buscar todos los digestores en COCCION
        digestors = db.session.execute(text("""
            SELECT e.id, e.tag, e.name
            FROM equipments e
            JOIN lines l ON e.line_id = l.id
            JOIN areas a ON l.area_id = a.id
            WHERE a.name = 'COCCION'
              AND (e.tag LIKE 'D%' AND e.tag NOT LIKE 'TH%')
            ORDER BY e.tag
        """)).fetchall()

        print(f"Encontrados {len(digestors)} digestores")
        total_created = 0
        for eq_id, eq_tag, eq_name in digestors:
            total_created += create_points_for_equipment(eq_id, eq_tag, eq_name)

        print(f"\n=== TOTAL: {total_created} puntos creados ===")

        # Verificar
        total_db = db.session.execute(text(
            "SELECT count(*) FROM thickness_points WHERE is_active = true"
        )).scalar()
        print(f"Total en BD: {total_db}")

        # Por grupo
        by_group = db.session.execute(text(
            "SELECT group_name, count(*) FROM thickness_points WHERE is_active = true GROUP BY group_name ORDER BY group_name"
        )).fetchall()
        for g, n in by_group:
            print(f"  {g}: {n}")
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.session.remove()
