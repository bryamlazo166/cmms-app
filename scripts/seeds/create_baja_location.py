#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Crea la ubicacion tecnica 'BAJA / FUERA DE SERVICIO' directamente via SQL."""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv('DATABASE_URL') or 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'

AREA_NAME = "BAJA / FUERA DE SERVICIO"
LINE_NAME = "EQUIPOS DE BAJA"
EQ_NAME = "ARCHIVO BAJA"
EQ_TAG = "BAJA"
SYSTEM_NAME = "ACTIVOS RETIRADOS"

COMPONENTS = [
    "MOTOR ELECTRICO",
    "CAJA REDUCTORA",
    "MOTORREDUCTOR",
    "HIDROLAVADORA",
    "BOMBA DE LODOS",
    "BOMBA TORRE DE ENFRIAMIENTO",
    "BOMBA CENTRIFUGA",
    "OTROS",
]


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("SELECT id FROM areas WHERE name = %s", (AREA_NAME,))
    row = cur.fetchone()
    if row:
        area_id = row[0]
        print(f"[=] Area existente: {AREA_NAME} (id={area_id})")
    else:
        cur.execute(
            "INSERT INTO areas (name, description) VALUES (%s, %s) RETURNING id",
            (AREA_NAME, "Ubicacion tecnica para activos dados de baja"),
        )
        area_id = cur.fetchone()[0]
        print(f"[+] Area creada: {AREA_NAME} (id={area_id})")

    cur.execute("SELECT id FROM lines WHERE area_id = %s AND name = %s", (area_id, LINE_NAME))
    row = cur.fetchone()
    if row:
        line_id = row[0]
        print(f"[=] Linea existente: {LINE_NAME} (id={line_id})")
    else:
        cur.execute(
            "INSERT INTO lines (area_id, name) VALUES (%s, %s) RETURNING id",
            (area_id, LINE_NAME),
        )
        line_id = cur.fetchone()[0]
        print(f"[+] Linea creada: {LINE_NAME} (id={line_id})")

    cur.execute("SELECT id FROM equipments WHERE line_id = %s AND tag = %s", (line_id, EQ_TAG))
    row = cur.fetchone()
    if row:
        eq_id = row[0]
        print(f"[=] Equipo existente: {EQ_NAME} [{EQ_TAG}] (id={eq_id})")
    else:
        cur.execute(
            "INSERT INTO equipments (line_id, name, tag, criticality, description) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (line_id, EQ_NAME, EQ_TAG, 'Baja', 'Ubicacion de archivo para equipos retirados'),
        )
        eq_id = cur.fetchone()[0]
        print(f"[+] Equipo creado: {EQ_NAME} [{EQ_TAG}] (id={eq_id})")

    cur.execute("SELECT id FROM systems WHERE equipment_id = %s AND name = %s", (eq_id, SYSTEM_NAME))
    row = cur.fetchone()
    if row:
        sys_id = row[0]
        print(f"[=] Sistema existente: {SYSTEM_NAME} (id={sys_id})")
    else:
        cur.execute(
            "INSERT INTO systems (equipment_id, name) VALUES (%s, %s) RETURNING id",
            (eq_id, SYSTEM_NAME),
        )
        sys_id = cur.fetchone()[0]
        print(f"[+] Sistema creado: {SYSTEM_NAME} (id={sys_id})")

    cur.execute("SELECT name FROM components WHERE system_id = %s", (sys_id,))
    existing = {r[0] for r in cur.fetchall()}
    created = 0
    for cname in COMPONENTS:
        if cname in existing:
            continue
        cur.execute(
            "INSERT INTO components (system_id, name, criticality, description) VALUES (%s, %s, %s, %s)",
            (sys_id, cname, 'Baja', 'Slot para activos retirados de este tipo'),
        )
        created += 1
    if created:
        print(f"[+] Componentes creados: {created}")
    else:
        print(f"[=] Todos los componentes ya existen")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDONE. Ubicacion BAJA: Area={area_id}, Linea={line_id}, Equipo={eq_id}, Sistema={sys_id}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
