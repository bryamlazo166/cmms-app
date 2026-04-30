"""Agrega el Sistema Electrico con 12 componentes estandar a todos los equipos.

Idempotente: si el sistema ya existe en un equipo, no lo duplica;
si faltan componentes, los agrega. No borra nada.

Uso: python add_electrical_system.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from database import db
from models import Equipment, System, Component

SYSTEM_NAME = "SISTEMA ELECTRICO"

COMPONENTS = [
    ("INTERRUPTOR / BREAKER", "Termomagnetico principal"),
    ("CONTACTOR", "Contactor de potencia"),
    ("RELE TERMICO", "Proteccion contra sobrecarga"),
    ("RELE AUXILIAR", "Control y enclavamiento"),
    ("ARRANCADOR SUAVE", "Softstarter (si aplica)"),
    ("VARIADOR DE FRECUENCIA", "VFD (si aplica)"),
    ("BOTONERA / PULSADORES", "Marcha, paro, emergencia"),
    ("SENSORES", "PT100, presion, nivel, proximidad"),
    ("MOTOR ELECTRICO", "Bobinado, caja de bornes"),
    ("CABLEADO / CANALIZACION", "Cables, bandejas, conduit, borneras"),
    ("PUESTA A TIERRA", "Cable, pica, barras equipotenciales"),
    ("TABLERO DE CONTROL", "Gabinete, luces piloto, selectores, ventilacion"),
]


def run():
    with app.app_context():
        equipos = Equipment.query.order_by(Equipment.id).all()
        total_eq = len(equipos)
        created_sys = 0
        created_comp = 0
        skipped_comp = 0

        for eq in equipos:
            sis = System.query.filter_by(equipment_id=eq.id, name=SYSTEM_NAME).first()
            if not sis:
                sis = System(name=SYSTEM_NAME, equipment_id=eq.id)
                db.session.add(sis)
                db.session.flush()
                created_sys += 1

            existing = {c.name for c in Component.query.filter_by(system_id=sis.id).all()}
            for cname, cdesc in COMPONENTS:
                if cname in existing:
                    skipped_comp += 1
                    continue
                db.session.add(Component(
                    name=cname,
                    description=cdesc,
                    system_id=sis.id,
                    criticality='Media',
                ))
                created_comp += 1

        db.session.commit()
        print(f"Equipos procesados: {total_eq}")
        print(f"Sistemas creados:   {created_sys}")
        print(f"Componentes creados: {created_comp}")
        print(f"Componentes ya existentes (omitidos): {skipped_comp}")


if __name__ == '__main__':
    run()
