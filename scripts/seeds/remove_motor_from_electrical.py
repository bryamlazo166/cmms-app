"""Elimina MOTOR ELECTRICO del SISTEMA ELECTRICO en todos los equipos,
siempre y cuando no tenga OTs, avisos, specs ni repuestos asociados.

Uso: python remove_motor_from_electrical.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from database import db
from sqlalchemy import text
from models import System, Component


def run():
    with app.app_context():
        targets = db.session.query(Component).join(System).filter(
            System.name == 'SISTEMA ELECTRICO',
            Component.name == 'MOTOR ELECTRICO',
        ).all()

        deleted = 0
        blocked = []
        for comp in targets:
            cid = comp.id
            wo_count = db.session.execute(
                text("SELECT count(*) FROM work_orders WHERE component_id = :c"), {"c": cid}
            ).scalar() or 0
            av_count = db.session.execute(
                text("SELECT count(*) FROM maintenance_notices WHERE component_id = :c"), {"c": cid}
            ).scalar() or 0
            sp_count = db.session.execute(
                text("SELECT count(*) FROM spare_parts WHERE component_id = :c"), {"c": cid}
            ).scalar() or 0
            spec_count = db.session.execute(
                text("SELECT count(*) FROM component_specs WHERE component_id = :c"), {"c": cid}
            ).scalar() or 0

            if wo_count or av_count or sp_count or spec_count:
                eq_name = db.session.execute(
                    text("SELECT e.tag FROM systems s JOIN equipments e ON s.equipment_id=e.id WHERE s.id=:sid"),
                    {"sid": comp.system_id},
                ).scalar()
                blocked.append((eq_name, wo_count, av_count, sp_count, spec_count))
                continue

            db.session.delete(comp)
            deleted += 1

        db.session.commit()
        print(f"MOTOR ELECTRICO eliminados de SISTEMA ELECTRICO: {deleted}")
        print(f"Equipos con referencias (no borrados): {len(blocked)}")
        for b in blocked:
            print(f"  {b[0]}: OTs={b[1]}, avisos={b[2]}, repuestos={b[3]}, specs={b[4]}")


if __name__ == '__main__':
    run()
