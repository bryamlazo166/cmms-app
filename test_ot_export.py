"""Verification of OT Export and Failure Mode"""
import requests
import pandas as pd
from io import BytesIO

url = 'http://127.0.0.1:5004/api/export-ots'

try:
    print(f"Testing URL: {url}")
    r = requests.get(url, timeout=5)
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('Content-Type')}")
    
    if r.status_code == 200:
        xls = pd.ExcelFile(BytesIO(r.content))
        df = pd.read_excel(xls, 'OrdenesTrabajo')
        print(f"Columns Found: {list(df.columns)}")
        
        if 'Modo de Falla' in df.columns:
            print("SUCCESS: 'Modo de Falla' column found inside Excel.")
        else:
            print("ERROR: 'Modo de Falla' column NOT found.")
            
        with open('ot_export_test.xlsx', 'wb') as f:
            f.write(r.content)
            
    else:
        print(f"Error Response: {r.text[:200]}")

except Exception as e:
    print(f"Exception: {e}")
