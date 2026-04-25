"""Migracion: extender role_permissions con 5 flags nuevos.

Antes:  can_view, can_edit, can_export
Despues: can_view, can_create, can_edit, can_delete, can_export,
         can_import, can_close, can_approve

Funciona tanto en SQLite (local dev) como Postgres (prod). Si el
campo ya existe se omite. Inicializa los nuevos flags derivandolos
del flag can_edit existente para no romper permisos actuales.
"""
import sys
import os

# Asegurar que importamos la app del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def migrate():
    from app import app
    from database import db
    from sqlalchemy import text, inspect

    new_cols = {
        'can_create':  'BOOLEAN DEFAULT FALSE',
        'can_delete':  'BOOLEAN DEFAULT FALSE',
        'can_import':  'BOOLEAN DEFAULT FALSE',
        'can_close':   'BOOLEAN DEFAULT FALSE',
        'can_approve': 'BOOLEAN DEFAULT FALSE',
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
            # Inicializar valores derivando del can_edit:
            # can_create / can_delete / can_close / can_approve = can_edit
            # can_import = false (lo activan manualmente)
            print("  [init] derivando valores iniciales de can_edit...")
            db.session.execute(text("""
                UPDATE role_permissions
                SET can_create = can_edit,
                    can_delete = can_edit,
                    can_close  = can_edit,
                    can_approve = can_edit
                WHERE can_edit = TRUE
            """))
            db.session.commit()
            print("  [done] valores derivados aplicados")

        print(f"OK - migracion completada. Columnas agregadas: {len(added)}")


if __name__ == '__main__':
    migrate()
