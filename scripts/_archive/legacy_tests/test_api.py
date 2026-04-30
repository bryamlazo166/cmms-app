
import requests
import json

def test_api():
    url = "http://127.0.0.1:5003/api/work_orders/1/personnel"
    headers = {"Content-Type": "application/json"}
    
    # Payload similar to what frontend sends
    # Note: Frontend sends { personnel: [ { technician_id: "1", technician_name: "...", specialty: "...", hours: 8 } ] }
    payload = {
        "personnel": [
            {
                "technician_id": 1, 
                "technician_name": "JOSE MENESES",
                "specialty": "MECANICO",
                "hours": "8" # Send as string to test parsing
            }
        ]
    }
    
    print(f"Sending POST to {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        resp = requests.post(url, json=payload)
        print(f"Status Code: {resp.status_code}")
        print("Response Text:")
        print(resp.text)
    except Exception as e:
        print(f"Request Failed: {e}")

if __name__ == "__main__":
    test_api()
