#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Backup completo de Supabase PostgreSQL.

Genera 3 archivos en backups/YYYY-MM-DD_HHMMSS/:
  - schema.sql   : CREATE TABLE statements
  - data.json    : Todos los datos por tabla en JSON (legible)
  - data.sql     : INSERT statements (restauracion rapida)
  - summary.txt  : Resumen de tablas y filas

Restauracion rapida: psql ... < data.sql
Restauracion selectiva: leer data.json y filtrar tabla deseada
"""
import os
import sys
import json
import datetime as dt
from pathlib import Path
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print("ERROR: DATABASE_URL no esta en .env")
    sys.exit(1)

ROOT = Path(r"D:\PROGRAMACION\CMMS_Industrial\backups")
TS = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
OUT = ROOT / TS
OUT.mkdir(parents=True, exist_ok=True)


def json_default(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if hasattr(o, '__str__'):
        return str(o)
    raise TypeError(f"Type not serializable: {type(o)}")


def sql_value(v):
    """Format a value for inclusion in an INSERT statement."""
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return f"'{v.isoformat()}'"
    s = str(v).replace("'", "''")
    return f"'{s}'"


def main():
    print(f"Conectando a Supabase...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 1. Listar tablas en schema public
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [r['table_name'] for r in cur.fetchall()]
    print(f"Encontradas {len(tables)} tablas")

    summary = []
    full_data = {}
    schema_sql = []
    data_sql = []

    schema_sql.append(f"-- Schema dump generado el {TS}")
    schema_sql.append(f"-- Origen: {DB_URL.split('@')[1] if '@' in DB_URL else 'supabase'}")
    schema_sql.append("")

    data_sql.append(f"-- Data dump generado el {TS}")
    data_sql.append(f"-- Total tablas: {len(tables)}")
    data_sql.append("")

    for t in tables:
        # Esquema (CREATE TABLE)
        cur.execute("""
            SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (t,))
        cols = cur.fetchall()
        col_lines = []
        for c in cols:
            line = f"  {c['column_name']} {c['data_type']}"
            if c['character_maximum_length']:
                line += f"({c['character_maximum_length']})"
            if c['is_nullable'] == 'NO':
                line += " NOT NULL"
            if c['column_default']:
                line += f" DEFAULT {c['column_default']}"
            col_lines.append(line)
        schema_sql.append(f"-- Table: {t}")
        schema_sql.append(f"CREATE TABLE IF NOT EXISTS {t} (")
        schema_sql.append(",\n".join(col_lines))
        schema_sql.append(");")
        schema_sql.append("")

        # Datos
        cur.execute(f'SELECT * FROM "{t}"')
        rows = cur.fetchall()
        rows_list = [dict(r) for r in rows]
        full_data[t] = rows_list
        summary.append((t, len(rows_list)))
        print(f"  {t}: {len(rows_list)} filas")

        if rows_list:
            col_names = list(rows_list[0].keys())
            data_sql.append(f"-- Data: {t} ({len(rows_list)} rows)")
            for r in rows_list:
                vals = ", ".join(sql_value(r[c]) for c in col_names)
                col_str = ", ".join(f'"{c}"' for c in col_names)
                data_sql.append(f'INSERT INTO "{t}" ({col_str}) VALUES ({vals});')
            data_sql.append("")

    # Escribir archivos
    (OUT / "schema.sql").write_text("\n".join(schema_sql), encoding='utf-8')
    (OUT / "data.sql").write_text("\n".join(data_sql), encoding='utf-8')
    with open(OUT / "data.json", 'w', encoding='utf-8') as f:
        json.dump(full_data, f, indent=2, ensure_ascii=False, default=json_default)

    summary_lines = [
        f"Backup CMMS Industrial - {TS}",
        f"Origen: Supabase PostgreSQL",
        "=" * 50,
        f"Total tablas: {len(tables)}",
        f"Total filas: {sum(c for _, c in summary)}",
        "",
        "Detalle por tabla:",
    ]
    for t, c in sorted(summary, key=lambda x: -x[1]):
        summary_lines.append(f"  {c:>6}  {t}")

    (OUT / "summary.txt").write_text("\n".join(summary_lines), encoding='utf-8')

    cur.close()
    conn.close()

    # Tamanos
    sizes = {}
    for fname in ['schema.sql', 'data.sql', 'data.json', 'summary.txt']:
        p = OUT / fname
        sizes[fname] = p.stat().st_size

    print()
    print(f"Backup completo en: {OUT}")
    for fname, sz in sizes.items():
        kb = sz / 1024
        print(f"  {fname}: {kb:,.1f} KB")
    print()
    print(summary_lines[3])
    print(summary_lines[4])


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
