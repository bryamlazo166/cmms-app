import requests
import pandas as pd
import io
import os

# Configuration
BASE_URL = "http://localhost:5000"

def create_complex_excel():
    # Create DataFrames with duplicate names in different branches
    
    # Areas: "Plant A", "Plant B"
    areas_df = pd.DataFrame([
        {'Name': 'Plant A', 'Description': 'Main Plant'},
        {'Name': 'Plant B', 'Description': 'Secondary Plant'}
    ])
    
    # Lines: "Line 1" in both plants
    lines_df = pd.DataFrame([
        {'Name': 'Line 1', 'Description': 'L1 in Plant A', 'AreaName': 'Plant A'},
        {'Name': 'Line 1', 'Description': 'L1 in Plant B', 'AreaName': 'Plant B'}
    ])
    
    # Equipments: "Pump X" in both Lines
    equipments_df = pd.DataFrame([
        {'Name': 'Pump X', 'Tag': 'P-001', 'Description': 'Pump in A-L1', 'LineName': 'Line 1', 'AreaName': 'Plant A'},
        {'Name': 'Pump X', 'Tag': 'P-002', 'Description': 'Pump in B-L1', 'LineName': 'Line 1', 'AreaName': 'Plant B'}
    ])
    
    # Systems: "Hydraulic" in both Pumps
    systems_df = pd.DataFrame([
        {'Name': 'Hydraulic', 'EquipmentName': 'Pump X', 'LineName': 'Line 1', 'AreaName': 'Plant A'},
        {'Name': 'Hydraulic', 'EquipmentName': 'Pump X', 'LineName': 'Line 1', 'AreaName': 'Plant B'}
    ])
    
    # Components: "Valve" in both Systems
    components_df = pd.DataFrame([
        {'Name': 'Valve', 'Description': 'V1', 'SystemName': 'Hydraulic', 'EquipmentName': 'Pump X', 'LineName': 'Line 1', 'AreaName': 'Plant A'},
        {'Name': 'Valve', 'Description': 'V2', 'SystemName': 'Hydraulic', 'EquipmentName': 'Pump X', 'LineName': 'Line 1', 'AreaName': 'Plant B'}
    ])
    
    # SpareParts: "Seal" in both Valves
    spares_df = pd.DataFrame([
        {'Name': 'Seal', 'Code': 'S-100', 'Brand': 'BrandX', 'Quantity': 10, 'ComponentName': 'Valve', 'SystemName': 'Hydraulic', 'EquipmentName': 'Pump X', 'LineName': 'Line 1', 'AreaName': 'Plant A'},
        {'Name': 'Seal', 'Code': 'S-200', 'Brand': 'BrandY', 'Quantity': 5, 'ComponentName': 'Valve', 'SystemName': 'Hydraulic', 'EquipmentName': 'Pump X', 'LineName': 'Line 1', 'AreaName': 'Plant B'}
    ])
    
    # Write to BytesIO
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        areas_df.to_excel(writer, sheet_name='Areas', index=False)
        lines_df.to_excel(writer, sheet_name='Lines', index=False)
        equipments_df.to_excel(writer, sheet_name='Equipments', index=False)
        systems_df.to_excel(writer, sheet_name='Systems', index=False)
        components_df.to_excel(writer, sheet_name='Components', index=False)
        spares_df.to_excel(writer, sheet_name='SpareParts', index=False)
        
    output.seek(0)
    return output

def test_upload():
    print("--- 1. Resetting DB ---")
    requests.post(f"{BASE_URL}/api/initialize")
    
    print("--- 2. Creating Complex Excel ---")
    excel_file = create_complex_excel()
    
    print("--- 3. Uploading Excel ---")
    files = {'file': ('complex_test.xlsx', excel_file, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    res = requests.post(f"{BASE_URL}/api/upload-excel", files=files)
    print(f"Upload Status: {res.status_code}")
    print(f"Upload Response: {res.text}")
    
    if res.status_code != 201:
        print("FAIL: Upload failed")
        return

    print("--- 4. Verifying Hierarchy ---")
    
    # Verify Areas
    areas = requests.get(f"{BASE_URL}/api/areas").json()
    print(f"Areas count: {len(areas)} (Expected 2)")
    
    # Verify Lines
    lines = requests.get(f"{BASE_URL}/api/lines").json()
    print(f"Lines count: {len(lines)} (Expected 2)")
    
    for line in lines:
        # Check parent area
        area = next(a for a in areas if a['id'] == line['area_id'])
        print(f"Line '{line['name']}' belongs to Area '{area['name']}'")
        
    # Verify Equipments
    equips = requests.get(f"{BASE_URL}/api/equipments").json()
    print(f"Equipments count: {len(equips)} (Expected 2)")
    
    for eq in equips:
        line = next(l for l in lines if l['id'] == eq['line_id'])
        area = next(a for a in areas if a['id'] == line['area_id'])
        print(f"Equipment '{eq['name']}' (Tag: {eq['tag']}) belongs to Line '{line['name']}' in Area '{area['name']}'")

    # Verify Spare Parts
    spares = requests.get(f"{BASE_URL}/api/spare-parts").json()
    print(f"Spare Parts count: {len(spares)} (Expected 2)")
    for sp in spares:
        # Trace back up (requires manually fetching parents as API returns IDs)
        # For brevity, trusting the structure if counts match and parents are distinct
        print(f"Spare '{sp['name']}' Code '{sp['code']}' component_id: {sp['component_id']}")

if __name__ == "__main__":
    test_upload()
