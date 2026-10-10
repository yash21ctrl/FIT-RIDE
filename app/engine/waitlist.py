"""promote_waitlisted() auto-promotion logic (Team KNIGHT | PS 40)."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import get_app_config
from app.db import query_bookings, _to_utc_dt


PRIORITY_WEIGHT = {
    "emergency": 4,
    "high": 3,
    "normal": 2,
    "low": 1,
}


def promote_waitlisted(conn=None) -> List[Dict[str, Any]]:
    """
    Scan WAITLISTED bookings and attempt to allocate vehicles and drivers.
    Ordered strictly by priority (emergency > high > normal > low), then created_at ASC.
    Transitions successfully allocated bookings to PENDING.
    """
    from app.engine.allocate import allocate, BookingRequest
    from app.services.transitions import transition

    waitlisted_bookings = query_bookings(conn=conn, active_only=False, status="WAITLISTED")
    if not waitlisted_bookings:
        return []

    # Sort: highest priority first, then earliest created_at first
    def sort_key(b):
        p_val = PRIORITY_WEIGHT.get(b.get("priority", "normal"), 2)
        c_at = _to_utc_dt(b.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)
        return (-p_val, c_at)

    sorted_waitlist = sorted(waitlisted_bookings, key=sort_key)
    promoted = []

    config = get_app_config(conn=conn)
    buffer_min = int(config.get("buffer_minutes", 15))

    for b in sorted_waitlist:
        start_dt = _to_utc_dt(b["start_time"])
        end_dt = _to_utc_dt(b["end_time"])
        if not start_dt or not end_dt:
            continue

        req = BookingRequest(
            start=start_dt,
            end=end_dt,
            passengers=int(b.get("passengers", 1)),
            type=b.get("type", "scheduled"),
            priority=b.get("priority", "normal"),
            destination=b.get("destination", ""),
            employee_id=b.get("employee_id"),
            reason=b.get("reason", ""),
        )

        res = allocate(req, exclude_booking_id=b["id"], db_conn=conn)
        if res.ok and res.options:
            top = res.options[0]
            blocked_until = end_dt + timedelta(minutes=buffer_min)

            updated = transition(
                booking_id=b["id"],
                new_status="PENDING",
                actor={"id": "system", "role": "system"},
                note="Promoted from waitlist when slot freed",
                extra_data={
                    "vehicle_id": top.vehicle_id,
                    "driver_id": top.driver_id,
                    "decision_reason": f"Auto-promoted from waitlist: {top.reason}",
                    "blocked_until": blocked_until,
                },
                conn=conn,
            )
            promoted.append(updated)

    return promoted
