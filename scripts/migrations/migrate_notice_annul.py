
import sqlite3
import os

DB_PATH = os.path.join(os.getcwd(), 'instance', 'cmms_v2.db')

def migrate_db():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database {DB_PATH} not found.")
        return

    print(f"Migrating database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    col_name = 'cancellation_reason'
    col_type = 'TEXT'

    try:
        print(f"Adding column: {col_name}...")
        cursor.execute(f"ALTER TABLE maintenance_notices ADD COLUMN {col_name} {col_type}")
        print(f"Column {col_name} added successfully.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"Column {col_name} already exists. Skipping.")
        else:
            print(f"Error adding column {col_name}: {e}")
    
    conn.commit()
    conn.close()
    print("Migration finished.")

if __name__ == '__main__':
    migrate_db()
