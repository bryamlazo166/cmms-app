import psycopg2
import sys

PROJECT_REF = "zxgksjwszqqvwoyfrekw"
PASSWORD = "Bryamlazo16"
DB_NAME = "postgres"

# Common Supabase Regions
REGIONS = [
    "us-east-1",
    "sa-east-1", # South America
    "eu-central-1",
    "ap-southeast-1",
    "us-west-1",
    "eu-west-1",
    "eu-west-2",
    "ap-northeast-1",
    "ap-northeast-2",
    "ca-central-1",
    "ap-south-1" 
]

def probe_pooler():
    print(f"--- Probing Poolers for Project: {PROJECT_REF} ---")
    
    for region in REGIONS:
        host = f"aws-0-{region}.pooler.supabase.com"
        port = "6543"
        # Pooler username format: postgres.[ref]
        user = f"postgres.{PROJECT_REF}"
        
        uri = f"postgresql://{user}:{PASSWORD}@{host}:{port}/{DB_NAME}"
        
        print(f"Trying region: {region} ({host})... ", end="")
        try:
            conn = psycopg2.connect(uri, connect_timeout=3)
            conn.close()
            print("SUCCESS! Connected.")
            print(f"\nFOUND VALID CONNECTION!")
            print(f"URL: {uri}")
            return uri
        except psycopg2.OperationalError as e:
            if "password" in str(e).lower():
                print("Auth failed (Host reached!)")
                # If auth failed, it means we reached the host but maybe user format is different?
                # Or simply wrong password? But password worked before? 
                # Actually, if we reach the host and get auth error, that's better than timeout.
            else:
                print("Timeout/Unreachable")
        except Exception as e:
            print(f"Error: {e}")
            
    print("\nCould not find a working pooler.")

if __name__ == "__main__":
    probe_pooler()
