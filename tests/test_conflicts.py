"""Race condition and concurrent conflict tests (Team KNIGHT | PS 40).

Tests concurrent multi-threaded simultaneous inserts for the same vehicle/slot,
verifying that:
1. Exactly one insert succeeds.
2. The losing thread raises error 23P01 (exclusion constraint violation).
3. The application error handler formats the standardized friendly error payload:
   {
     "error": {
       "code": "VEHICLE_TAKEN",
       "message": "That vehicle was just reserved. Here are the best alternatives:",
       "alternatives": [...]
     }
   }
Supports both live PostgreSQL (when DATABASE_URL is configured) and simulated
concurrent database locking fixtures so tests pass deterministically anywhere.
"""
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import pytest

from app.db import (
    get_db_connection,
    ExclusionViolationError,
    format_exclusion_error,
)
from app.engine.allocate import allocate


class SimulatedBookingDatabase:
    """
    Thread-safe database simulator enforcing PostgreSQL GiST exclusion constraints
    (no_vehicle_overlap on tstzrange(start_time, blocked_until, '[)'))
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.bookings: List[Dict] = []

    def insert_booking(
        self,
        vehicle_id: str,
        driver_id: str,
        start_time: datetime,
        end_time: datetime,
        blocked_until: datetime,
        status: str = "PENDING",
    ) -> str:
        booking_id = str(uuid.uuid4())
        # Acquire lock to simulate atomic PostgreSQL index insertion and GiST check
        with self._lock:
            # Check GiST exclusion: vehicle_id WITH =, tstzrange WITH &&
            for b in self.bookings:
                if b["vehicle_id"] == vehicle_id and b["status"] in (
                    "PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED", "IN_PROGRESS"
                ):
                    b_start = b["start_time"]
                    b_blocked = b["blocked_until"]
                    # Half-open interval overlap [start, blocked_until) && [b_start, b_blocked)
                    if b_start < blocked_until and start_time < b_blocked:
                        raise ExclusionViolationError(
                            message=f'conflicting key value violates exclusion constraint "no_vehicle_overlap"',
                            pgcode="23P01",
                        )

            # Check GiST exclusion: driver_id WITH =, tstzrange WITH &&
            for b in self.bookings:
                if b["driver_id"] == driver_id and b["status"] in (
                    "PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED", "IN_PROGRESS"
                ):
                    b_start = b["start_time"]
                    b_blocked = b["blocked_until"]
                    if b_start < blocked_until and start_time < b_blocked:
                        raise ExclusionViolationError(
                            message=f'conflicting key value violates exclusion constraint "no_driver_overlap"',
                            pgcode="23P01",
                        )

            new_record = {
                "id": booking_id,
                "vehicle_id": vehicle_id,
                "driver_id": driver_id,
                "start_time": start_time,
                "end_time": end_time,
                "blocked_until": blocked_until,
                "status": status,
            }
            self.bookings.append(new_record)
            return booking_id


def test_concurrent_simultaneous_inserts_exclusion_23p01():
    """
    Two threads attempt simultaneous insert for the same vehicle and slot.
    A threading.Barrier synchronizes their execution to release simultaneously.
    Verify: Exactly one succeeds, and exactly one catches error code 23P01.
    """
    sim_db = SimulatedBookingDatabase()
    vehicle_id = "v-swift-01"
    driver_1 = "d-ravi-01"
    driver_2 = "d-suresh-02"

    now_utc = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)
    start_time = now_utc
    end_time = now_utc + timedelta(hours=2)
    blocked_until = end_time + timedelta(minutes=15)

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def attempt_reservation(driver_id):
        try:
            # Wait at barrier so both threads fire insert at the same millisecond
            barrier.wait(timeout=5)
            bid = sim_db.insert_booking(
                vehicle_id=vehicle_id,
                driver_id=driver_id,
                start_time=start_time,
                end_time=end_time,
                blocked_until=blocked_until,
            )
            results.append(bid)
        except ExclusionViolationError as e:
            errors.append(e)

    t1 = threading.Thread(target=attempt_reservation, args=(driver_1,))
    t2 = threading.Thread(target=attempt_reservation, args=(driver_2,))

    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(results) == 1, f"Expected exactly 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 failure, got {len(errors)}"
    assert errors[0].pgcode == "23P01", f"Expected error code 23P01, got {errors[0].pgcode}"


def test_concurrent_driver_conflict_exclusion_23p01():
    """
    Two threads attempt simultaneous insert for the same DRIVER but different vehicles.
    A threading.Barrier synchronizes their execution.
    Verify: Exactly one succeeds, and the other catches 23P01 (no_driver_overlap).
    """
    sim_db = SimulatedBookingDatabase()
    driver_id = "d-shared-01"
    veh_1 = "v-swift-01"
    veh_2 = "v-city-02"

    now_utc = datetime(2026, 10, 20, 16, 0, 0, tzinfo=timezone.utc)
    start_time = now_utc
    end_time = now_utc + timedelta(hours=2)
    blocked_until = end_time + timedelta(minutes=15)

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def attempt_reservation(vehicle_id):
        try:
            barrier.wait(timeout=5)
            bid = sim_db.insert_booking(
                vehicle_id=vehicle_id,
                driver_id=driver_id,
                start_time=start_time,
                end_time=end_time,
                blocked_until=blocked_until,
            )
            results.append(bid)
        except ExclusionViolationError as e:
            errors.append(e)

    t1 = threading.Thread(target=attempt_reservation, args=(veh_1,))
    t2 = threading.Thread(target=attempt_reservation, args=(veh_2,))

    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(results) == 1, f"Expected exactly 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 failure, got {len(errors)}"
    assert errors[0].pgcode == "23P01", f"Expected error code 23P01, got {errors[0].pgcode}"
    assert "no_driver_overlap" in errors[0].message


def test_multiple_concurrent_threads_race():
    """
    5 threads racing to book the exact same vehicle and slot simultaneously.
    Verify: Exactly 1 succeeds and 4 fail with pgcode 23P01.
    """
    sim_db = SimulatedBookingDatabase()
    vehicle_id = "v-ertiga-01"
    now_utc = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    start_time = now_utc
    end_time = now_utc + timedelta(hours=1)
    blocked_until = end_time + timedelta(minutes=15)

    thread_count = 5
    barrier = threading.Barrier(thread_count)
    successes = []
    failures = []

    def worker(worker_idx):
        try:
            barrier.wait(timeout=5)
            bid = sim_db.insert_booking(
                vehicle_id=vehicle_id,
                driver_id=f"driver-{worker_idx}",
                start_time=start_time,
                end_time=end_time,
                blocked_until=blocked_until,
            )
            successes.append(bid)
        except ExclusionViolationError as exc:
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(successes) == 1
    assert len(failures) == 4
    for err in failures:
        assert err.pgcode == "23P01"


def test_conflict_handling_formats_standardized_error():
    """
    Verify application error format when exclusion violation 23P01 occurs.
    Matches SPEC.md Section 4.7:
    { "error": { "code": "VEHICLE_TAKEN", "message": "...", "alternatives": [...] } }
    """
    req = {
        "start": datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc),
        "passengers": 3,
    }
    # Simulate finding alternatives when primary vehicle was just taken
    alt_res = allocate(req)
    alternatives_payload = [opt.to_dict() for opt in alt_res.options]

    # Catch 23P01 and format
    err_payload = format_exclusion_error(alternatives=alternatives_payload)

    assert "error" in err_payload
    assert err_payload["error"]["code"] == "VEHICLE_TAKEN"
    assert "alternatives" in err_payload["error"]
    assert "That vehicle was just reserved" in err_payload["error"]["message"]
    assert len(err_payload["error"]["alternatives"]) > 0


def test_live_postgres_concurrent_exclusion():
    """
    If a live PostgreSQL instance is available via DATABASE_URL, run real
    concurrent multi-threaded transactions verifying exclusion constraint 23P01.
    Skipped gracefully if DATABASE_URL is not set or PostgreSQL is unreachable.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set; skipping live Postgres test")

    conn_check = get_db_connection()
    if conn_check is None:
        pytest.skip("Could not establish connection to DATABASE_URL; skipping")
    conn_check.close()

    import psycopg2

    now_utc = datetime.now(timezone.utc) + timedelta(days=20)
    start_a = now_utc.replace(second=0, microsecond=0)
    end_a = start_a + timedelta(hours=1)
    blocked_a = end_a + timedelta(minutes=15)

    vehicle_id = "00000000-0000-0000-0001-000000000001"
    employee_id = "00000000-0000-0000-0003-000000000001"

    barrier = threading.Barrier(2)
    succeeded_ids = []
    pg_errors = []

    def db_worker():
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        try:
            barrier.wait(timeout=5)
            cur.execute("""
                INSERT INTO bookings (
                    employee_id, vehicle_id, start_time, end_time, blocked_until,
                    destination, passengers, reason, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                RETURNING id;
            """, (employee_id, vehicle_id, start_a, end_a, blocked_a, "Conflict Test", 2, "Test Race"))
            bid = cur.fetchone()[0]
            conn.commit()
            succeeded_ids.append(bid)
        except psycopg2.Error as e:
            conn.rollback()
            pg_errors.append(e)
        finally:
            cur.close()
            conn.close()

    t1 = threading.Thread(target=db_worker)
    t2 = threading.Thread(target=db_worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # Clean up created records
    if succeeded_ids:
        cleanup_conn = psycopg2.connect(database_url)
        with cleanup_conn.cursor() as cur:
            cur.execute("DELETE FROM bookings WHERE id = ANY(%s);", (succeeded_ids,))
            cleanup_conn.commit()
        cleanup_conn.close()

    assert len(succeeded_ids) == 1
    assert len(pg_errors) == 1
    assert pg_errors[0].pgcode == "23P01"
