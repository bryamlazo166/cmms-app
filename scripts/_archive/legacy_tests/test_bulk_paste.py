import requests
import unittest

BASE_URL = "http://127.0.0.1:5000/api"

class TestBulkPaste(unittest.TestCase):
    
    def setUp(self):
        # Reset DB before tests
        requests.post(f"http://127.0.0.1:5000/api/initialize")

    def test_bulk_paste_areas(self):
        print("\nTesting Bulk Paste: Areas...")
        raw = "Name\tDescription\nAreaTest1\tDesc1\nAreaTest2\tDesc2"
        payload = {
            "entity_type": "Areas",
            "raw_data": raw
        }
        res = requests.post(f"{BASE_URL}/bulk-paste", json=payload)
        self.assertEqual(res.status_code, 201)
        
        # Verify
        areas = requests.get(f"{BASE_URL}/areas").json()
        self.assertEqual(len(areas), 2)
        print("Areas OK")

    def test_bulk_paste_hierarchy(self):
        print("\nTesting Bulk Paste: Full Hierarchy...")
        
        # 1. Area
        requests.post(f"{BASE_URL}/bulk-paste", json={"entity_type": "Areas", "raw_data": "Name\nPlant1"})
        
        # 2. Line
        requests.post(f"{BASE_URL}/bulk-paste", json={"entity_type": "Lines", "raw_data": "Name\tAreaName\nLine1\tPlant1"})
        
        # 3. Equipment
        requests.post(f"{BASE_URL}/bulk-paste", json={"entity_type": "Equipments", "raw_data": "Name\tTag\tLineName\tAreaName\nPump1\tP-01\tLine1\tPlant1"})
        
        # Verify Equipment
        equips = requests.get(f"{BASE_URL}/equipments").json()
        self.assertEqual(len(equips), 1)
        self.assertEqual(equips[0]['name'], 'Pump1')
        print("Hierarchy OK")

if __name__ == '__main__':
    unittest.main()
