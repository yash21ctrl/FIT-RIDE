"""Single authoritative state machine and audit logger (Team KNIGHT | PS 40).

Strictly enforces the State Transition Matrix defined in SPEC.md Section 3.
Rule: No other code may update the booking status column directly.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

from app.config import get_app_config
from app.db import (
    get_booking_by_id,
    create_booking,
    update_booking,
    update_vehicle,
    update_driver,
    get_driver_by_id,
    get_driver_by_profile_id,
    add_decision_log,
    add_driver_response,
    get_driver_responses,
    create_or_update_trip,
    create_notification,
    _to_utc_dt,
)


class TransitionError(ValueError):
    """Base exception for transition failures."""
    pass


class IllegalTransitionError(TransitionError):
    """Raised when an illegal transition jump is attempted."""
    pass


class ForbiddenTransitionError(TransitionError):
    """Raised when actor lacks permission to trigger transition."""
    pass


class BookingNotFoundError(TransitionError):
    """Raised when booking record does not exist."""
    pass


# State Transition Matrix from SPEC.md Section 3
ALLOWED: Dict[Optional[str], Set[str]] = {
    None: {"PENDING", "WAITLISTED"},
    "(new)": {"PENDING", "WAITLISTED"},
    "": {"PENDING", "WAITLISTED"},
    "PENDING": {"APPROVED", "REJECTED", "CANCELLED", "BUMPED", "WAITLISTED"},
    "APPROVED": {"DRIVER_PENDING", "CANCELLED", "BUMPED", "WAITLISTED"},
    "DRIVER_PENDING": {"CONFIRMED", "PENDING", "CANCELLED", "BUMPED", "DRIVER_PENDING", "WAITLISTED"},
    "CONFIRMED": {"IN_PROGRESS", "CANCELLED", "BUMPED", "WAITLISTED"},
    "IN_PROGRESS": {"COMPLETED"},
    "BUMPED": {"PENDING", "WAITLISTED", "CANCELLED"},
    "WAITLISTED": {"PENDING", "CANCELLED"},
    "COMPLETED": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
}

# Known manager profile IDs for system broadcasts
MANAGER_PROFILE_IDS = [
    "00000000-0000-0000-0002-000000000001",
    "00000000-0000-0000-0002-000000000002",
]


def _extract_actor_info(actor: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (actor_id, actor_role, actor_driver_id)."""
    if isinstance(actor, dict):
        a_id = actor.get("id")
        a_role = actor.get("role")
        d_id = actor.get("driver_id")
        if not d_id and a_role == "driver" and a_id:
            d_rec = get_driver_by_profile_id(a_id)
            if d_rec:
                d_id = d_rec.get("id")
        return (str(a_id) if a_id else None, str(a_role) if a_role else None, str(d_id) if d_id else None)
    if isinstance(actor, str):
        if actor.lower() in ("system", "engine"):
            return ("system", "system", None)
        return (str(actor), None, None)
    return ("system", "system", None)


def transition(
    booking_id: Optional[str],
    new_status: str,
    actor: Any,
    note: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    conn=None,
) -> Dict[str, Any]:
    """
    Single authoritative state transition function.
    
    1. Validates move against ALLOWED dictionary.
    2. Enforces actor authorization.
    3. Executes database side effects (driver/vehicle statuses, respond_by, trips).
    4. Logs decision to decision_log.
    5. Dispatches notifications.
    6. Triggers waitlist promotion on slot-freeing events after database update.
    """
    actor_id, actor_role, actor_driver_id = _extract_actor_info(actor)
    now_utc = datetime.now(timezone.utc)

    # -------------------------------------------------------------
    # 0. Initial creation: (new) -> PENDING or (new) -> WAITLISTED
    # -------------------------------------------------------------
    if booking_id is None or str(booking_id).strip() in ("", "(new)"):
        if new_status not in ALLOWED.get("(new)", set()):
            raise IllegalTransitionError(f"Illegal initial status transition to '{new_status}'")
        if not extra_data or not isinstance(extra_data, dict):
            raise TransitionError("Initial booking creation requires extra_data dictionary")

        booking_record = dict(extra_data)
        booking_record["status"] = new_status
        created_booking = create_booking(booking_record, conn=conn)
        bid = str(created_booking["id"])

        if new_status == "PENDING":
            action_name = extra_data.get("action") or "requested"
            for m_id in MANAGER_PROFILE_IDS:
                create_notification(m_id, f"New booking request {bid} submitted by employee.", booking_id=bid, conn=conn)
            log_actor_id = actor_id if (actor_id and actor_id != "system") else None
            add_decision_log(bid, log_actor_id, action=action_name, note=note or created_booking.get("decision_reason"), conn=conn)
        elif new_status == "WAITLISTED":
            action_name = extra_data.get("action") or "waitlisted"
            emp_id = created_booking.get("employee_id")
            if emp_id:
                create_notification(emp_id, f"Booking {bid} was placed on waitlist: {note or 'Capacity full'}", booking_id=bid, conn=conn)
            log_actor_id = actor_id if (actor_id and actor_id != "system") else None
            add_decision_log(bid, log_actor_id, action=action_name, note=note or created_booking.get("failure_reason"), conn=conn)

        return created_booking

    bid = str(booking_id)
    booking = get_booking_by_id(bid, conn=conn)
    if not booking:
        raise BookingNotFoundError(f"Booking not found with ID {bid}")

    current_status = booking.get("status")
    allowed_targets = ALLOWED.get(current_status, set())

    # 1. State machine check
    if new_status not in allowed_targets:
        raise IllegalTransitionError(
            f"Illegal status transition from '{current_status}' to '{new_status}'"
        )

    updates: Dict[str, Any] = {"status": new_status}
    action_name = extra_data.get("action") if extra_data else None

    # Preserve was_bumped flag across transitions
    if booking.get("was_bumped") or (extra_data and extra_data.get("was_bumped")):
        updates["was_bumped"] = True

    # 2. Strict actor authorization checks
    if new_status == "CANCELLED":
        if actor_role == "employee":
            if str(booking.get("employee_id")) != str(actor_id):
                raise ForbiddenTransitionError("Cannot cancel another employee's booking")
        elif actor_role not in ("manager", "system"):
            raise ForbiddenTransitionError("Unauthorized to cancel booking")

    elif new_status in ("CONFIRMED", "IN_PROGRESS", "COMPLETED"):
        if actor_role not in ("driver", "system"):
            raise ForbiddenTransitionError(f"Only the assigned driver can mark booking as {new_status.lower().replace('_', ' ')}")
        if actor_role == "driver":
            assigned_driver_id = str(booking.get("driver_id")) if booking.get("driver_id") else None
            if not actor_driver_id or actor_driver_id != assigned_driver_id:
                raise ForbiddenTransitionError("Driver is not assigned to this booking")

    elif new_status == "PENDING" and current_status == "DRIVER_PENDING":
        # Driver reject or timeout
        if actor_role not in ("driver", "system", "manager"):
            raise ForbiddenTransitionError("Only the assigned driver, system, or manager can reject or timeout assignment")
        if actor_role == "driver":
            assigned_driver_id = str(booking.get("driver_id")) if booking.get("driver_id") else None
            if not actor_driver_id or actor_driver_id != assigned_driver_id:
                raise ForbiddenTransitionError("Driver is not assigned to this booking")

    elif new_status in ("APPROVED", "REJECTED"):
        if actor_role not in ("manager", "system"):
            raise ForbiddenTransitionError("Only a manager or system rule can approve or reject bookings")

    elif new_status == "BUMPED":
        if actor_role not in ("manager", "system"):
            raise ForbiddenTransitionError("Only the engine or manager can bump a booking")

    elif new_status == "DRIVER_PENDING" and current_status == "DRIVER_PENDING":
        if actor_role not in ("manager", "system"):
            raise ForbiddenTransitionError("Only a manager or system rule can override or re-dispatch an active assignment")

    # 3. Transition-specific side effects
    if new_status == "APPROVED":
        action_name = action_name or ("auto_approved" if actor_role == "system" else "approved")
        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Booking {bid} was approved.", booking_id=bid, conn=conn)

    elif new_status == "DRIVER_PENDING":
        action_name = action_name or ("overridden" if current_status == "DRIVER_PENDING" else "dispatched")
        if extra_data and "respond_by" in extra_data and extra_data["respond_by"]:
            respond_by_dt = _to_utc_dt(extra_data["respond_by"])
        else:
            config = get_app_config(conn=conn)
            window_min = int(config.get("respond_window_emergency_min", 2)) if booking.get("type") == "emergency" else int(config.get("respond_window_scheduled_min", 30))
            respond_by_dt = now_utc + timedelta(minutes=window_min)
        updates["respond_by"] = respond_by_dt

        # Target driver for notification (may be changed via override)
        drv_id = extra_data.get("driver_id") if (extra_data and extra_data.get("driver_id")) else booking.get("driver_id")
        if drv_id:
            driver_rec = get_driver_by_id(drv_id, conn=conn)
            if driver_rec and driver_rec.get("profile_id"):
                create_notification(
                    driver_rec["profile_id"],
                    f"New trip assignment {bid}. Please accept within time window.",
                    booking_id=bid,
                    conn=conn,
                )

    elif new_status == "CONFIRMED":
        action_name = action_name or "driver_accepted"
        drv_id = booking.get("driver_id")
        if drv_id:
            add_driver_response(bid, drv_id, response="accepted", conn=conn)

        # Notify employee and manager
        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Driver accepted your booking {bid}.", booking_id=bid, conn=conn)
        for m_id in MANAGER_PROFILE_IDS:
            create_notification(m_id, f"Driver accepted trip {bid}.", booking_id=bid, conn=conn)

    elif new_status == "PENDING" and current_status == "DRIVER_PENDING":
        drv_id = booking.get("driver_id")
        reason = extra_data.get("reject_reason", "other") if extra_data else "other"
        is_timeout = extra_data.get("is_timeout", False) if extra_data else False
        resp_type = "timeout" if is_timeout else "rejected"
        action_name = action_name or f"driver_{resp_type}"

        if drv_id:
            add_driver_response(bid, drv_id, response=resp_type, reject_reason=reason if not is_timeout else None, conn=conn)

        # Flag vehicle for manager inspection if driver reported vehicle_issue
        if reason == "vehicle_issue":
            veh_id = booking.get("vehicle_id")
            for m_id in MANAGER_PROFILE_IDS:
                create_notification(
                    m_id,
                    f"Driver reported vehicle issue for vehicle {veh_id} on booking {bid}: {note or reason}. Inspection required.",
                    booking_id=bid,
                    conn=conn,
                )

        # Re-run allocation engine excluding ALL drivers who have rejected or timed out
        from app.engine.allocate import allocate, BookingRequest
        past_responses = get_driver_responses(bid, conn=conn)
        exclude_set = {str(r["driver_id"]) for r in past_responses if r.get("response") in ("rejected", "timeout")}
        if drv_id:
            exclude_set.add(str(drv_id))

        req = BookingRequest(
            start=booking["start_time"],
            end=booking["end_time"],
            passengers=int(booking.get("passengers", 1)),
            type=booking.get("type", "scheduled"),
            priority=booking.get("priority", "normal"),
            destination=booking.get("destination", ""),
            employee_id=booking.get("employee_id"),
            reason=booking.get("reason", ""),
        )
        alloc_res = allocate(req, exclude_driver_ids=tuple(exclude_set), exclude_booking_id=bid, db_conn=conn)
        if alloc_res.ok and alloc_res.options:
            new_opt = alloc_res.options[0]
            updates["driver_id"] = new_opt.driver_id
            updates["vehicle_id"] = new_opt.vehicle_id
            updates["decision_reason"] = f"Reassigned driver after rejection: {new_opt.reason}"
        else:
            updates["driver_id"] = None
            updates["decision_reason"] = f"Driver rejected ({reason}); no replacement available. Awaiting manager intervention."
            for m_id in MANAGER_PROFILE_IDS:
                create_notification(m_id, f"Driver rejected booking {bid}. No replacement found.", booking_id=bid, conn=conn)

    elif new_status == "IN_PROGRESS":
        action_name = action_name or "trip_started"
        start_odo = extra_data.get("start_odometer") if extra_data else None
        checklist = extra_data.get("checklist") if extra_data else None
        create_or_update_trip(
            bid,
            {
                "start_odometer": start_odo,
                "checklist": checklist,
                "actual_start": now_utc,
            },
            conn=conn,
        )
        if booking.get("driver_id"):
            update_driver(booking["driver_id"], {"status": "on_trip"}, conn=conn)

        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Trip {bid} is now in progress.", booking_id=bid, conn=conn)

    elif new_status == "COMPLETED":
        action_name = action_name or "trip_completed"
        end_odo = extra_data.get("end_odometer") if extra_data else None
        fuel = extra_data.get("fuel_added") if extra_data else None
        create_or_update_trip(
            bid,
            {
                "end_odometer": end_odo,
                "fuel_added": fuel,
                "actual_end": now_utc,
            },
            conn=conn,
        )
        if booking.get("driver_id"):
            update_driver(booking["driver_id"], {"status": "available"}, conn=conn)
        if booking.get("vehicle_id"):
            veh_updates: Dict[str, Any] = {"status": "available"}
            if end_odo is not None:
                veh_updates["odometer_km"] = end_odo
            update_vehicle(booking["vehicle_id"], veh_updates, conn=conn)

        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Trip {bid} completed. Please rate your driver & vehicle!", booking_id=bid, conn=conn)

    elif new_status == "REJECTED":
        action_name = action_name or "rejected"
        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Booking {bid} rejected. Reason: {note or 'Not specified'}", booking_id=bid, conn=conn)

    elif new_status == "CANCELLED":
        action_name = action_name or "cancelled"
        if booking.get("driver_id") and booking.get("status") == "IN_PROGRESS":
            update_driver(booking["driver_id"], {"status": "available"}, conn=conn)
        if booking.get("vehicle_id") and booking.get("status") == "IN_PROGRESS":
            update_vehicle(booking["vehicle_id"], {"status": "available"}, conn=conn)

        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Booking {bid} has been cancelled.", booking_id=bid, conn=conn)

    elif new_status == "BUMPED":
        action_name = action_name or "bumped"
        updates["was_bumped"] = True
        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Booking {bid} was bumped by an emergency request.", booking_id=bid, conn=conn)
        for m_id in MANAGER_PROFILE_IDS:
            create_notification(m_id, f"Booking {bid} was bumped by an emergency request.", booking_id=bid, conn=conn)

    elif new_status == "WAITLISTED":
        action_name = action_name or ("bumped_waitlisted" if current_status == "BUMPED" else "waitlisted")
        updates["vehicle_id"] = None
        updates["driver_id"] = None
        if current_status == "BUMPED" or booking.get("was_bumped"):
            updates["was_bumped"] = True
        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Booking {bid} was placed on the waitlist.", booking_id=bid, conn=conn)

    elif new_status == "PENDING" and current_status == "WAITLISTED":
        action_name = action_name or "waitlist_promoted"
        emp_id = booking.get("employee_id")
        if emp_id:
            create_notification(emp_id, f"Your waitlisted booking {bid} has an available vehicle & driver!", booking_id=bid, conn=conn)

    # Apply any extra data fields passed in (safeguard: do not let rejected driver overwrite reallocated driver)
    if extra_data:
        for field in ("vehicle_id", "driver_id", "decision_reason", "failure_reason", "blocked_until", "respond_by", "was_bumped"):
            if field in extra_data:
                if field == "driver_id" and new_status == "PENDING" and current_status == "DRIVER_PENDING":
                    continue
                updates[field] = extra_data[field]

    # 4. Perform database update FIRST so slot is officially freed before waitlist check
    updated = update_booking(bid, updates, conn=conn)

    # 5. Record to decision_log
    log_actor_id = actor_id if (actor_id and actor_id != "system") else None
    add_decision_log(bid, log_actor_id, action=action_name or new_status.lower(), note=note, conn=conn)

    # 6. Trigger waitlist auto-promotion on slot-freeing events AFTER database update
    if new_status in ("COMPLETED", "REJECTED", "CANCELLED", "BUMPED"):
        try:
            from app.engine.waitlist import promote_waitlisted
            promote_waitlisted(conn=conn)
        except Exception as exc:
            logger.warning("Waitlist promotion failed during transition of booking %s: %s", bid, exc)

    return updated
