
import requests
import json

BASE_URL = 'http://localhost:5000'

def test_filter_apis():
    endpoints = ['areas', 'lines', 'equipments']
    
    for ep in endpoints:
        try:
            url = f'{BASE_URL}/api/{ep}'
            print(f"Testing {url}...")
            res = requests.get(url)
            
            if res.status_code == 200:
                data = res.json()
                print(f"✅ {ep.capitalize()}: {len(data)} items found.")
                if len(data) > 0:
                    print(f"   Sample: {data[0]['name']}")
            else:
                print(f"❌ {ep.capitalize()}: Failed with status {res.status_code}")
                
        except Exception as e:
            print(f"❌ {ep.capitalize()}: Error {e}")

if __name__ == '__main__':
    test_filter_apis()
