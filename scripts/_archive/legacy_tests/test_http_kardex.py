"""Test Kardex HTTP Download"""
import requests

try:
    r = requests.get('http://127.0.0.1:5003/api/warehouse/export-kardex', timeout=10)
    print(f'Status: {r.status_code}')
    print(f'Content-Type: {r.headers.get("Content-Type", "N/A")}')
    print(f'Size: {len(r.content)} bytes')
    
    if r.status_code == 200:
        with open('downloaded_kardex.xlsx', 'wb') as f:
            f.write(r.content)
        print('SUCCESS: Saved to downloaded_kardex.xlsx')
    else:
        print(f'ERROR Response: {r.text[:500]}')
except Exception as e:
    print(f'Exception: {e}')
