"""Actualiza los espesores nominal/alarma/scrap del trípode interno de los digestores.

Datos confirmados por el cliente:
- Eje secundario y refuerzo del trípode: tubo 4" SCH 160, espesor de pared 13.49 mm
- Paletas: plancha 3/4" = 19.05 mm

Nuevos umbrales:
| Grupo    | Nominal (mm) | Alarma (mm) | Scrap (mm) |
|----------|--------------|-------------|------------|
| PALETA   | 19.05        | 12.0        | 8.0        |
| REFUERZO | 13.49        | 10.0        | 8.0        |
| EJE      | 13.49        | 10.0        | 8.0        |

Uso:
    python -m scripts.seeds.update_tripode_specs            # dry-run (no escribe)
    python -m scripts.seeds.update_tripode_specs --apply    # aplica cambios
"""
import os
import sys

os.environ.setdefault('DB_MODE', 'supabase')
os.environ.setdefault('DATABASE_URL',
    'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require')
os.environ.setdefault('SUPABASE_PROBE_TIMEOUT_SEC', '5')
os.environ.setdefault('ALLOW_LOCAL_FALLBACK', '0')
os.environ.setdefault('SUPABASE_URL', 'https://zxgksjwszqqvwoyfrekw.supabase.co')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'x')

from app import app, db
from sqlalchemy import text

NEW_SPECS = {
    'PALETA':   {'nominal': 19.05, 'alarm': 12.0, 'scrap': 8.0},
    'REFUERZO': {'nominal': 13.49, 'alarm': 10.0, 'scrap': 8.0},
    'EJE':      {'nominal': 13.49, 'alarm': 10.0, 'scrap': 8.0},
}


def main(apply_changes: bool):
    mode = 'APLICANDO CAMBIOS' if apply_changes else 'DRY-RUN (no escribe)'
    print(f"\n=== {mode} ===\n")

    with app.app_context():
        rows = db.session.execute(text("""
            SELECT group_name,
                   COUNT(*)                                   AS n_points,
                   ROUND(AVG(nominal_thickness)::numeric, 2)  AS avg_nominal,
                   ROUND(AVG(alarm_thickness)::numeric, 2)    AS avg_alarm,
                   ROUND(AVG(scrap_thickness)::numeric, 2)    AS avg_scrap
            FROM thickness_points
            WHERE group_name IN ('PALETA', 'REFUERZO', 'EJE')
              AND is_active = true
            GROUP BY group_name
            ORDER BY group_name
        """)).fetchall()

        print(f"{'GRUPO':<10} {'PUNTOS':<8} {'NOM ACTUAL':<12} {'NOM NUEVO':<12} "
              f"{'ALA ACT':<10} {'ALA NUE':<10} {'SCR ACT':<10} {'SCR NUE':<10}")
        print('-' * 90)
        total = 0
        for g, n, an, aa, asc in rows:
            spec = NEW_SPECS[g]
            print(f"{g:<10} {n:<8} {float(an):<12} {spec['nominal']:<12} "
                  f"{float(aa):<10} {spec['alarm']:<10} {float(asc):<10} {spec['scrap']:<10}")
            total += n

        print(f"\nTotal de puntos a actualizar: {total}")

        if not apply_changes:
            print("\nEsto es un dry-run. Para aplicar: python -m scripts.seeds.update_tripode_specs --apply")
            return

        for g, spec in NEW_SPECS.items():
            res = db.session.execute(text("""
                UPDATE thickness_points
                SET nominal_thickness = :nom,
                    alarm_thickness   = :alm,
                    scrap_thickness   = :scr
                WHERE group_name = :g
                  AND is_active = true
            """), {
                'nom': spec['nominal'],
                'alm': spec['alarm'],
                'scr': spec['scrap'],
                'g': g,
            })
            print(f"  {g}: {res.rowcount} puntos actualizados")

        # Recalcular status de cada punto en base al nuevo umbral
        # CRITICO si last_value <= scrap, ALERTA si <= alarm, NORMAL si no
        db.session.execute(text("""
            UPDATE thickness_points
            SET status = CASE
                WHEN last_value IS NULL THEN 'NORMAL'
                WHEN last_value <= scrap_thickness THEN 'CRITICO'
                WHEN last_value <= alarm_thickness THEN 'ALERTA'
                ELSE 'NORMAL'
            END
            WHERE group_name IN ('PALETA', 'REFUERZO', 'EJE')
              AND is_active = true
        """))

        db.session.commit()
        print("\nCambios aplicados correctamente.")


if __name__ == '__main__':
    apply_flag = '--apply' in sys.argv
    main(apply_flag)
