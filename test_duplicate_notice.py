
import requests
import json

BASE_URL = 'http://localhost:5000'

def test_duplicate_detection():
    # 1. Get an Equipment ID (assuming one exists or create dummy)
    # For now let's assumes we can get one or fail if none
    try:
        equip_res = requests.get(f'{BASE_URL}/api/equipments')
        equips = equip_res.json()
        if not equips:
            print("No equipments found. Cannot test.")
            return
        
        target_equip_id = equips[0]['id']
        print(f"Testing with Equipment ID: {target_equip_id}")
        
        # 2. Create First Notice
        notice_data = {
            "equipment_id": target_equip_id,
            "description": "Test Notice Original",
            "reporter_name": "Tester",
            "status": "Pendiente"
        }
        
        print("Creating First Notice...")
        r1 = requests.post(f'{BASE_URL}/api/notices', json=notice_data)
        print(f"Response 1: {r1.status_code}")
        print(r1.json())
        
        # 3. Create Duplicate Notice
        print("Creating Duplicate Notice...")
        r2 = requests.post(f'{BASE_URL}/api/notices', json=notice_data)
        print(f"Response 2: {r2.status_code}")
        res2_json = r2.json()
        print(res2_json)
        
        if res2_json.get('is_duplicate'):
            print("SUCCESS: Duplicate Detected!")
            print(f"Reason: {res2_json.get('duplicate_reason')}")
        else:
            print("FAILURE: Duplicate NOT Detected.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test_duplicate_detection()
