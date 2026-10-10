"""Smoke test script for the allocation engine.

Demonstrates deterministic vehicle and driver allocation with plain-English
explanations, diagnostic failure ladder, and alternative recommendations.
"""
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from app.engine.allocate import (
    allocate,
    get_default_vehicles,
    get_default_drivers,
)


def print_separator(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def run_smoke_tests():
    now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base_time = now_utc + timedelta(days=2, hours=10) # 2 days ahead at 10:00 UTC

    # -------------------------------------------------------------
    # Scenario 1: Standard 3-passenger request (Capacity best fit)
    # -------------------------------------------------------------
    print_separator("SCENARIO 1: Standard 3-Passenger Scheduled Request")
    req_1 = {
        "start": base_time,
        "end": base_time + timedelta(hours=2),
        "passengers": 3,
        "type": "scheduled",
        "priority": "normal",
        "destination": "Bengaluru Tech Park",
    }
    print(f"Request: 3 passengers, {format_dt(req_1['start'])} to {format_dt(req_1['end'])}")
    res_1 = allocate(req_1)
    print(f"Allocation OK: {res_1.ok}")
    print(f"Top {len(res_1.options)} Options:")
    for i, opt in enumerate(res_1.options, start=1):
        print(f"  [{i}] Vehicle: {opt.vehicle_name} | Driver: {opt.driver_name} | Score: {opt.score}")
        print(f"      Reason: {opt.reason}")

    # -------------------------------------------------------------
    # Scenario 2: 6-Passenger Request (Should pick 7-seater MUV)
    # -------------------------------------------------------------
    print_separator("SCENARIO 2: 6-Passenger Team Transfer")
    req_2 = {
        "start": base_time,
        "end": base_time + timedelta(hours=3),
        "passengers": 6,
        "type": "scheduled",
        "priority": "normal",
        "destination": "Airport Terminal 2",
    }
    print(f"Request: 6 passengers, {format_dt(req_2['start'])} to {format_dt(req_2['end'])}")
    res_2 = allocate(req_2)
    print(f"Allocation OK: {res_2.ok}")
    for i, opt in enumerate(res_2.options, start=1):
        print(f"  [{i}] Vehicle: {opt.vehicle_name} | Driver: {opt.driver_name} | Score: {opt.score}")
        print(f"      Reason: {opt.reason}")

    # -------------------------------------------------------------
    # Scenario 3: 15 Passengers (Exceeds 12-seater Tempo -> NO_VEHICLE_BIG_ENOUGH)
    # -------------------------------------------------------------
    print_separator("SCENARIO 3: 15 Passengers (Exceeds Fleet Max Capacity)")
    req_3 = {
        "start": base_time,
        "end": base_time + timedelta(hours=4),
        "passengers": 15,
        "type": "scheduled",
        "priority": "normal",
        "destination": "Offsite Conference Hall",
    }
    print(f"Request: 15 passengers (Fleet max is 12 seats)")
    res_3 = allocate(req_3)
    print(f"Allocation OK: {res_3.ok}")
    print(f"Failure Reason: {res_3.failure_reason}")
    print(f"Alternatives Returned: {len(res_3.alternatives)}")
    for alt in res_3.alternatives:
        print(f"  - [{alt.get('type')}] {alt.get('description')}")

    # -------------------------------------------------------------
    # Scenario 4: All Suitable Vehicles Busy -> ALL_VEHICLES_BUSY
    # -------------------------------------------------------------
    print_separator("SCENARIO 4: Overlapping Reservations (ALL_VEHICLES_BUSY)")
    all_vehicles = get_default_vehicles()
    # Book every single vehicle for the slot
    simulated_busy_bookings = []
    for v in all_vehicles:
        simulated_busy_bookings.append({
            "id": f"busy-{v['id']}",
            "vehicle_id": v["id"],
            "driver_id": "00000000-0000-0000-0005-000000000001",
            "start_time": base_time,
            "end_time": base_time + timedelta(hours=2),
            "blocked_until": base_time + timedelta(hours=2, minutes=15),
            "status": "CONFIRMED",
        })

    req_4 = {
        "start": base_time + timedelta(minutes=30),
        "end": base_time + timedelta(hours=1, minutes=30),
        "passengers": 4,
    }
    res_4 = allocate(req_4, bookings=simulated_busy_bookings)
    print(f"Allocation OK: {res_4.ok}")
    print(f"Failure Reason: {res_4.failure_reason}")
    print(f"Alternatives Offered: {len(res_4.alternatives)}")
    for alt in res_4.alternatives[:4]:
        print(f"  - [{alt.get('type')}] {alt.get('description')}")

    # -------------------------------------------------------------
    # Scenario 5: Drivers Rest-Gap Violation -> NO_ELIGIBLE_DRIVER
    # -------------------------------------------------------------
    print_separator("SCENARIO 5: Rest-Gap Fatigue Violation (NO_ELIGIBLE_DRIVER)")
    all_drivers = get_default_drivers()
    # Give all drivers a trip ending just 15 minutes before new request (violates 45m rest requirement)
    fatigued_bookings = []
    for d in all_drivers:
        fatigued_bookings.append({
            "id": f"prev-{d['id']}",
            "vehicle_id": "00000000-0000-0000-0001-000000000001",
            "driver_id": d["id"],
            "start_time": base_time - timedelta(hours=2),
            "end_time": base_time - timedelta(minutes=15), # Ended 15m ago
            "blocked_until": base_time,
            "status": "COMPLETED",
        })

    req_5 = {
        "start": base_time,
        "end": base_time + timedelta(hours=1),
        "passengers": 4,
    }
    res_5 = allocate(req_5, bookings=fatigued_bookings)
    print(f"Allocation OK: {res_5.ok}")
    print(f"Failure Reason: {res_5.failure_reason}")
    print(f"Alternatives Offered: {len(res_5.alternatives)}")
    for alt in res_5.alternatives[:3]:
        print(f"  - [{alt.get('type')}] {alt.get('description')}")

    # -------------------------------------------------------------
    # Scenario 6: Maintenance Demo -> VEHICLES_IN_MAINTENANCE
    # -------------------------------------------------------------
    print_separator("SCENARIO 6: Vehicles Under Maintenance (VEHICLES_IN_MAINTENANCE)")
    maintenance_vehicles = [
        {
            "id": "veh-1",
            "name": "Force Tempo Traveller",
            "capacity": 12,
            "status": "maintenance",
            "maintenance_until": base_time + timedelta(days=1),
        }
    ]
    req_6 = {
        "start": base_time,
        "end": base_time + timedelta(hours=2),
        "passengers": 10,
    }
    res_6 = allocate(req_6, vehicles=maintenance_vehicles)
    print(f"Allocation OK: {res_6.ok}")
    print(f"Failure Reason: {res_6.failure_reason}")

    print_separator("ALL SMOKE TESTS EXECUTED CLEANLY AND SUCCESSFULLY!")


if __name__ == "__main__":
    run_smoke_tests()
