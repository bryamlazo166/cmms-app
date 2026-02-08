import requests

BASE_URL = 'http://127.0.0.1:5006/api'

def get_data(endpoint):
    return requests.get(f"{BASE_URL}/{endpoint}").json()

areas = get_data('areas')
lines = get_data('lines')
equips = get_data('equipments')
systems = get_data('systems')
comps = get_data('components')

print(f"Loaded {len(areas)} areas, {len(lines)} lines.")

for area in areas:
    print(f"Area: {area['name']} (ID: {area['id']})")
    area_lines = [l for l in lines if l['area_id'] == area['id']]
    print(f"  -> Found {len(area_lines)} lines.")
    
    for line in area_lines:
        print(f"  Line: {line['name']} (ID: {line['id']})")
        line_equips = [e for e in equips if e['line_id'] == line['id']]
        print(f"    -> Found {len(line_equips)} equipments.")
        
        for eq in line_equips:
            print(f"    Equip: {eq['name']}")
