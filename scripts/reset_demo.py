"""Demo reset script: Resets database state to initial clean seed condition."""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def reset_demo():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set: Resetting in-memory test/demo store...")
        from app.db import reset_seed_data
        reset_seed_data()
        print("Demo reset completed successfully! In-memory store is in pristine seed state.")
        return

    print("Connecting to database for demo reset...")
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cursor = conn.cursor()

    try:
        print("Clearing transactional tables...")
        cursor.execute("DELETE FROM ratings;")
        cursor.execute("DELETE FROM trip_locations;")
        cursor.execute("DELETE FROM trips;")
        cursor.execute("DELETE FROM driver_responses;")
        cursor.execute("DELETE FROM decision_log;")
        cursor.execute("DELETE FROM notifications;")
        cursor.execute("DELETE FROM bookings;")

        print("Resetting vehicles and drivers status to available...")
        cursor.execute("UPDATE vehicles SET status = 'available', maintenance_until = NULL;")
        cursor.execute("UPDATE drivers SET status = 'available';")

        print("Re-applying seed data from 003_seed.sql...")
        seed_path = os.path.join(os.path.dirname(__file__), "..", "migrations", "003_seed.sql")
        with open(seed_path, "r", encoding="utf-8") as f:
            seed_sql = f.read()

        cursor.execute(seed_sql)
        conn.commit()
        print("Demo reset completed successfully! Database is in pristine seed state.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR during demo reset: {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    reset_demo()
