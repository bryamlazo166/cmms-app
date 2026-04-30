"""Genera puntos de lubricación para FAJAS y CADENAS de TODAS las áreas.

Frecuencia: 15 días (quincenal), mismo patrón que las chumaceras.

Lubricantes por tipo de componente:
  - FAJA    -> CRC BELT GRIP FPS (antideslizante)
  - CADENA  -> POR IDENTIFICAR (aceite de cadena, el usuario lo define después)

Uso:
  python gen_lub_fajas_cadenas.py          -> DRY-RUN (solo reporte)
  python gen_lub_fajas_cadenas.py --apply  -> inserta realmente
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
from collections import Counter, defaultdict


APPLY = '--apply' in sys.argv

FREQUENCY_DAYS = 15
WARNING_DAYS = 3
TASK_GROUP = 'LUBRICACION QUINCENAL'
TASK_TYPE = 'LUBRICACION'

# Configuración por tipo de componente
TYPE_CONFIG = {
    'FAJA': {
        'lubricant': 'CRC BELT GRIP FPS',
        'unit': 'ml',
        'code_suffix': 'FAJA',
        'task_name': 'APLICACION CRC BELT GRIP FPS EN FAJA',
        'point_name_prefix': 'APLICACION ANTIDESLIZANTE FAJA',
    },
    'CADENA': {
        'lubricant': 'POR IDENTIFICAR',
        'unit': 'ml',
        'code_suffix': 'CADENA',
        'task_name': 'LUBRICACION CADENA TRANSMISION',
        'point_name_prefix': 'LUBRICACION CADENA',
    },
}


with app.app_context():
    print(f"\n{'=' * 72}")
    print(f" MODO: {'APLICAR CAMBIOS' if APPLY else 'DRY-RUN (sin cambios)'}")
    print(f" TARGET: FAJAS y CADENAS | Frecuencia: {FREQUENCY_DAYS} dias (quincenal)")
    print(f"{'=' * 72}\n")

    try:
        # 1. Buscar componentes tipo FAJA y CADENA en todas las areas
        print("## BUSQUEDA DE FAJAS Y CADENAS EN EL ARBOL DE EQUIPOS ##")
        rows = db.session.execute(text("""
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
            WHERE UPPER(c.name) LIKE '%FAJA%' OR UPPER(c.name) LIKE '%CADENA%'
            ORDER BY a.name, e.tag, c.name
        """)).fetchall()

        if not rows:
            print("   [!] No se encontraron componentes FAJA o CADENA.\n")
            sys.exit(0)

        # Clasificar por tipo
        classified = []
        for r in rows:
            cname = r.component_name.upper()
            # Excluir componentes accesorios que no deben lubricarse
            # (ej. "GUARDA DE FAJA", "PROTECTOR DE CADENA")
            if 'GUARDA' in cname or 'PROTECTOR' in cname or 'CUBIERTA' in cname:
                continue
            if 'FAJA' in cname:
                classified.append(('FAJA', r))
            elif 'CADENA' in cname:
                classified.append(('CADENA', r))

        print(f"   Encontrados {len(classified)} componentes validos (excluyendo guardas/protectores)\n")

        # Resumen por area y tipo
        summary = defaultdict(lambda: Counter())
        for typ, r in classified:
            summary[r.area_name][typ] += 1
        print("   Desglose por area:")
        for area_name in sorted(summary.keys()):
            fajas = summary[area_name].get('FAJA', 0)
            cadenas = summary[area_name].get('CADENA', 0)
            print(f"     * {area_name:12s} -> {fajas} fajas, {cadenas} cadenas")

        # 2. Generar codigos y verificar cuales existen
        print("\n## PROPUESTA DE PUNTOS A CREAR ##")
        today = date.today()
        next_due = (today + timedelta(days=FREQUENCY_DAYS)).isoformat()
        to_create = []
        already_exist = []

        # Detectar duplicados por (equipo, tipo)
        key_counts = Counter()
        for typ, r in classified:
            key_counts[(r.equipment_id, typ)] += 1

        seen_counter = Counter()
        for typ, r in classified:
            cfg = TYPE_CONFIG[typ]
            key = (r.equipment_id, typ)
            seen_counter[key] += 1
            idx = seen_counter[key]
            total = key_counts[key]

            if total == 1:
                code = f"LUB-{r.equipment_tag}-{cfg['code_suffix']}"
                point_name = f"{cfg['point_name_prefix']} {r.equipment_tag}"
            else:
                code = f"LUB-{r.equipment_tag}-{cfg['code_suffix']}-{idx}"
                point_name = f"{cfg['point_name_prefix']} #{idx} {r.equipment_tag}"

            existing = db.session.execute(
                text("SELECT id FROM lubrication_points WHERE code = :c"),
                {"c": code}
            ).fetchone()

            if existing:
                already_exist.append((code, typ, r))
            else:
                to_create.append({
                    'code': code,
                    'name': point_name,
                    'task_name': cfg['task_name'],
                    'lubricant': cfg['lubricant'],
                    'unit': cfg['unit'],
                    'type': typ,
                    'row': r,
                })

        print(f"   -> {len(to_create)} puntos nuevos a crear")
        print(f"   -> {len(already_exist)} puntos ya existen (se omiten)")

        if already_exist:
            print("\n   Puntos existentes (muestra):")
            for code, typ, r in already_exist[:5]:
                print(f"     [EXISTE] {code:30s} | {typ:8s} | {r.area_name} / {r.equipment_tag}")
            if len(already_exist) > 5:
                print(f"     ... y {len(already_exist) - 5} mas")

        if not to_create:
            print("\n   [OK] No hay puntos nuevos que crear.\n")
            sys.exit(0)

        # Agrupar por area + tipo para reporte
        print("\n## PUNTOS NUEVOS A CREAR POR AREA ##")
        grouped = defaultdict(list)
        for item in to_create:
            grouped[(item['row'].area_name, item['type'])].append(item)

        for (area, typ), items in sorted(grouped.items()):
            print(f"\n  --- {area} / {typ} ({len(items)} puntos) ---")
            for it in items[:10]:
                r = it['row']
                print(f"     {it['code']:30s} | {r.equipment_tag:10s} | {it['lubricant']}")
            if len(items) > 10:
                print(f"     ... y {len(items) - 10} mas")

        if not APPLY:
            print("\n" + "=" * 72)
            print(" DRY-RUN: nada se modifico. Para aplicar, usar --apply")
            print("=" * 72 + "\n")
            sys.exit(0)

        # 3. APPLY
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
                'lubricant': item['lubricant'],
                'unit': item['unit'],
                'freq': FREQUENCY_DAYS,
                'warn': WARNING_DAYS,
                'due': next_due,
            })
            created_count += 1

        db.session.commit()
        print(f"\n   [OK] {created_count} puntos creados exitosamente")

        new_total = db.session.execute(
            text("SELECT count(*) FROM lubrication_points WHERE is_active = true")
        ).scalar()
        print(f"   Total puntos activos ahora: {new_total}\n")

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        print(f"\n   [X] ERROR: {e}\n")
        sys.exit(1)
    finally:
        db.session.remove()
