
import sys
import os
import pandas as pd
from io import BytesIO

# Add project root to path
sys.path.append(os.path.abspath('d:\\PROGRAMACION\\CMMS_Industrial'))

from app import app, db, WarehouseItem

def test_export_full():
    print("Starting Internal Export Test...")
    
    # Ensure app context
    with app.app_context():
        # Check if we have items
        count = WarehouseItem.query.count()
        print(f"Database contains {count} warehouse items.")
        
        with app.test_client() as client:
            print("Requesting /api/warehouse/export...")
            response = client.get('/api/warehouse/export')
            
            print(f"Status Code: {response.status_code}")
            print(f"Content-Type: {response.content_type}")
            
            if response.status_code != 200:
                print(f"ERROR BODY: {response.data.decode('utf-8')}")
                return
            
            # Try to save and read
            content = response.data
            print(f"Response Size: {len(content)} bytes")
            
            try:
                # Validate it is a valid excel
                df = pd.read_excel(BytesIO(content))
                print("\nSUCCESS: File generated and parsed correctly.")
                print("Columns found:", df.columns.tolist())
                print(f"Rows in Excel: {len(df)}")
                
                # Save for manual inspection if needed
                with open("internal_test_export.xlsx", "wb") as f:
                    f.write(content)
                print("Saved to 'internal_test_export.xlsx'")
                
            except Exception as e:
                print(f"\nCRITICAL FAILURE: Response is not a valid Excel file. Error: {e}")
                print("First 100 bytes of response:", content[:100])

if __name__ == "__main__":
    test_export_full()
