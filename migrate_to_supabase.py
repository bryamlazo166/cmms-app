import os
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import argparse
import sys

# Load env variables
load_dotenv()

# Default Local Supabase URL
LOCAL_SUPABASE_URL = "postgresql://postgres:postgres@localhost:54322/postgres"

def create_tables(db_url):
    """
    Initialize the database schema using the Flask app context.
    """
    print(f"--- Creating Tables in {db_url} ---")
    
    # Temporarily set env var if not set, so app.py picks it up
    # We need to make sure app.py uses this specific URL
    os.environ['DATABASE_URL'] = db_url
    
    try:
        from app import app, db
        # Force config update
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        
        with app.app_context():
            db.create_all()
            print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def migrate(target_url, verify_ssl=True):
    sqlite_db = 'cmms_v2.db'
    print(f"--- Starting Migration: SQLite ({sqlite_db}) -> Postgres ---")
    
    if not os.path.exists(sqlite_db):
        print(f"Error: {sqlite_db} not found.")
        return

    # Connect to SQLite
    try:
        sqlite_conn = sqlite3.connect(sqlite_db)
        sqlite_cursor = sqlite_conn.cursor()
        print(f"Connected to SQLite")
    except Exception as e:
        print(f"Error connecting to SQLite: {e}")
        return

    # Connect to Postgres
    try:
        # Determine SSL mode. Local usually doesn't need it.
        sslmode = 'require' if verify_ssl else 'disable'
        if 'localhost' in target_url or '127.0.0.1' in target_url:
            sslmode = 'disable'
            
        pg_conn = psycopg2.connect(target_url, sslmode=sslmode)
        pg_cursor = pg_conn.cursor()
        print("Connected to Postgres")
    except Exception as e:
        print(f"Error connecting to Postgres: {e}")
        return

    # 1. Get List of Tables from SQLite
    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in sqlite_cursor.fetchall() if row[0] != 'sqlite_sequence']
    
    # 2. Iterate and Copy Data
    for table in tables:
        print(f"\nProcessing Table: {table}")
        
        # Get data from SQLite
        try:
            sqlite_cursor.execute(f"SELECT * FROM {table}")
            rows = sqlite_cursor.fetchall()
            
            if not rows:
                print(f"  - No data in {table}. Skipping.")
                continue
                
            # Get columns to build INSERT query
            col_names = [description[0] for description in sqlite_cursor.description]
            cols_str = ', '.join(col_names)
            placeholders = ', '.join(['%s'] * len(col_names))
            
            insert_query = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            
            print(f"  - Migrating {len(rows)} rows...")
            
            # Execute Batch Insert
            execute_values(pg_cursor, insert_query, rows)
            pg_conn.commit()
            print(f"  - Success.")
            
        except Exception as e:
            print(f"  - Error migrating {table}: {e}")
            pg_conn.rollback()

    print("\n--- Migration Complete ---")
    sqlite_conn.close()
    pg_conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite to Supabase/Postgres")
    parser.add_argument("--local", action="store_true", help="Use default local Supabase URL")
    parser.add_argument("--create-tables", action="store_true", help="Create tables in target DB before migrating")
    parser.add_argument("--url", type=str, help="Target Database URL (overrides .env)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    
    args = parser.parse_args()
    
    # Determine Target URL
    target_url = args.url or os.getenv('DATABASE_URL')
    
    if args.local:
        if not args.url and not os.getenv('DATABASE_URL'):
             target_url = LOCAL_SUPABASE_URL
        elif args.url is None: # If local flag is on but no URL provided, prioritize local default if env var is suspicious? 
             # Simpler: if --local is passed, we prefer local default unless --url is explicit.
             target_url = LOCAL_SUPABASE_URL

    if not target_url:
        print("Error: No DATABASE_URL found. Set it in .env, pass --url, or use --local")
        sys.exit(1)
        
    print(f"Target Database: {target_url}") 
    
    if args.create_tables:
        create_tables(target_url)
        
    if args.yes:
        migrate(target_url, verify_ssl=not args.local)
    else:
        confirm = input("Proceed with migration? (y/n): ")
        if confirm.lower() == 'y':
            migrate(target_url, verify_ssl=not args.local)
        else:
            print("Cancelled.")
