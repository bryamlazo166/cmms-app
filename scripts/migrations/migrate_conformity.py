"""Migracion: agregar campos de Conformidad de Servicio a work_orders.

Agrega:
  - conformity_doc_url: VARCHAR(500) — link al PDF de conformidad firmado
    (Google Drive, OneDrive, etc.) Presencia = conformidad enviada a logistica.
  - conformity_uploaded_at: VARCHAR(20) — fecha en que se registro la URL.

Funciona en SQLite (local) y Postgres (Supabase).
"""
import os
import sys

# Permitir importar app.py desde el root del proyecto
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import text


def _column_exists(conn, table, column, dialect):
    if dialect == 'sqlite':
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    # Postgres
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {'t': table, 'c': column}).fetchall()
    return len(rows) > 0


def run():
    from app import app, db  # carga config y crea engine
    with app.app_context():
        engine = db.engine
        dialect = engine.dialect.name  # 'sqlite' o 'postgresql'
        print(f"DB dialect: {dialect}")

        columns = [
            ('conformity_doc_url', 'VARCHAR(500)'),
            ('conformity_uploaded_at', 'VARCHAR(20)'),
        ]

        with engine.begin() as conn:
            for col, col_type in columns:
                if _column_exists(conn, 'work_orders', col, dialect):
                    print(f"  - {col}: ya existe, omitiendo")
                    continue
                sql = f"ALTER TABLE work_orders ADD COLUMN {col} {col_type}"
                print(f"  + {col}: ejecutando {sql}")
                conn.execute(text(sql))
        print("Migracion completada.")


if __name__ == '__main__':
    run()
