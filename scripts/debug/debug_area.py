import requests

def debug_area_creation():
    url = "http://localhost:5000/api/areas"
    payload = {"name": "Test Area Debug"}
    try:
        print(f"Sending POST to {url} with {payload}")
        res = requests.post(url, json=payload)
        print(f"Status Code: {res.status_code}")
        print(f"Response: {res.text}")
        
        if res.status_code == 201:
            print("Backend Works! Issue is likely in Frontend.")
        else:
            print("Backend Failure.")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    debug_area_creation()
