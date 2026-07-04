#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Borra los Motor electrico placeholder que se crearon por error en los TH.

Los TH solo deben tener Motorreductor. El script anterior
(bulk_create_lub_motors.py --apply --only-motors --th-only) creo 44 registros
con codigos RA-0001 a RA-0044. De esos, los Motor electrico son incorrectos
y deben borrarse; los Motorreductor se conservan.

Identificacion segura del scope: codigo entre RA-0001 y RA-0044
AND category = 'Motor electrico'
AND notes LIKE 'Placeholder generado%' (extra-safety).

Uso:
    python scripts/cleanup_wrong_motors.py            # DRY RUN
    python scripts/cleanup_wrong_motors.py --apply    # BORRA
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from app import app  # noqa: E402
from database import db  # noqa: E402
from models import RotativeAsset, Equipment  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true',
                        help='Aplica el borrado. Sin esta flag es DRY RUN.')
    args = parser.parse_args()

    with app.app_context():
        # Buscar candidatos: codigos RA-0001..RA-0044 con categoria Motor electrico
        # y notes de placeholder (3 capas de filtro defensivo).
        codes = [f"RA-{i:04d}" for i in range(1, 45)]
        candidates = (
            RotativeAsset.query
            .filter(RotativeAsset.code.in_(codes))
            .filter(RotativeAsset.category == 'Motor electrico')
            .filter(RotativeAsset.notes.like('Placeholder generado%'))
            .all()
        )

        mode = 'APPLY (borra de BD)' if args.apply else 'DRY RUN (no borra)'
        print(f"=== cleanup_wrong_motors.py === {mode}")
        print(f"Candidatos a borrar: {len(candidates)}\n")
        print(f"  {'Codigo':<10} {'Equipo':<32} {'Categoria':<22}")
        print(f"  {'-'*10} {'-'*32} {'-'*22}")
        for ra in sorted(candidates, key=lambda x: x.code):
            eq = Equipment.query.get(ra.equipment_id) if ra.equipment_id else None
            eq_name = eq.name if eq else '(sin equipo)'
            print(f"  {ra.code:<10} {eq_name[:32]:<32} {ra.category:<22}")

        if not candidates:
            print("\n(nada que borrar)")
            return

        if args.apply:
            for ra in candidates:
                db.session.delete(ra)
            db.session.commit()
            print(f"\n[OK] {len(candidates)} registros borrados.")
        else:
            db.session.rollback()
            print(f"\n[DRY-RUN] {len(candidates)} registros NO borrados.")
            print("Para aplicar, repite con --apply.")


if __name__ == '__main__':
    main()
