import requests
import json

BASE_URL = 'http://127.0.0.1:5006/api'

def check_endpoint(name):
    try:
        url = f"{BASE_URL}/{name}"
        print(f"Fetching {url}...")
        r = requests.get(url)
        if r.status_code == 200:
            data = r.json()
            print(f"--- {name.upper()} ({len(data)} items) ---")
            if data:
                print(f"First item keys: {list(data[0].keys())}")
                print(f"First item sample: {data[0]}")
            else:
                print("Empty list.")
        else:
            print(f"Error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Exception: {e}")

check_endpoint('areas')
check_endpoint('lines')
check_endpoint('equipments')
check_endpoint('systems')
check_endpoint('components')
