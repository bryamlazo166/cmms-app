
from app import app, db
from models import SparePart, WarehouseItem, WorkOrder

with app.app_context():
    sp_count = SparePart.query.count()
    wh_count = WarehouseItem.query.count()
    ot_count = WorkOrder.query.count()
    print(f"SparePart count: {sp_count}")
    print(f"WarehouseItem count: {wh_count}")
    print(f"WorkOrder count: {ot_count}")
