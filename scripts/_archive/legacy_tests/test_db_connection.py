import psycopg2
import urllib.parse
import sys
import socket

HOST = "db.zxgksjwszqqvwoyfrekw.supabase.co"
PORT = "5432"
DB = "postgres"
USER = "postgres"

passwords_to_try = [
    "Bryamlazo16"
]

def test_connection():
    print("--- Testing Supabase Connection ---")
    
    # Force IPv4
    try:
        ip_list = socket.getaddrinfo(HOST, 5432, socket.AF_INET)
        ipv4 = ip_list[0][4][0]
        print(f"Resolved {HOST} to IPv4: {ipv4}")
    except Exception as e:
        print(f"Could not resolve to IPv4: {e}")
        return

    for pwd in passwords_to_try:
        # Encode password
        encoded_pwd = urllib.parse.quote_plus(pwd)
        # Use IP directly to bypass IPv6
        uri = f"postgresql://{USER}:{encoded_pwd}@{ipv4}:{PORT}/{DB}"
        
        print(f"Testing password: '{pwd}' ... ", end="")
        try:
            conn = psycopg2.connect(uri)
            conn.close()
            print("SUCCESS!")
            print(f"\nVALID PASSWORD FOUND: {pwd}")
            print(f"Update your .env with: DATABASE_URL=postgresql://{USER}:{encoded_pwd}@{ipv4}:{PORT}/{DB}")
            return
        except psycopg2.OperationalError as e:
            print(f"Failed (OperationalError): {e}")
        except Exception as e:
             print(f"Failed ({type(e).__name__}): {e}")

    print("\nNo valid password found in list.")

if __name__ == "__main__":
    test_connection()
