import requests
import json

BASE_URL = "http://localhost:5006"

def test_add_material():
    print("--- Testing Add Material Backend Logic ---")
    
    # 1. Create a dummy Warehouse Item
    item_data = {
        "name": "Test Spare Part",
        "code": "TSP-001",
        "stock": 10,
        "min_stock": 2,
        "unit_cost": 50.0
    }
    # Check if exists first to avoidunique constraint error if re-running
    # Actually, let's just make a unique code
    import random
    item_data['code'] = f"TSP-{random.randint(1000,9999)}"
    
    print(f"Creating Item: {item_data['code']} with Stock 10")
    res = requests.post(f"{BASE_URL}/api/warehouse", json=item_data)
    if not res.ok:
        print("Failed to create item:", res.text)
        return
    item = res.json()
    item_id = item['id']
    
    # 2. Create a dummy OT
    ot_data = {
        "description": "OT for Material Test",
        "maintenance_type": "Correctivo",
        "status": "Abierta"
    }
    print("Creating OT...")
    res = requests.post(f"{BASE_URL}/api/work-orders", json=ot_data)
    if not res.ok:
        print("Failed to create OT:", res.text)
        return
    ot = res.json()
    ot_id = ot['id']
    
    # 3. Test Success Case (Add 2 items)
    print("\nTest 1: Adding 2 items (Valid)...")
    payload = {
        "item_type": "warehouse",
        "item_id": item_id,
        "quantity": 2
    }
    res = requests.post(f"{BASE_URL}/api/work_orders/{ot_id}/materials", json=payload)
    if res.ok:
        print("PASS: Material added successfully.")
    else:
        print("FAIL: Could not add material:", res.text)
        
    # Verify Stock Deduction
    res = requests.get(f"{BASE_URL}/api/warehouse")
    items = res.json()
    updated_item = next((i for i in items if i['id'] == item_id), None)
    if updated_item and updated_item['stock'] == 8:
        print("PASS: Stock deducted correctly (10 - 2 = 8).")
    else:
        print(f"FAIL: Stock not deducted correctly. Expected 8, got {updated_item['stock'] if updated_item else 'None'}")

    # 4. Test Error Case: Invalid Quantity (0)
    print("\nTest 2: Adding 0 items (Invalid)...")
    payload['quantity'] = 0
    res = requests.post(f"{BASE_URL}/api/work_orders/{ot_id}/materials", json=payload)
    if res.status_code == 400 and "positive integer" in res.text:
         print("PASS: Rejected invalid quantity correctly.")
    else:
         print(f"FAIL: Unexpected response for qty=0: {res.status_code} - {res.text}")

    # 5. Test Error Case: Insufficient Stock (Try adding 20, have 8)
    print("\nTest 3: Insufficient Stock (Try 20, Have 8)...")
    payload['quantity'] = 20
    res = requests.post(f"{BASE_URL}/api/work_orders/{ot_id}/materials", json=payload)
    if res.status_code == 400 and "insuficiente" in res.text.lower():
        print("PASS: Rejected insufficient stock correctly.")
    else:
        print(f"FAIL: Failed to detect insufficient stock. Status: {res.status_code}, Resp: {res.text}")
        
    print("\n--- End Test ---")

if __name__ == "__main__":
    try:
        test_add_material()
    except Exception as e:
        print(f"Test Execution Failed: {e}")
