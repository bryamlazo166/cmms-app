
import requests
import json

url = "http://localhost:5003/api/warehouse"
data = {
    "name": "Test Item New Schema",
    "family": "Rodamientos",
    "brand": "SKF",
    "manufacturer_code": "123-REF",
    "criticality": "Alta",
    "average_cost": 50.5,
    "stock": 10
}

try:
    res = requests.post(url, json=data)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
except Exception as e:
    print(f"Error: {e}")
