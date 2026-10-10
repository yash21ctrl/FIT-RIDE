"""Emergency bump candidate selection and execution engine (Team KNIGHT | PS 40).

Governed by SPEC.md Section 4.3 & Section 3:
1. When an emergency booking is submitted and direct allocation finds no free slot,
   the engine searches for an overlapping low-priority booking to bump.
2. Guardrails:
   - Never bump IN_PROGRESS or emergency trips.
   - Never bump a booking twice (was_bumped == True is protected forever).
   - Only bump priority 'low' bookings whose vehicle capacity >= emergency passengers.
   - Lowest priority picked first, then most recently created.
3. Candidate transitions to BUMPED (was_bumped=True).
4. Emergency booking takes the slot and advances directly to DRIVER_PENDING (2 min response window).
5. Bumped employee receives alternatives or waitlist placement. Manager alerted.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_app_config
from app.db import (
    query_bookings,
    query_vehicles,
    get_vehicle_by_id,
    get_booking_by_id,
    update_booking,
    create_notification,
    _to_utc_dt,
)
from app.engine.allocate import get_default_vehicles, BookingRequest
from app.services.transitions import transition, MANAGER_PROFILE_IDS


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get attribute or dict key."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def find_bump_candidate(
    request: Any,
    bookings: Optional[List[Any]] = None,
    vehicles: Optional[List[Any]] = None,
    conn=None,
) -> Optional[Dict[str, Any]]:
    """
    Search for an eligible bump candidate:
    - Overlapping booking with priority 'low'
    - Status not 'IN_PROGRESS' (must be in pre-trip slot-holding: PENDING, APPROVED, DRIVER_PENDING, CONFIRMED)
    - Not already bumped (was_bumped == False)
    - Vehicle capacity >= requested passengers
    - Ranked by lowest priority (all 'low'), then most recently created (DESC).
    """
    config = get_app_config(conn=conn)
    buffer_min = int(config.get("buffer_minutes", 15))
    buffer_delta = timedelta(minutes=buffer_min)

    start_utc = _to_utc_dt(_get(request, "start") or _get(request, "start_time"))
    end_utc = _to_utc_dt(_get(request, "end") or _get(request, "end_time"))
    passengers = int(_get(request, "passengers", 1))
    if not start_utc or not end_utc:
        return None

    blocked_until_utc = end_utc + buffer_delta

    if bookings is None:
        bookings = query_bookings(conn=conn, active_only=False)

    if vehicles is None:
        vehicles = query_vehicles(conn=conn)
        if not vehicles:
            vehicles = get_default_vehicles()

    veh_by_id = {str(_get(v, "id")): v for v in vehicles}

    candidates = []
    for b in bookings:
        b_dict = dict(b) if not isinstance(b, dict) else b
        # Guardrail 1: Never bump emergency or normal/high trips. Only 'low' priority.
        b_priority = _get(b_dict, "priority", "normal")
        if b_priority != "low":
            continue

        # Guardrail 2: Never bump trips already IN_PROGRESS or completed/cancelled
        b_status = _get(b_dict, "status", "")
        if b_status not in ("PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED"):
            continue

        # Guardrail 3: Never bump a booking twice
        if _get(b_dict, "was_bumped", False):
            continue

        # Vehicle must exist and have enough capacity for the emergency trip
        v_id = str(_get(b_dict, "vehicle_id", ""))
        veh = veh_by_id.get(v_id)
        if not veh:
            continue
        v_cap = int(_get(veh, "capacity", 0))
        if v_cap < passengers:
            continue

        # Time overlap check: [b_start, b_blocked_until) overlaps with [req_start, req_blocked_until)
        b_st = _to_utc_dt(_get(b_dict, "start_time"))
        b_bu = _to_utc_dt(_get(b_dict, "blocked_until") or (_to_utc_dt(_get(b_dict, "end_time")) + buffer_delta))
        if not b_st or not b_bu:
            continue

        if b_st < blocked_until_utc and start_utc < b_bu:
            candidates.append(b_dict)

    if not candidates:
        return None

    # Ranking: lowest priority first (all 'low'), then most recently created (DESC)
    def sort_key(b):
        c_at = _to_utc_dt(_get(b, "created_at")) or datetime.min.replace(tzinfo=timezone.utc)
        return c_at

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def execute_bump(
    candidate_booking: Dict[str, Any],
    emergency_booking_data: Dict[str, Any],
    actor: Any,
    conn=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Execute emergency bump:
    1. Candidate transitions to BUMPED (was_bumped=True).
    2. Emergency takes the slot and advances directly to DRIVER_PENDING.
    3. Bumped employee receives alternatives and notifications.
    4. Managers are alerted.
    Returns (emergency_booking, bumped_booking).
    """
    from app.engine.alternatives import find_alternatives

    config = get_app_config(conn=conn)
    buffer_min = int(config.get("buffer_minutes", 15))
    buffer_delta = timedelta(minutes=buffer_min)
    win_min = int(config.get("respond_window_emergency_min", 2))
    now_utc = datetime.now(timezone.utc)
    respond_by_dt = now_utc + timedelta(minutes=win_min)

    c_id = candidate_booking["id"]
    assigned_vehicle_id = candidate_booking.get("vehicle_id")
    assigned_driver_id = candidate_booking.get("driver_id")

    # 1. Bump the candidate booking
    bumped = transition(
        booking_id=c_id,
        new_status="BUMPED",
        actor={"id": "system", "role": "system"},
        note=f"Bumped by emergency booking for {emergency_booking_data.get('passengers', 1)} passengers",
        extra_data={"was_bumped": True},
        conn=conn,
    )

    # 2. Build and insert emergency booking
    emg_data = dict(emergency_booking_data)
    emg_data["vehicle_id"] = assigned_vehicle_id
    emg_data["driver_id"] = assigned_driver_id
    emg_data["type"] = "emergency"
    emg_data["priority"] = "emergency"
    emg_data["was_bumped"] = False

    veh_rec = get_vehicle_by_id(assigned_vehicle_id, conn=conn)
    veh_name = veh_rec.get("name", "Vehicle") if veh_rec else "Vehicle"
    emg_data["decision_reason"] = (
        f"Emergency priority override: bumped low-priority booking {str(c_id)[:8]} "
        f"on {veh_name} (seats {veh_rec.get('capacity', '?') if veh_rec else '?'})"
    )

    # Ensure blocked_until is populated
    end_utc = _to_utc_dt(emg_data.get("end_time") or emg_data.get("end"))
    if end_utc and "blocked_until" not in emg_data:
        emg_data["blocked_until"] = end_utc + buffer_delta

    # Create emergency booking as PENDING
    created_emg = transition(
        booking_id=None,
        new_status="PENDING",
        actor=actor,
        note=emg_data["decision_reason"],
        extra_data=emg_data,
        conn=conn,
    )
    emg_id = created_emg["id"]

    # Auto-approve and dispatch to DRIVER_PENDING directly (skipping manager approval queue)
    transition(
        booking_id=emg_id,
        new_status="APPROVED",
        actor={"id": "system", "role": "system"},
        note="Emergency booking auto-approved",
        conn=conn,
    )
    final_emg = transition(
        booking_id=emg_id,
        new_status="DRIVER_PENDING",
        actor={"id": "system", "role": "system"},
        note="Emergency trip dispatched directly to driver (2 min window)",
        extra_data={"respond_by": respond_by_dt},
        conn=conn,
    )

    # 3. Generate alternatives for the bumped employee
    bumped_req = BookingRequest(
        start=_to_utc_dt(candidate_booking["start_time"]),
        end=_to_utc_dt(candidate_booking["end_time"]),
        passengers=int(candidate_booking.get("passengers", 1)),
        type=candidate_booking.get("type", "scheduled"),
        priority=candidate_booking.get("priority", "low"),
        destination=candidate_booking.get("destination", ""),
        employee_id=candidate_booking.get("employee_id"),
        reason=candidate_booking.get("reason", ""),
    )
    alts = find_alternatives(bumped_req, config=config, exclude_booking_id=c_id)
    update_booking(
        c_id,
        {
            "failure_reason": "BUMPED_BY_EMERGENCY",
            "decision_reason": f"Bumped by emergency booking {str(emg_id)[:8]}. Alternative slots available.",
        },
        conn=conn,
    )

    # 4. Notify bumped employee and managers
    bumped_emp_id = candidate_booking.get("employee_id")
    if bumped_emp_id:
        create_notification(
            bumped_emp_id,
            f"Your booking {str(c_id)[:8]} was bumped by an emergency request. Please review alternative times or join the waitlist.",
            booking_id=c_id,
            conn=conn,
        )

    for m_id in MANAGER_PROFILE_IDS:
        create_notification(
            m_id,
            f"EMERGENCY BUMP: Trip {str(emg_id)[:8]} bumped booking {str(c_id)[:8]} on {veh_name}.",
            booking_id=emg_id,
            conn=conn,
        )

    return (final_emg, bumped)
