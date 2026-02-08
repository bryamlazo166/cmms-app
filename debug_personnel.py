
from app import app, db, Technician, WorkOrder, OTPersonnel
import sys

def check_data():
    with app.app_context():
        print("--- CHECKING TECHNICIANS ---")
        techs = Technician.query.all()
        for t in techs:
            print(f"ID: {t.id}, Name: {t.name}, Active: {t.is_active}")
        
        if not techs:
            print("WARNING: No technicians found in DB!")

        print("\n--- CHECKING WORK ORDERS ---")
        # Get one OT
        ot = WorkOrder.query.first()
        if not ot:
            print("WARNING: No Work Orders found!")
            return
        
        print(f"Testing with OT ID: {ot.id}")
        
        # Try to manually add personnel
        print("\n--- TESTING OTPersonnel INSERTION ---")
        try:
            # Pick first tech
            if techs:
                t = techs[0]
                print(f"Attempting to add Tech ID {t.id} to OT ID {ot.id}")
                
                # Check if already exists to avoid unique constraint if any (model doesn't show unique, but let's see)
                # cleanup first
                existing = OTPersonnel.query.filter_by(work_order_id=ot.id, technician_id=t.id).first()
                if existing:
                    print("Removing existing entry...")
                    db.session.delete(existing)
                    db.session.commit()
                
                new_p = OTPersonnel(
                    work_order_id=ot.id,
                    technician_id=t.id,
                    specialty='TEST_SPEC',
                    hours_assigned=10
                )
                db.session.add(new_p)
                db.session.commit()
                print("SUCCESS: Manually added personnel.")
            else:
                print("Cannot test insertion: No technicians.")
                
        except Exception as e:
            print(f"FAIL: Database insertion failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    check_data()
