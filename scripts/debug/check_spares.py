from app import app, db
from models import SparePart

with app.app_context():
    items = SparePart.query.all()
    print(f"Total Repuestos en BD: {len(items)}")
    for i in items:
        print(f"- {i.name} (ID: {i.id}, Código: {i.code})")
