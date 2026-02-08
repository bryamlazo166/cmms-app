"""Migration Script to add failure_mode column"""
import sqlite3

db_path = 'instance/cmms_v2.db'

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(work_orders)")
    columns = [info[1] for info in cursor.fetchall()]
    
    if 'failure_mode' not in columns:
        print("Adding failure_mode column...")
        cursor.execute("ALTER TABLE work_orders ADD COLUMN failure_mode TEXT")
        conn.commit()
        print("Migration successful.")
    else:
        print("Column already exists.")
        
    conn.close()
except Exception as e:
    print(f"Migration failed: {e}")
