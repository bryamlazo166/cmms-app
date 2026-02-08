import urllib.request
import urllib.parse
import json
import traceback

BASE_URL = "http://localhost:5006"

def request(method, endpoint, data=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    
    if data:
        data_bytes = json.dumps(data).encode('utf-8')
    else:
        data_bytes = None
        
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        print(f"Request failed: {e}")
        return 0, None

def test_add_material():
    print("--- Testing Add Material Backend Logic (urllib) ---")
    
    import random
    code = f"TSP-{random.randint(10000,99999)}"
    
    # 1. Create Item
    print(f"Creating Item: {code}")
    status, item = request('POST', '/api/warehouse', {
        "name": "Test Part Urllib",
        "code": code,
        "stock": 10,
        "unit_cost": 25.0
    })
    
    if status != 201:
        print("Failed to create item:", item)
        return
    item_id = item['id']
    print(f"Item Created: ID {item_id}")

    # 2. Create OT
    print("Creating OT...")
    status, ot = request('POST', '/api/work-orders', {
        "description": "OT Test Urllib",
        "maintenance_type": "Preventivo",
        "status": "Abierta"
    })
    
    if status != 201:
        print("Failed to create OT:", ot)
        return
    ot_id = ot['id']
    print(f"OT Created: ID {ot_id}")

    # 3. Test Success
    print("\nTest 1: Adding 5 items (Valid)...")
    status, res = request('POST', f"/api/work_orders/{ot_id}/materials", {
        "item_type": "warehouse",
        "item_id": item_id,
        "quantity": 5
    })
    
    if status == 201:
        print("PASS: Material added.")
    else:
        print(f"FAIL: {status} - {res}")

    # Verify Stock
    status, items = request('GET', '/api/warehouse?all=true')
    updated = next((i for i in items if i['id'] == item_id), None)
    if updated and updated['stock'] == 5:
         print("PASS: Stock deducted 10 -> 5.")
    else:
         print(f"FAIL: Stock is {updated['stock'] if updated else 'N/A'}")

    # 4. Test Invalid Qty
    print("\nTest 2: Adding 0 items...")
    status, res = request('POST', f"/api/work_orders/{ot_id}/materials", {
         "item_type": "warehouse", 
         "item_id": item_id, 
         "quantity": 0
    })
    if status == 400: print("PASS: Rejected 0 qty.")
    else: print(f"FAIL: {status} - {res}")

    # 5. Test Insufficient Stock
    print("\nTest 3: Insufficient Stock (Ask 10, Have 5)...")
    status, res = request('POST', f"/api/work_orders/{ot_id}/materials", {
         "item_type": "warehouse", 
         "item_id": item_id, 
         "quantity": 10
    })
    if status == 400 and "insuficiente" in str(res).lower(): print("PASS: Rejected insufficient stock.")
    else: print(f"FAIL: {status} - {res}")

if __name__ == "__main__":
    test_add_material()
