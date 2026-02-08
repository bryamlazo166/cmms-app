import requests
import time

BASE_URL = 'http://127.0.0.1:5000'

def test_persistence():
    print("--- Starting Persistence Test ---")
    
    # 0. Initialize DB (just in case)
    try:
        requests.post(f"{BASE_URL}/api/initialize")
    except Exception as e:
        print(f"Server not running? {e}")
        return

    # 1. Create Location
    loc_data = {
        "name": f"Test Location {int(time.time())}",
        "description": "Created by automated test"
    }
    print(f"Sending Location: {loc_data}")
    
    res_loc = requests.post(f"{BASE_URL}/api/locations", json=loc_data)
    if res_loc.status_code == 201:
        loc_id = res_loc.json()['id']
        print(f"Location Created (ID: {loc_id})")
    else:
        print(f"Failed to create location: {res_loc.text}")
        return

    # 2. Immediate Fetch
    res_fetch = requests.get(f"{BASE_URL}/api/locations")
    locations = res_fetch.json()
    
    found = any(l['id'] == loc_id for l in locations)
    
    if found:
        print("SUCCESS: Location found in DB via API.")
    else:
        print("FAILURE: Location created but NOT found via API.")

if __name__ == "__main__":
    test_persistence()
