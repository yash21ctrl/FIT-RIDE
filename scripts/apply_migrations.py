"""Script to apply SQL migrations in order against DATABASE_URL."""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def apply_migrations():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set in environment or .env file.")
        sys.exit(1)

    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    migration_files = ["001_schema.sql", "002_constraints.sql", "003_seed.sql"]

    print(f"Connecting to database: {database_url.split('@')[-1] if '@' in database_url else 'DATABASE_URL'}")
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cursor = conn.cursor()

    try:
        for filename in migration_files:
            filepath = os.path.join(migrations_dir, filename)
            if not os.path.exists(filepath):
                print(f"Skipping missing migration: {filename}")
                continue

            print(f"Applying migration: {filename}...")
            with open(filepath, "r", encoding="utf-8") as f:
                sql = f.read()

            cursor.execute(sql)
            conn.commit()
            print(f"  Successfully applied: {filename}")

        print("All migrations applied successfully!")
    except Exception as e:
        conn.rollback()
        print(f"ERROR applying migrations: {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    apply_migrations()
