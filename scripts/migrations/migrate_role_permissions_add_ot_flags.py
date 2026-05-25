"""Migracion: agrega 2 flags granulares en role_permissions.

Antes: 8 flags (view, create, edit, delete, export, import, close, approve)
Despues: + can_edit_ot, can_adjust_hours

Estos 2 flags nuevos solo aplican al modulo "ordenes" y permiten
controlar especificamente los botones "Editar OT" (tabla planificacion)
y "Ajustar horas" (panel ejecucion en OT cerrada) sin acoplarlos a los
permisos genericos edit/close del modulo.

Inicializacion (para no romper permisos existentes):
  - can_edit_ot      = can_edit
  - can_adjust_hours = can_close

Funciona en SQLite (local) y Postgres (prod). Idempotente.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def migrate():
    from app import app
    from database import db
    from sqlalchemy import text, inspect

    new_cols = {
        'can_edit_ot':      'BOOLEAN DEFAULT FALSE',
        'can_adjust_hours': 'BOOLEAN DEFAULT FALSE',
    }

    with app.app_context():
        inspector = inspect(db.engine)
        existing = {c['name'] for c in inspector.get_columns('role_permissions')}
        added = []
        for col, ddl in new_cols.items():
            if col in existing:
                print(f"  [skip] {col} ya existe")
                continue
            print(f"  [add ] {col}")
            db.session.execute(text(f"ALTER TABLE role_permissions ADD COLUMN {col} {ddl}"))
            added.append(col)
        db.session.commit()

        if added:
            print("  [init] derivando valores iniciales...")
            # can_edit_ot = can_edit  (solo donde aplica)
            if 'can_edit_ot' in added:
                db.session.execute(text("""
                    UPDATE role_permissions
                    SET can_edit_ot = can_edit
                """))
            # can_adjust_hours = can_close
            if 'can_adjust_hours' in added:
                db.session.execute(text("""
                    UPDATE role_permissions
                    SET can_adjust_hours = can_close
                """))
            db.session.commit()
            print("  [done] valores derivados aplicados")

        print(f"OK - migracion completada. Columnas agregadas: {len(added)}")


if __name__ == '__main__':
    migrate()
