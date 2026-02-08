import requests
import json
import datetime

BASE_URL = "http://localhost:5003/api"

def log(msg, color="white"):
    print(f"[{datetime.datetime.now().time()}] {msg}")

def test_ot_flow():
    session = requests.Session()
    
    # 1. Create or Get Provider
    log("1. Checking Providers...")
    res = session.get(f"{BASE_URL}/providers")
    providers = res.json()
    if not providers:
        log("No providers found, creating one...")
        res = session.post(f"{BASE_URL}/providers", json={
            "name": "Proveedor Test",
            "specialty": "General",
            "contact_info": "123456"
        })
        provider_id = res.json()['id']
    else:
        provider_id = providers[0]['id']
    log(f"Using Provider ID: {provider_id}")

    # 2. Create Maintenance Notice
    log("2. Creating Maintenance Notice...")
    notice_data = {
        "reporter_name": "Juan Test",
        "description": "Fallo en motor principal - Test Flow",
        "priority": "Alta",
        "criticality": "Alta",
        "maintenance_type": "Correctivo",
        "request_date": datetime.datetime.now().isoformat()[:10],
        "status": "Pendiente"
    }
    res = session.post(f"{BASE_URL}/notices", json=notice_data)
    if res.status_code != 201:
        log(f"Error creating notice: {res.text}")
        return
    notice = res.json()
    notice_id = notice['id']
    log(f"Notice Created: AV-{notice_id} (Code: {notice.get('code')})")

    # 3. Create OT from Notice
    log("3. Creating Work Order from Notice...")
    ot_data = {
        "notice_id": notice_id,
        "description": "Reparación de Motor - OT Test",
        "maintenance_type": "Correctivo",
        "priority": "Alta",
        "status": "Abierta",
        "technician_id": "Tecnico Test",
        "estimated_duration": 4.0
    }
    res = session.post(f"{BASE_URL}/work-orders", json=ot_data)
    if res.status_code != 201:
        log(f"Error creating OT: {res.text}")
        return
    ot = res.json()
    ot_id = ot['id']
    log(f"OT Created: OT-{ot_id} (Code: {ot.get('code')})")

    # 4. Add Material (Tool)
    log("4. Adding Tool to OT...")
    # Ensure a tool exists or just use a dummy ID if we don't validate strictly (app does validate)
    # Let's create a tool first to be safe
    tool_res = session.post(f"{BASE_URL}/tools", json={
        "name": "Taladro Test",
        "category": "Electrica",
        "status": "Disponible"
    })
    if tool_res.status_code == 201:
        tool_id = tool_res.json()['id']
        mat_data = {
            "item_type": "tool",
            "item_id": tool_id,
            "quantity": 1
        }
        res = session.post(f"{BASE_URL}/work_orders/{ot_id}/materials", json=mat_data)
        log(f"Material Add Status: {res.status_code}")
    
    # 5. Start Execution
    log("5. Starting Execution (Abierta -> En Progreso)...")
    res = session.put(f"{BASE_URL}/work-orders/{ot_id}", json={
        "status": "En Progreso",
        "real_start_date": datetime.datetime.now().isoformat()
    })
    if res.status_code == 200:
        log("OT Status updated to 'En Progreso'")
    else:
        log(f"Failed to start OT: {res.text}")

    # Check Notice Status
    res = session.get(f"{BASE_URL}/notices/{notice_id}")
    notice = res.json()
    if notice['status'] == 'En Progreso':
        log("Notice correctly updated to 'En Progreso'")
    else:
        log(f"WARNING: Notice status is {notice['status']}, expected 'En Progreso'")

    # 6. Close OT
    log("6. Closing OT...")
    res = session.put(f"{BASE_URL}/work-orders/{ot_id}", json={
        "status": "Cerrada",
        "real_end_date": datetime.datetime.now().isoformat(),
        "execution_comments": "Reparación exitosa"
    })
    
    # 7. Final Verification
    res = session.get(f"{BASE_URL}/notices/{notice_id}")
    notice = res.json()
    log(f"Final Notice Status: {notice['status']}")
    
    if notice['status'] == 'Cerrado':  # Note: backend uses 'Cerrado' or 'Cerrada'? App uses 'Cerrado' for notices.
        log("SUCCESS: Full Flow Verified!")
    else:
        log(f"FAILURE: Notice not closed. Status: {notice['status']}")

if __name__ == "__main__":
    test_ot_flow()
