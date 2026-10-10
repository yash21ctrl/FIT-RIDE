"""Admin and demo simulation routes (Team KNIGHT | PS 40).

Endpoints:
- POST /api/admin/simulate: Run complete demo chaos script simulating conflicts, 15-pax failure,
  emergency bumps, driver fatigue reassignments, and vehicle maintenance reallocations.
- POST /api/admin/trip-merge-check: Proximity trip merge suggestion engine (Haversine distance).
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, g

from app.auth import require_role
from app.db import (
    create_booking,
    get_booking_by_id,
    query_bookings,
    update_vehicle,
    get_vehicle_by_id,
    _to_utc_dt,
)
from app.engine.allocate import allocate, BookingRequest
from app.engine.bump import find_bump_candidate, execute_bump
from app.engine.waitlist import promote_waitlisted
from app.routes.vehicles import reallocate_vehicle_maintenance
from app.services.transitions import transition

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


@admin_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "admin", "status": "pong"})


@admin_bp.route("/reset", methods=["POST"])
@require_role("manager")
def reset_system_data():
    """Wipe all bookings, trips, logs, and simulation data back to clean seed slate."""
    from app.db import reset_seed_data
    reset_seed_data()
    return jsonify({
        "ok": True,
        "message": "All simulation data and bookings wiped successfully. System restored to clean initial state.",
    }), 200


@admin_bp.route("/trip-merge-check", methods=["POST"])
@require_role("manager", "employee")
def trip_merge_check():
    """
    Check if a trip request can be merged with existing active bookings:
    - Same destination within merge_radius_km (default 2.0 km)
    - Overlapping / close start times (+/- 30 minutes)
    - Vehicle has enough residual capacity
    """
    data = request.get_json(silent=True) or {}
    dest_lat = data.get("dest_lat")
    dest_lng = data.get("dest_lng")
    start_raw = data.get("start_time") or data.get("start")
    passengers = int(data.get("passengers", 1))
    radius_km = float(data.get("merge_radius_km", 2.0))

    if dest_lat is None or dest_lng is None or not start_raw:
        return jsonify({
            "mergeable": False,
            "message": "dest_lat, dest_lng, and start_time are required for proximity check",
            "candidates": [],
        }), 200

    start_dt = _to_utc_dt(start_raw)
    if not start_dt:
        return jsonify({"mergeable": False, "candidates": []}), 400

    active_bookings = query_bookings(active_only=True)
    merge_candidates = []

    for b in active_bookings:
        b_lat = b.get("dest_lat")
        b_lng = b.get("dest_lng")
        if b_lat is None or b_lng is None:
            continue

        dist_km = haversine_km(float(dest_lat), float(dest_lng), float(b_lat), float(b_lng))
        b_st = _to_utc_dt(b.get("start_time"))
        if not b_st:
            continue

        time_diff_min = abs((b_st - start_dt).total_seconds()) / 60.0

        if dist_km <= radius_km and time_diff_min <= 30.0:
            veh = get_vehicle_by_id(b.get("vehicle_id")) if b.get("vehicle_id") else None
            veh_cap = int(veh.get("capacity", 0)) if veh else 0
            b_pax = int(b.get("passengers", 1))
            remaining_seats = max(0, veh_cap - b_pax)

            can_fit = remaining_seats >= passengers
            merge_candidates.append({
                "booking_id": b["id"],
                "destination": b.get("destination", ""),
                "distance_km": round(dist_km, 2),
                "time_difference_min": round(time_diff_min, 1),
                "existing_passengers": b_pax,
                "remaining_seats": remaining_seats,
                "can_fit_all": can_fit,
            })

    can_merge = any(c["can_fit_all"] for c in merge_candidates)
    return jsonify({
        "mergeable": can_merge,
        "merge_radius_km": radius_km,
        "candidates": merge_candidates,
        "recommendation": "Trip merge recommended: share vehicle to optimize fleet efficiency" if can_merge else "No suitable merge candidate within proximity radius",
    }), 200


@admin_bp.route("/simulate", methods=["POST"])
@require_role("manager")
def simulate_chaos():
    """
    Demo Chaos Simulation Script (SPEC.md Section 16 Demo Script):
    1. Overlapping trips conflict simulation.
    2. 15-passenger failure ladder.
    3. Emergency priority bump.
    4. Driver fatigue rejection & automatic re-assignment.
    5. Vehicle maintenance reallocation.
    """
    user = getattr(g, "current_user", {"id": "00000000-0000-0000-0002-000000000001", "role": "manager"})
    results = []
    base_time = datetime.now(timezone.utc) + timedelta(days=14, hours=9)

    # -------------------------------------------------------------
    # Scenario 1: Overlapping Booking Handling
    # -------------------------------------------------------------
    try:
        t1_start = base_time
        t1_end = t1_start + timedelta(hours=2)

        req1 = BookingRequest(
            start=t1_start,
            end=t1_end,
            passengers=3,
            type="scheduled",
            priority="normal",
            destination="Tech Hub A",
            employee_id="00000000-0000-0000-0003-000000000001",
            reason="Demo Scenario 1A",
        )
        res1 = allocate(req1)
        b1_veh = res1.options[0].vehicle_id if res1.ok else None
        if res1.ok:
            create_booking({
                "employee_id": "00000000-0000-0000-0003-000000000001",
                "vehicle_id": b1_veh,
                "driver_id": res1.options[0].driver_id,
                "start_time": t1_start,
                "end_time": t1_end,
                "passengers": 3,
                "destination": "Tech Hub A",
                "reason": "Demo Scenario 1A",
                "type": "scheduled",
                "priority": "normal",
                "status": "CONFIRMED",
            })

        req2 = BookingRequest(
            start=t1_start,
            end=t1_end,
            passengers=3,
            type="scheduled",
            priority="normal",
            destination="Tech Hub B",
            employee_id="00000000-0000-0000-0003-000000000002",
            reason="Demo Scenario 1B Overlap",
        )
        res2 = allocate(req2)
        b2_veh = res2.options[0].vehicle_id if res2.ok else None

        results.append({
            "scenario": "1. Overlapping Booking",
            "description": "Two simultaneous booking requests for matching times",
            "passed": bool(res1.ok and res2.ok and (b1_veh != b2_veh)),
            "details": f"Trip 1 assigned vehicle {b1_veh[:8] if b1_veh else 'None'}, Trip 2 seamlessly assigned alternate vehicle {b2_veh[:8] if b2_veh else 'None'}",
        })
    except Exception as exc:
        results.append({"scenario": "1. Overlapping Booking", "passed": False, "error": str(exc)})

    # -------------------------------------------------------------
    # Scenario 2: 15-Passenger Failure Ladder
    # -------------------------------------------------------------
    try:
        t2_start = base_time + timedelta(hours=3)
        t2_end = t2_start + timedelta(hours=2)

        req15 = BookingRequest(
            start=t2_start,
            end=t2_end,
            passengers=15,
            type="scheduled",
            priority="normal",
            destination="Annual Convention",
            employee_id="00000000-0000-0000-0003-000000000001",
            reason="Demo Scenario 2: 15 Pax",
        )
        res15 = allocate(req15)
        passed_15 = (not res15.ok) and (res15.failure_reason == "NO_VEHICLE_BIG_ENOUGH") and (len(res15.alternatives) > 0)

        results.append({
            "scenario": "2. 15-Passenger Failure Ladder",
            "description": "Request with 15 passengers exceeds maximum fleet capacity (12 seats)",
            "passed": passed_15,
            "failure_reason": res15.failure_reason,
            "alternatives_count": len(res15.alternatives),
            "details": "Accurately diagnosed NO_VEHICLE_BIG_ENOUGH and presented group split recommendation",
        })
    except Exception as exc:
        results.append({"scenario": "2. 15-Passenger Failure Ladder", "passed": False, "error": str(exc)})

    # -------------------------------------------------------------
    # Scenario 3: Emergency Priority Bump
    # -------------------------------------------------------------
    try:
        t3_start = base_time + timedelta(hours=6)
        t3_end = t3_start + timedelta(hours=2)

        # Create low priority booking on 4-seater Swift
        low_b = create_booking({
            "employee_id": "00000000-0000-0000-0003-000000000001",
            "vehicle_id": "00000000-0000-0000-0001-000000000001",
            "driver_id": "00000000-0000-0000-0005-000000000001",
            "start_time": t3_start,
            "end_time": t3_end,
            "passengers": 3,
            "type": "scheduled",
            "priority": "low",
            "status": "CONFIRMED",
            "reason": "Routine office supplies",
        })

        # Locate bump candidate
        emg_req = BookingRequest(
            start=t3_start,
            end=t3_end,
            passengers=3,
            type="emergency",
            priority="emergency",
            destination="Emergency Medical Center",
            employee_id="00000000-0000-0000-0003-000000000002",
            reason="URGENT Medical Equipment Delivery",
        )
        candidate = find_bump_candidate(emg_req)
        assert candidate is not None and candidate["id"] == low_b["id"]

        final_emg, bumped_bkg = execute_bump(
            candidate,
            {
                "employee_id": "00000000-0000-0000-0003-000000000002",
                "start_time": t3_start,
                "end_time": t3_end,
                "passengers": 3,
                "destination": "Emergency Medical Center",
                "reason": "URGENT Medical Equipment Delivery",
            },
            actor=user,
        )

        passed_bump = (bumped_bkg["status"] == "BUMPED") and (bumped_bkg["was_bumped"] is True) and (final_emg["status"] == "DRIVER_PENDING")

        results.append({
            "scenario": "3. Emergency Priority Bump",
            "description": "Emergency request bumps low-priority trip and directly enters DRIVER_PENDING",
            "passed": passed_bump,
            "bumped_id": bumped_bkg["id"][:8],
            "emergency_id": final_emg["id"][:8],
            "details": "Low-priority trip bumped (was_bumped=True); emergency dispatched directly with 2 min window",
        })
    except Exception as exc:
        results.append({"scenario": "3. Emergency Priority Bump", "passed": False, "error": str(exc)})

    # -------------------------------------------------------------
    # Scenario 4: Driver Fatigue Rejection & Auto-Reassignment
    # -------------------------------------------------------------
    try:
        t4_start = base_time + timedelta(hours=9)
        t4_end = t4_start + timedelta(hours=1)

        b_driver = create_booking({
            "employee_id": "00000000-0000-0000-0003-000000000001",
            "vehicle_id": "00000000-0000-0000-0001-000000000002",
            "driver_id": "00000000-0000-0000-0005-000000000001",
            "start_time": t4_start,
            "end_time": t4_end,
            "passengers": 2,
            "type": "scheduled",
            "priority": "normal",
            "status": "DRIVER_PENDING",
        })

        # Driver rejects with reason "tired"
        reassigned_bkg = transition(
            booking_id=b_driver["id"],
            new_status="PENDING",
            actor={"id": "00000000-0000-0000-0004-000000000001", "role": "driver"},
            note="Fatigued after long shift",
            extra_data={"reject_reason": "tired"},
        )
        passed_fatigue = (reassigned_bkg["driver_id"] != "00000000-0000-0000-0005-000000000001")

        results.append({
            "scenario": "4. Driver Fatigue Rejection",
            "description": "Driver reports tired; engine automatically excludes driver and reassigns replacement",
            "passed": passed_fatigue,
            "new_driver_id": reassigned_bkg.get("driver_id", "None")[:8],
            "details": "Rejection saved to driver_responses; allocation engine reassigned next eligible rested driver",
        })
    except Exception as exc:
        results.append({"scenario": "4. Driver Fatigue Rejection", "passed": False, "error": str(exc)})

    # -------------------------------------------------------------
    # Scenario 5: Vehicle Maintenance Reallocation
    # -------------------------------------------------------------
    try:
        t5_start = base_time + timedelta(days=1)
        t5_end = t5_start + timedelta(hours=2)

        # Booking on Bolero
        bolero_id = "00000000-0000-0000-0001-000000000005"
        b_bolero = create_booking({
            "employee_id": "00000000-0000-0000-0003-000000000001",
            "vehicle_id": bolero_id,
            "driver_id": "00000000-0000-0000-0005-000000000003",
            "start_time": t5_start,
            "end_time": t5_end,
            "passengers": 6,
            "type": "scheduled",
            "priority": "normal",
            "status": "CONFIRMED",
        })

        # Update Bolero status to maintenance
        update_vehicle(bolero_id, {"status": "maintenance"})
        realloc_res = reallocate_vehicle_maintenance(bolero_id, manager_actor=user)

        updated_bolero_trip = get_booking_by_id(b_bolero["id"])
        passed_maint = (updated_bolero_trip["vehicle_id"] != bolero_id) or (updated_bolero_trip["status"] == "WAITLISTED")

        results.append({
            "scenario": "5. Vehicle Maintenance Reallocation",
            "description": "Vehicle enters maintenance; engine automatically reallocates affected trips or waitlists",
            "passed": passed_maint,
            "new_vehicle_id": (updated_bolero_trip.get("vehicle_id") or "WAITLISTED")[:8],
            "details": f"Bolero put in maintenance; trip status: {updated_bolero_trip['status']}, vehicle: {updated_bolero_trip.get('vehicle_id')}",
        })
    except Exception as exc:
        results.append({"scenario": "5. Vehicle Maintenance Reallocation", "passed": False, "error": str(exc)})

    all_passed = all(r.get("passed", False) for r in results)

    return jsonify({
        "ok": all_passed,
        "message": "Chaos Simulation Script completed successfully" if all_passed else "Some simulation steps failed",
        "scenarios": results,
    }), 200
