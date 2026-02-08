"""Test Kardex Export"""
from app import app
from models import WarehouseMovement

with app.app_context():
    movs = WarehouseMovement.query.all()
    print(f"Total movements in DB: {len(movs)}")
    
    # Test the export
    client = app.test_client()
    response = client.get('/api/warehouse/export-kardex')
    
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.content_type}")
    print(f"Response Size: {len(response.data)} bytes")
    
    if response.status_code == 200:
        with open('test_kardex_export.xlsx', 'wb') as f:
            f.write(response.data)
        print("SUCCESS: Kardex exported to test_kardex_export.xlsx")
    else:
        print(f"ERROR: {response.data.decode()}")
