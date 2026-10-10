"""Test script to verify exclusion constraint behavior (error 23P01 and 15-minute buffer)."""
import os
import sys
import psycopg2
import psycopg2.errors
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

def test_exclusion_constraint():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set.")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()

    vehicle_id = "00000000-0000-0000-0001-000000000001" # Maruti Swift
    employee_id = "00000000-0000-0000-0003-000000000001" # Ananya Roy

    now_utc = datetime.now(timezone.utc)
    base_time = now_utc + timedelta(days=10) # 10 days in future to avoid existing bookings

    start_a = base_time.replace(hour=10, minute=0, second=0, microsecond=0)
    end_a = base_time.replace(hour=11, minute=0, second=0, microsecond=0)
    blocked_a = end_a + timedelta(minutes=15) # 11:15

    # Overlapping slot: 10:30 to 11:30
    start_b = base_time.replace(hour=10, minute=30, second=0, microsecond=0)
    end_b = base_time.replace(hour=11, minute=30, second=0, microsecond=0)
    blocked_b = end_b + timedelta(minutes=15)

    # Back-to-back slot: starts at 11:15 (right after blocked_until of A)
    start_c = base_time.replace(hour=11, minute=15, second=0, microsecond=0)
    end_c = base_time.replace(hour=12, minute=15, second=0, microsecond=0)
    blocked_c = end_c + timedelta(minutes=15)

    booking_ids_created = []

    try:
        print("1. Inserting Booking A (10:00 - 11:00, blocked until 11:15, PENDING)...")
        cursor.execute("""
            INSERT INTO bookings (
                employee_id, vehicle_id, start_time, end_time, blocked_until,
                destination, passengers, reason, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
            RETURNING id;
        """, (employee_id, vehicle_id, start_a, end_a, blocked_a, "Test Dest A", 2, "Test Reason A"))
        id_a = cursor.fetchone()[0]
        booking_ids_created.append(id_a)
        conn.commit()
        print(f"   Booking A inserted successfully: {id_a}")

        print("\n2. Attempting to insert overlapping Booking B (10:30 - 11:30, PENDING)...")
        overlap_failed_with_23p01 = False
        try:
            cursor.execute("""
                INSERT INTO bookings (
                    employee_id, vehicle_id, start_time, end_time, blocked_until,
                    destination, passengers, reason, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                RETURNING id;
            """, (employee_id, vehicle_id, start_b, end_b, blocked_b, "Test Dest B", 2, "Test Reason B"))
            conn.commit()
            print("   ERROR: Overlapping booking was NOT rejected!")
        except psycopg2.Error as e:
            conn.rollback()
            print(f"   Caught expected database exception: pgcode={e.pgcode}, msg={e.pgerror.strip() if e.pgerror else e}")
            if e.pgcode == "23P01":
                overlap_failed_with_23p01 = True
                print("   SUCCESS: Database rejected overlap with error code 23P01 (exclusion_violation)!")

        assert overlap_failed_with_23p01, "Test failed: Overlapping booking did NOT raise 23P01!"

        print("\n3. Inserting back-to-back Booking C (11:15 - 12:15, starting at 11:15 with 15-min gap, PENDING)...")
        cursor.execute("""
            INSERT INTO bookings (
                employee_id, vehicle_id, start_time, end_time, blocked_until,
                destination, passengers, reason, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
            RETURNING id;
        """, (employee_id, vehicle_id, start_c, end_c, blocked_c, "Test Dest C", 2, "Test Reason C"))
        id_c = cursor.fetchone()[0]
        booking_ids_created.append(id_c)
        conn.commit()
        print(f"   Booking C inserted successfully: {id_c}")

        print("\nALL EXCLUSION CONSTRAINT CHECKS PASSED PERFECTLY!")

    finally:
        # Clean up test rows
        if booking_ids_created:
            print("\nCleaning up test records...")
            cursor.execute("DELETE FROM bookings WHERE id = ANY(%s);", (booking_ids_created,))
            conn.commit()
        cursor.close()
        conn.close()

if __name__ == "__main__":
    test_exclusion_constraint()
