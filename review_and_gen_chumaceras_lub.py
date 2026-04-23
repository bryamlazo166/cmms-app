"""Revisa puntos de lubricación existentes y genera los faltantes para las
chumaceras motriz y conducida de TODAS las áreas.

Uso:
  python review_and_gen_chumaceras_lub.py          -> modo DRY-RUN (no inserta)
  python review_and_gen_chumaceras_lub.py --apply  -> inserta realmente
"""
import os
import sys

os.environ['DB_MODE'] = 'supabase'
os.environ['DATABASE_URL'] = 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ['SUPABASE_PROBE_TIMEOUT_SEC'] = '5'
os.environ['ALLOW_LOCAL_FALLBACK'] = '0'

from app import app, db
from sqlalchemy import text
from datetime import date, timedelta


APPLY = '--apply' in sys.argv

# Defaults definidos por el usuario: quincenal + GRASA FRIXO 177
FREQUENCY_DAYS = 15
WARNING_DAYS = 3
LUBRICANT = 'GRASA FRIXO 177'
QUANTITY_UNIT = 'g'
TASK_GROUP = 'LUBRICACION QUINCENAL'
TASK_TYPE = 'LUBRICACION'


with app.app_context():
    print(f"\n{'=' * 70}")
    print(f" MODO: {'APLICAR CAMBIOS' if APPLY else 'DRY-RUN (solo reporte)'}")
    print(f"{'=' * 70}\n")

    try:
        # 1. Resumen global de puntos de lubricación existentes
        print("## RESUMEN ACTUAL DE PUNTOS DE LUBRICACIÓN ##")
        total_act = db.session.execute(
            text("SELECT count(*) FROM lubrication_points WHERE is_active = true")
        ).scalar()
        print(f"   Total activos: {total_act}")

        by_area = db.session.execute(text("""
            SELECT a.name, COUNT(lp.id)
            FROM lubrication_points lp
            LEFT JOIN areas a ON lp.area_id = a.id
            WHERE lp.is_active = true
            GROUP BY a.name
            ORDER BY a.name
        """)).fetchall()
        for area_name, cnt in by_area:
            print(f"     * {area_name or '(sin área)':20s} -> {cnt} puntos")

        # 2. Buscar TODOS los componentes tipo chumacera en todas las áreas
        print("\n## BÚSQUEDA DE CHUMACERAS EN EL ÁRBOL DE EQUIPOS ##")
        chumaceras = db.session.execute(text("""
            SELECT
                c.id            AS component_id,
                c.name          AS component_name,
                s.id            AS system_id,
                s.name          AS system_name,
                e.id            AS equipment_id,
                e.tag           AS equipment_tag,
                e.name          AS equipment_name,
                l.id            AS line_id,
                l.name          AS line_name,
                a.id            AS area_id,
                a.name          AS area_name
            FROM components c
            JOIN systems s    ON c.system_id = s.id
            JOIN equipments e ON s.equipment_id = e.id
            JOIN lines l      ON e.line_id = l.id
            JOIN areas a      ON l.area_id = a.id
            WHERE UPPER(c.name) LIKE '%CHUMACERA%'
            ORDER BY a.name, l.name, e.tag, c.name
        """)).fetchall()
        print(f"   Encontradas {len(chumaceras)} componentes tipo 'CHUMACERA' en BD")

        if not chumaceras:
            print("\n   [!]  No hay componentes con nombre 'CHUMACERA*'. Nada que hacer.")
            sys.exit(0)

        # 3. Agrupar por área para mostrar
        from collections import defaultdict
        by_area_chm = defaultdict(list)
        for row in chumaceras:
            by_area_chm[row.area_name].append(row)

        for area_name, rows in sorted(by_area_chm.items()):
            motriz = sum(1 for r in rows if 'MOTRIZ' in r.component_name.upper())
            conducida = sum(1 for r in rows if 'CONDUCIDA' in r.component_name.upper())
            otras = len(rows) - motriz - conducida
            print(f"     * {area_name:20s} -> {motriz} motriz, {conducida} conducida, {otras} otras")

        # 4. Para cada chumacera, generar código propuesto y ver si ya existe
        # Primero clasificar y detectar duplicados por (equipo, tipo) para agregar sufijo numérico
        print("\n## PROPUESTA DE PUNTOS A CREAR ##")
        today = date.today()
        next_due = (today + timedelta(days=FREQUENCY_DAYS)).isoformat()
        to_create = []
        already_exist = []
        skipped = []

        # Primera pasada: agrupar chumaceras por (equipo, tipo) para detectar múltiples
        from collections import Counter
        key_counts = Counter()
        for row in chumaceras:
            cname_upper = row.component_name.upper()
            if 'MOTRIZ' in cname_upper:
                key_counts[(row.equipment_id, 'MOT')] += 1
            elif 'CONDUCIDA' in cname_upper:
                key_counts[(row.equipment_id, 'CON')] += 1

        # Segunda pasada: generar códigos, con sufijo -N solo cuando hay múltiples
        seen_counter = Counter()  # cuántas ya hemos procesado de cada (equipo, tipo)
        for row in chumaceras:
            cname_upper = row.component_name.upper()
            if 'MOTRIZ' in cname_upper:
                stype = 'MOT'
                task_name = 'ENGRASE CHUMACERA MOTRIZ'
            elif 'CONDUCIDA' in cname_upper:
                stype = 'CON'
                task_name = 'ENGRASE CHUMACERA CONDUCIDA'
            else:
                skipped.append(row)
                continue

            key = (row.equipment_id, stype)
            total_for_key = key_counts[key]
            seen_counter[key] += 1
            idx = seen_counter[key]

            if total_for_key == 1:
                # Único del tipo en el equipo → sin sufijo numérico
                code = f"LUB-{row.equipment_tag}-CHM-{stype}"
                point_name = f"LUBRICACION CHUMACERA {'MOTRIZ' if stype == 'MOT' else 'CONDUCIDA'} {row.equipment_tag}"
            else:
                # Múltiples → agregar sufijo -N
                code = f"LUB-{row.equipment_tag}-CHM-{stype}-{idx}"
                point_name = f"LUBRICACION CHUMACERA {'MOTRIZ' if stype == 'MOT' else 'CONDUCIDA'} #{idx} {row.equipment_tag}"

            existing = db.session.execute(
                text("SELECT id FROM lubrication_points WHERE code = :c"),
                {"c": code}
            ).fetchone()

            if existing:
                already_exist.append((code, row))
            else:
                to_create.append({
                    'code': code,
                    'name': point_name,
                    'task_name': task_name,
                    'row': row,
                })

        print(f"   -> {len(to_create)} puntos nuevos a crear")
        print(f"   -> {len(already_exist)} puntos ya existen (se omiten)")
        if skipped:
            print(f"   -> {len(skipped)} chumaceras sin 'MOTRIZ'/'CONDUCIDA' en nombre (se omiten)")
            for r in skipped[:10]:
                print(f"       [SKIP] {r.area_name} / {r.equipment_tag} / {r.component_name}")

        if not to_create:
            print("\n   [OK] Todas las chumaceras ya tienen punto de lubricación.\n")
            sys.exit(0)

        # Agrupar la propuesta por área para el reporte
        print("\n## PUNTOS NUEVOS A CREAR POR ÁREA ##")
        by_area_new = defaultdict(list)
        for item in to_create:
            by_area_new[item['row'].area_name].append(item)
        for area_name, items in sorted(by_area_new.items()):
            print(f"\n  --- {area_name} ({len(items)} puntos) ---")
            for it in items[:15]:
                r = it['row']
                print(f"     {it['code']:30s} | {r.equipment_tag:8s} | {it['task_name']}")
            if len(items) > 15:
                print(f"     ... y {len(items) - 15} más")

        # 5. Si APPLY, crear
        if not APPLY:
            print("\n" + "=" * 70)
            print(" DRY-RUN: nada se modificó. Para aplicar, vuelve a correr con --apply")
            print("=" * 70 + "\n")
            sys.exit(0)

        print("\n## CREANDO PUNTOS EN BD ##")
        created_count = 0
        for item in to_create:
            r = item['row']
            db.session.execute(text("""
                INSERT INTO lubrication_points (
                    code, name, task_name, task_group, task_type,
                    area_id, line_id, equipment_id, system_id, component_id,
                    lubricant_name, quantity_unit, frequency_days, warning_days,
                    next_due_date, semaphore_status, is_active, created_at, updated_at
                )
                VALUES (
                    :code, :name, :task_name, :task_group, :task_type,
                    :area_id, :line_id, :equipment_id, :system_id, :component_id,
                    :lubricant, :unit, :freq, :warn,
                    :due, 'VERDE', true, NOW(), NOW()
                )
            """), {
                'code': item['code'],
                'name': item['name'],
                'task_name': item['task_name'],
                'task_group': TASK_GROUP,
                'task_type': TASK_TYPE,
                'area_id': r.area_id,
                'line_id': r.line_id,
                'equipment_id': r.equipment_id,
                'system_id': r.system_id,
                'component_id': r.component_id,
                'lubricant': LUBRICANT,
                'unit': QUANTITY_UNIT,
                'freq': FREQUENCY_DAYS,
                'warn': WARNING_DAYS,
                'due': next_due,
            })
            created_count += 1

        db.session.commit()
        print(f"\n   [OK] {created_count} puntos creados exitosamente")

        # Resumen final
        new_total = db.session.execute(
            text("SELECT count(*) FROM lubrication_points WHERE is_active = true")
        ).scalar()
        print(f"   Total puntos activos ahora: {new_total} (antes: {total_act})\n")

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        print(f"\n   [X] ERROR: {e}\n")
        sys.exit(1)
    finally:
        db.session.remove()
