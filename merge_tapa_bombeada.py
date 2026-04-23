"""Detecta pares duplicados 'TAPA BOMBEADA CONDUCIDA' + 'TAPA BOMBEADA CONDUCIDO'
dentro del MISMO sistema de un equipo, mueve todas las referencias al que se
conserva ('CONDUCIDO') y borra el duplicado ('CONDUCIDA').

El conservado es 'CONDUCIDO' (decision del usuario).

Tablas que se migran del componente duplicado al conservado:
  - thickness_points
  - lubrication_points
  - monitoring_points
  - maintenance_notices    (historial)
  - work_orders            (historial)
  - component_specs
  - spare_parts
  - rotative_assets
  - rotative_asset_history
  - photo_attachments (entity_type='component')
  - document_links    (entity_type='component')

Uso:
  python merge_tapa_bombeada.py          -> DRY-RUN (solo reporte)
  python merge_tapa_bombeada.py --apply  -> ejecuta merge real
"""
import os
import sys

os.environ['DB_MODE'] = 'supabase'
os.environ['DATABASE_URL'] = 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ['SUPABASE_PROBE_TIMEOUT_SEC'] = '5'
os.environ['ALLOW_LOCAL_FALLBACK'] = '0'

from app import app, db
from sqlalchemy import text


APPLY = '--apply' in sys.argv

# Definicion del merge:
#   KEEP   = nombre del componente que se conserva
#   DROP   = nombre del componente que se borra (sus refs se mueven al KEEP)
KEEP = 'TAPA BOMBEADA CONDUCIDO'
DROP = 'TAPA BOMBEADA CONDUCIDA'


# Tablas con FK component_id directa
FK_TABLES = [
    'thickness_points',
    'lubrication_points',
    'monitoring_points',
    'maintenance_notices',
    'work_orders',
    'component_specs',
    'spare_parts',
    'rotative_assets',
    'rotative_asset_history',
]
# Tablas con entity_type + entity_id (polimorficas)
ENTITY_TABLES = [
    'photo_attachments',
    'document_links',
]


with app.app_context():
    print(f"\n{'=' * 72}")
    print(f" MERGE DE COMPONENTES DUPLICADOS")
    print(f" KEEP (se conserva): {KEEP}")
    print(f" DROP (se borra):    {DROP}")
    print(f" MODO: {'APLICAR' if APPLY else 'DRY-RUN (sin cambios)'}")
    print(f"{'=' * 72}\n")

    try:
        # 1. Buscar todos los pares dentro del mismo sistema
        pairs = db.session.execute(text("""
            SELECT
                c1.id    AS keep_id,
                c1.name  AS keep_name,
                c2.id    AS drop_id,
                c2.name  AS drop_name,
                s.id     AS system_id,
                s.name   AS system_name,
                e.tag    AS equip_tag,
                e.name   AS equip_name,
                a.name   AS area_name
            FROM components c1
            JOIN components c2 ON c2.system_id = c1.system_id
                              AND UPPER(c2.name) = :drop_name
            JOIN systems s    ON c1.system_id = s.id
            JOIN equipments e ON s.equipment_id = e.id
            JOIN lines l      ON e.line_id = l.id
            JOIN areas a      ON l.area_id = a.id
            WHERE UPPER(c1.name) = :keep_name
            ORDER BY a.name, e.tag, s.name
        """), {"keep_name": KEEP, "drop_name": DROP}).fetchall()

        if not pairs:
            print("   [!] No se encontraron pares duplicados. Nada que hacer.\n")
            sys.exit(0)

        print(f"## PARES DUPLICADOS ENCONTRADOS: {len(pairs)} ##\n")
        total_moves = 0
        per_pair_details = []

        for row in pairs:
            details = {
                'keep_id': row.keep_id,
                'drop_id': row.drop_id,
                'equip_tag': row.equip_tag,
                'system_name': row.system_name,
                'area_name': row.area_name,
                'moves': {},
            }
            # Contar refs en cada tabla para el DROP
            for tbl in FK_TABLES:
                cnt = db.session.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE component_id = :d"),
                    {"d": row.drop_id}
                ).scalar()
                if cnt:
                    details['moves'][tbl] = cnt
                    total_moves += cnt

            for tbl in ENTITY_TABLES:
                cnt = db.session.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE entity_type = 'component' AND entity_id = :d"),
                    {"d": row.drop_id}
                ).scalar()
                if cnt:
                    details['moves'][tbl] = cnt
                    total_moves += cnt

            per_pair_details.append(details)

            # Imprimir por par
            move_str = ', '.join(f"{k}={v}" for k, v in details['moves'].items()) or '(sin referencias)'
            print(f"   {row.area_name:10s} / {row.equip_tag:10s} / {row.system_name:25s}")
            print(f"     KEEP id={row.keep_id}   DROP id={row.drop_id}")
            print(f"     Referencias a mover: {move_str}")
            print()

        print(f"## TOTAL DE REFERENCIAS A MOVER: {total_moves} ##\n")

        if not APPLY:
            print("=" * 72)
            print(" DRY-RUN completado. Revisa el reporte.")
            print(" Para aplicar realmente: python merge_tapa_bombeada.py --apply")
            print("=" * 72 + "\n")
            sys.exit(0)

        # 2. APLICAR: mover referencias y borrar duplicados
        print("## EJECUTANDO MERGE ##\n")
        moved_total = 0
        deleted_total = 0

        for d in per_pair_details:
            keep_id = d['keep_id']
            drop_id = d['drop_id']
            print(f"  {d['area_name']} / {d['equip_tag']} / {d['system_name']}")

            for tbl in FK_TABLES:
                r = db.session.execute(text(
                    f"UPDATE {tbl} SET component_id = :k WHERE component_id = :d"
                ), {"k": keep_id, "d": drop_id})
                if r.rowcount:
                    print(f"     {tbl}: {r.rowcount} refs movidas")
                    moved_total += r.rowcount

            for tbl in ENTITY_TABLES:
                r = db.session.execute(text(
                    f"UPDATE {tbl} SET entity_id = :k WHERE entity_type = 'component' AND entity_id = :d"
                ), {"k": keep_id, "d": drop_id})
                if r.rowcount:
                    print(f"     {tbl}: {r.rowcount} refs movidas")
                    moved_total += r.rowcount

            # Borrar el componente duplicado
            r = db.session.execute(text("DELETE FROM components WHERE id = :d"),
                                   {"d": drop_id})
            if r.rowcount:
                print(f"     [OK] componente id={drop_id} eliminado")
                deleted_total += 1

            db.session.commit()

        print(f"\n## RESUMEN ##")
        print(f"   Componentes duplicados eliminados: {deleted_total}")
        print(f"   Referencias migradas: {moved_total}\n")

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        print(f"\n   [X] ERROR: {e}\n")
        sys.exit(1)
    finally:
        db.session.remove()
