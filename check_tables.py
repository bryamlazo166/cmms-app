
import sqlite3

try:
    conn = sqlite3.connect('instance/cmms_v2.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print(cursor.fetchall())
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
