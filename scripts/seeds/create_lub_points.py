"""Create lubrication points for COCCION area (Digestors and TH)."""
import os
os.environ['DB_MODE'] = 'supabase'
os.environ['DATABASE_URL'] = 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ['SUPABASE_PROBE_TIMEOUT_SEC'] = '5'
os.environ['ALLOW_LOCAL_FALLBACK'] = '0'
os.environ['SUPABASE_URL'] = 'https://zxgksjwszqqvwoyfrekw.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'x'

from app import app, db
from sqlalchemy import text
from datetime import date, timedelta


with app.app_context():
    try:
        # Get COCCION area
        area = db.session.execute(text("SELECT id FROM areas WHERE name = 'COCCION'")).fetchone()
        coccion_id = area[0]

        # Get all digestors and THs in COCCION
        equips = db.session.execute(text("""
            SELECT e.id, e.name, e.tag, l.id as line_id
            FROM equipments e
            JOIN lines l ON e.line_id = l.id
            WHERE l.area_id = :a AND (e.tag LIKE 'D%' OR e.tag LIKE 'TH%')
            ORDER BY e.tag
        """), {"a": coccion_id}).fetchall()

        print(f"Found {len(equips)} equipment in COCCION")

        # Get system + component IDs for each equipment
        def get_system(eq_id, sys_name):
            r = db.session.execute(text("SELECT id FROM systems WHERE equipment_id = :e AND name = :n"), {"e": eq_id, "n": sys_name}).fetchone()
            return r[0] if r else None

        def get_component(sys_id, comp_name):
            r = db.session.execute(text("SELECT id FROM components WHERE system_id = :s AND UPPER(name) = :n"), {"s": sys_id, "n": comp_name.upper()}).fetchone()
            return r[0] if r else None

        next_due = (date.today() + timedelta(days=7)).isoformat()
        next_due_30 = (date.today() + timedelta(days=30)).isoformat()
        created = 0

        for eq_id, eq_name, eq_tag, line_id in equips:
            is_digestor = eq_tag.startswith('D') and not eq_tag.startswith('TH')
            is_th = eq_tag.startswith('TH')

            # SISTEMA DE ACCIONAMIENTO has chumaceras + faja/cadena
            sys_acc = get_system(eq_id, 'SISTEMA DE ACCIONAMIENTO')
            if not sys_acc:
                print(f"  Skip {eq_tag}: no SISTEMA DE ACCIONAMIENTO")
                continue

            comp_chm_mot = get_component(sys_acc, 'CHUMACERA MOTRIZ')
            comp_chm_con = get_component(sys_acc, 'CHUMACERA CONDUCIDA')

            # CHUMACERA MOTRIZ — semanal
            if comp_chm_mot:
                code = f"LUB-{eq_tag}-CHM-MOT"
                db.session.execute(text("""
                    INSERT INTO lubrication_points (code, name, task_name, task_group, task_type,
                        area_id, line_id, equipment_id, system_id, component_id,
                        lubricant_name, quantity_unit, frequency_days, warning_days,
                        next_due_date, semaphore_status, is_active, created_at, updated_at)
                    VALUES (:code, :name, :task, 'LUBRICACION SEMANAL', 'LUBRICACION',
                        :a, :l, :e, :s, :c,
                        'POR IDENTIFICAR', 'g', 7, 2,
                        :due, 'VERDE', true, NOW(), NOW())
                """), {
                    "code": code, "name": f"LUBRICACION CHUMACERA MOTRIZ {eq_tag}",
                    "task": "ENGRASE CHUMACERA MOTRIZ",
                    "a": coccion_id, "l": line_id, "e": eq_id, "s": sys_acc, "c": comp_chm_mot,
                    "due": next_due,
                })
                created += 1

            # CHUMACERA CONDUCIDA — semanal
            if comp_chm_con:
                code = f"LUB-{eq_tag}-CHM-CON"
                db.session.execute(text("""
                    INSERT INTO lubrication_points (code, name, task_name, task_group, task_type,
                        area_id, line_id, equipment_id, system_id, component_id,
                        lubricant_name, quantity_unit, frequency_days, warning_days,
                        next_due_date, semaphore_status, is_active, created_at, updated_at)
                    VALUES (:code, :name, :task, 'LUBRICACION SEMANAL', 'LUBRICACION',
                        :a, :l, :e, :s, :c,
                        'POR IDENTIFICAR', 'g', 7, 2,
                        :due, 'VERDE', true, NOW(), NOW())
                """), {
                    "code": code, "name": f"LUBRICACION CHUMACERA CONDUCIDA {eq_tag}",
                    "task": "ENGRASE CHUMACERA CONDUCIDA",
                    "a": coccion_id, "l": line_id, "e": eq_id, "s": sys_acc, "c": comp_chm_con,
                    "due": next_due,
                })
                created += 1

            # FAJA (only digestors) — mensual
            if is_digestor:
                comp_faja = get_component(sys_acc, 'FAJA')
                if comp_faja:
                    code = f"LUB-{eq_tag}-FAJA"
                    db.session.execute(text("""
                        INSERT INTO lubrication_points (code, name, task_name, task_group, task_type,
                            area_id, line_id, equipment_id, system_id, component_id,
                            lubricant_name, quantity_unit, frequency_days, warning_days,
                            next_due_date, semaphore_status, is_active, created_at, updated_at)
                        VALUES (:code, :name, :task, 'LUBRICACION MENSUAL', 'LUBRICACION',
                            :a, :l, :e, :s, :c,
                            'CRC BELT GRIP FPS', 'ml', 30, 5,
                            :due, 'VERDE', true, NOW(), NOW())
                    """), {
                        "code": code, "name": f"APLICACION ANTIDESLIZANTE FAJA {eq_tag}",
                        "task": "APLICACION CRC BELT GRIP FPS",
                        "a": coccion_id, "l": line_id, "e": eq_id, "s": sys_acc, "c": comp_faja,
                        "due": next_due_30,
                    })
                    created += 1

            # CADENA (only TH) — semanal
            if is_th:
                comp_cadena = get_component(sys_acc, 'CADENA')
                if comp_cadena:
                    code = f"LUB-{eq_tag}-CADENA"
                    db.session.execute(text("""
                        INSERT INTO lubrication_points (code, name, task_name, task_group, task_type,
                            area_id, line_id, equipment_id, system_id, component_id,
                            lubricant_name, quantity_unit, frequency_days, warning_days,
                            next_due_date, semaphore_status, is_active, created_at, updated_at)
                        VALUES (:code, :name, :task, 'LUBRICACION SEMANAL', 'LUBRICACION',
                            :a, :l, :e, :s, :c,
                            'POR IDENTIFICAR', 'ml', 7, 2,
                            :due, 'VERDE', true, NOW(), NOW())
                    """), {
                        "code": code, "name": f"LUBRICACION CADENA {eq_tag}",
                        "task": "LUBRICACION CADENA TRANSMISION",
                        "a": coccion_id, "l": line_id, "e": eq_id, "s": sys_acc, "c": comp_cadena,
                        "due": next_due,
                    })
                    created += 1

        db.session.commit()
        print(f"\n=== DONE: {created} puntos de lubricacion creados ===")

        # Verify
        total = db.session.execute(text("SELECT count(*) FROM lubrication_points WHERE is_active = true")).scalar()
        print(f"Total puntos activos en BD: {total}")

        # List by type
        by_type = db.session.execute(text("""
            SELECT task_group, count(*) FROM lubrication_points WHERE is_active = true GROUP BY task_group
        """)).fetchall()
        for t in by_type:
            print(f"  {t[0]}: {t[1]}")

        db.session.remove()
    except Exception as e:
        db.session.rollback()
        db.session.remove()
        import traceback
        traceback.print_exc()
