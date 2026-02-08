from app import app, db
from models import Area, Line, Equipment, System, Component

with app.app_context():
    print("--- AREAS ---")
    areas = Area.query.all()
    for a in areas:
        print(f"ID: {a.id}, Name: {a.name}")
        
    print("\n--- LINES ---")
    lines = Line.query.all()
    for l in lines:
        print(f"ID: {l.id}, Name: {l.name}, AreaID: {l.area_id}")
        
    print("\n--- EQUIPMENTS ---")
    equips = Equipment.query.all()
    for e in equips:
        print(f"ID: {e.id}, Name: {e.name}, LineID: {e.line_id}")
        
    print("\n--- SYSTEMS ---")
    systems = System.query.all()
    for s in systems:
        print(f"ID: {s.id}, Name: {s.name}, EquipID: {s.equipment_id}")
        
    print("\n--- COMPONENTS ---")
    comps = Component.query.all()
    for c in comps:
        print(f"ID: {c.id}, Name: {c.name}, SystemID: {c.system_id}")
