
import sqlite3
import os

DB_PATH = os.path.join(os.getcwd(), 'instance', 'cmms_v2.db')

def inspect_db():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database {DB_PATH} not found.")
        return

    print(f"Inspecting database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(warehouse_items)")
        columns = cursor.fetchall()
        print("Columns in warehouse_items:")
        for col in columns:
            print(f"- {col[1]} ({col[2]})")
            
    except Exception as e:
        print(f"Error: {e}")
    
    conn.close()

if __name__ == '__main__':
    inspect_db()
