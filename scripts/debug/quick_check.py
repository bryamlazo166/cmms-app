
import sqlite3

try:
    conn = sqlite3.connect('instance/cmms_v2.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT count(*) FROM spare_parts")
    sp_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT count(*) FROM warehouse_items")
    wh_count = cursor.fetchone()[0]
    
    print(f"SpareParts: {sp_count}")
    print(f"WarehouseItems: {wh_count}")
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
