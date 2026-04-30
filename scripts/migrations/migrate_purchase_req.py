
import sqlite3

try:
    conn = sqlite3.connect('instance/cmms_v2.db')
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(purchase_request)")
    cols = [info[1] for info in cursor.fetchall()]
    
    if 'warehouse_item_id' not in cols:
        print("Adding warehouse_item_id column to purchase_request...")
        cursor.execute("ALTER TABLE purchase_request ADD COLUMN warehouse_item_id INTEGER REFERENCES warehouse_items(id)")
        print("Done.")
    else:
        print("Column already exists.")
        
    conn.commit()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
