#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Migracion: agregar columnas attended y replacement_for_id a ot_personnel."""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print("ERROR: DATABASE_URL no esta en .env")
    sys.exit(1)


def col_exists(cur, table, column):
    cur.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s AND column_name=%s
    """, (table, column))
    return cur.fetchone() is not None


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    if not col_exists(cur, 'ot_personnel', 'attended'):
        cur.execute("ALTER TABLE ot_personnel ADD COLUMN attended BOOLEAN")
        print("[+] Columna 'attended' agregada")
    else:
        print("[=] Columna 'attended' ya existe")

    if not col_exists(cur, 'ot_personnel', 'replacement_for_id'):
        cur.execute("""
            ALTER TABLE ot_personnel
            ADD COLUMN replacement_for_id INTEGER REFERENCES ot_personnel(id)
        """)
        print("[+] Columna 'replacement_for_id' agregada")
    else:
        print("[=] Columna 'replacement_for_id' ya existe")

    conn.commit()
    cur.close()
    conn.close()
    print("\nDONE.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
