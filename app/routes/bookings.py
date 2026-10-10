"""Employee booking routes (Team KNIGHT | PS 40).

Endpoints:
- POST /api/bookings: Submit request, idempotency check, allocate, auto-approve rule.
- GET  /api/bookings/mine: List current user's bookings.
- GET  /api/bookings/<id>: Retrieve single booking.
- POST /api/bookings/<id>/cancel: Cancel booking before trip starts.
"""
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict
import zoneinfo
from flask import Blueprint, jsonify, request, g

from app.auth import require_role
from app.config import get_app_config
from app.db import (
    create_booking,
    get_booking_by_id,
    query_bookings,
    get_recent_pending_booking,
    serialize_booking,
    _to_utc_dt,
)
from app.engine.allocate import allocate, BookingRequest
from app.services.transitions import (
    transition,
    IllegalTransitionError,
    ForbiddenTransitionError,
    BookingNotFoundError,
)

bookings_bp = Blueprint("bookings", __name__, url_prefix="/api/bookings")
KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


@bookings_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "bookings", "status": "pong"})


@bookings_bp.route("", methods=["POST"])
@require_role("employee", "manager")
def create_booking_request():
    """Submit booking request with idempotency guard, allocate engine, and auto-approve."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a JSON object",
                "alternatives": [],
            }
        }), 400

    # 1. Determine employee
    current_user = g.current_user
    employee_id = current_user["id"]
    if current_user.get("role") == "manager" and data.get("employee_id"):
        employee_id = str(data["employee_id"]).strip()

    # 2. Idempotency guard: reject duplicate pending request from same employee within 30s
    recent_pending = get_recent_pending_booking(employee_id, within_seconds=30)
    if recent_pending:
        return jsonify({
            "error": {
                "code": "DUPLICATE_REQUEST",
                "message": "A pending booking request was already submitted within the last 30 seconds",
                "alternatives": [],
            }
        }), 409

    # 3. Input validations
    passengers_raw = data.get("passengers")
    if passengers_raw is None:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Field 'passengers' is required",
                "alternatives": [],
            }
        }), 400

    try:
        passengers = int(passengers_raw)
    except (ValueError, TypeError):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Field 'passengers' must be an integer",
                "alternatives": [],
            }
        }), 400

    if passengers < 1 or passengers > 60:
        return jsonify({
            "error": {
                "code": "INVALID_PASSENGERS",
                "message": "Passenger count must be between 1 and 60",
                "alternatives": [],
            }
        }), 400

    start_raw = data.get("start_time") or data.get("start")
    end_raw = data.get("end_time") or data.get("end")
    if not start_raw or not end_raw:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Fields 'start_time' and 'end_time' are required",
                "alternatives": [],
            }
        }), 400

    try:
        start_utc = _to_utc_dt(start_raw)
        end_utc = _to_utc_dt(end_raw)
    except Exception as exc:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Invalid datetime format: {str(exc)}",
                "alternatives": [],
            }
        }), 400

    if not start_utc or not end_utc:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Could not parse start_time or end_time",
                "alternatives": [],
            }
        }), 400

    now_utc = datetime.now(timezone.utc)
    if start_utc < now_utc - timedelta(seconds=60):
        return jsonify({
            "error": {
                "code": "INVALID_TIME",
                "message": "Booking start time must be in the future",
                "alternatives": [],
            }
        }), 400

    if end_utc <= start_utc:
        return jsonify({
            "error": {
                "code": "INVALID_TIME",
                "message": "Booking end time must be strictly after start time",
                "alternatives": [],
            }
        }), 400

    destination = str(data.get("destination", "")).strip()
    if not destination:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Field 'destination' is required",
                "alternatives": [],
            }
        }), 400

    reason = str(data.get("reason", "")).strip()
    if not reason:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Field 'reason' is required",
                "alternatives": [],
            }
        }), 400

    booking_type = data.get("type", "scheduled")
    if booking_type not in ("scheduled", "emergency"):
        booking_type = "scheduled"

    priority = data.get("priority", "emergency" if booking_type == "emergency" else "normal")
    if priority not in ("low", "normal", "high", "emergency"):
        priority = "normal"

    config = get_app_config()
    buffer_min = int(config.get("buffer_minutes", 15))
    blocked_until = end_utc + timedelta(minutes=buffer_min)

    # 3b. Validate optional destination coordinates
    dest_lat = data.get("dest_lat")
    dest_lng = data.get("dest_lng")

    if dest_lat is not None and dest_lat != "":
        if isinstance(dest_lat, bool):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Field 'dest_lat' must be a valid number between -90 and 90",
                    "alternatives": [],
                }
            }), 400
        try:
            dest_lat = float(dest_lat)
        except (ValueError, TypeError):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Field 'dest_lat' must be a valid float",
                    "alternatives": [],
                }
            }), 400
        if not (-90.0 <= dest_lat <= 90.0):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Field 'dest_lat' must be between -90 and 90",
                    "alternatives": [],
                }
            }), 400
    else:
        dest_lat = None

    if dest_lng is not None and dest_lng != "":
        if isinstance(dest_lng, bool):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Field 'dest_lng' must be a valid number between -180 and 180",
                    "alternatives": [],
                }
            }), 400
        try:
            dest_lng = float(dest_lng)
        except (ValueError, TypeError):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Field 'dest_lng' must be a valid float",
                    "alternatives": [],
                }
            }), 400
        if not (-180.0 <= dest_lng <= 180.0):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Field 'dest_lng' must be between -180 and 180",
                    "alternatives": [],
                }
            }), 400
    else:
        dest_lng = None

    # 3c. Direct waitlist request
    if data.get("waitlist") is True:
        wait_record = {
            "employee_id": employee_id,
            "vehicle_id": None,
            "driver_id": None,
            "start_time": start_utc,
            "end_time": end_utc,
            "blocked_until": blocked_until,
            "destination": destination,
            "dest_lat": dest_lat,
            "dest_lng": dest_lng,
            "passengers": passengers,
            "reason": reason,
            "type": booking_type,
            "priority": priority,
            "status": "WAITLISTED",
            "decision_reason": "Waitlisted upon employee request",
            "failure_reason": data.get("failure_reason", "WAITLISTED"),
            "was_bumped": False,
        }
        created = transition(
            booking_id=None,
            new_status="WAITLISTED",
            actor=current_user,
            note="Employee joined waitlist for requested slot",
            extra_data=wait_record,
        )
        return jsonify({
            "booking": serialize_booking(created),
            "status": "WAITLISTED",
        }), 201

    # 4. Run allocation engine
    req_obj = BookingRequest(
        start=start_utc,
        end=end_utc,
        passengers=passengers,
        type=booking_type,
        priority=priority,
        destination=destination,
        dest_lat=dest_lat,
        dest_lng=dest_lng,
        employee_id=employee_id,
        reason=reason,
    )

    alloc_result = allocate(req_obj)

    # 5. Handle allocation failure
    if not alloc_result.ok:
        # Check if emergency bump can be performed
        if booking_type == "emergency" or priority == "emergency":
            from app.engine.bump import find_bump_candidate, execute_bump
            bump_candidate = find_bump_candidate(req_obj)
            if bump_candidate:
                emg_data = {
                    "employee_id": employee_id,
                    "start_time": start_utc,
                    "end_time": end_utc,
                    "blocked_until": blocked_until,
                    "destination": destination,
                    "dest_lat": dest_lat,
                    "dest_lng": dest_lng,
                    "passengers": passengers,
                    "reason": reason,
                    "type": "emergency",
                    "priority": "emergency",
                }
                final_emg, bumped_bkg = execute_bump(bump_candidate, emg_data, actor=current_user)
                return jsonify({
                    "booking": serialize_booking(final_emg),
                    "bumped_booking_id": bumped_bkg["id"],
                    "bumped": True,
                    "status": "DRIVER_PENDING",
                    "auto_approved": True,
                }), 201

        alternatives = [
            a.to_dict() if hasattr(a, "to_dict") else a
            for a in alloc_result.alternatives
        ]
        return jsonify({
            "ok": False,
            "failure_reason": alloc_result.failure_reason,
            "alternatives": alternatives,
            "error": {
                "code": alloc_result.failure_reason or "ALLOCATION_FAILED",
                "message": f"Allocation failed: {alloc_result.failure_reason}",
                "alternatives": alternatives,
            }
        }), 422

    # 6. Allocation succeeded: insert as PENDING
    top_option = alloc_result.options[0]
    booking_record = {
        "employee_id": employee_id,
        "vehicle_id": top_option.vehicle_id,
        "driver_id": top_option.driver_id,
        "start_time": start_utc,
        "end_time": end_utc,
        "blocked_until": blocked_until,
        "destination": destination,
        "dest_lat": dest_lat,
        "dest_lng": dest_lng,
        "passengers": passengers,
        "reason": reason,
        "type": booking_type,
        "priority": priority,
        "status": "PENDING",
        "decision_reason": top_option.reason,
        "was_bumped": False,
    }

    # Route initial creation through state machine: (new) -> PENDING
    created = transition(
        booking_id=None,
        new_status="PENDING",
        actor=current_user,
        note=top_option.reason,
        extra_data=booking_record,
    )
    booking_id = created["id"]

    # 7. Check Auto-Approve Rule (SPEC.md Section 4.1 & 4.3)
    # Rule A: Emergency bookings skip approval queue and enter DRIVER_PENDING directly (2 min window)
    # Rule B: Scheduled, priority in ('low', 'normal'), duration <= auto_approve_max_hours (4h),
    # and within working_hours (08:00-20:00 in Asia/Kolkata).
    is_auto_approved = False
    duration_hours = (end_utc - start_utc).total_seconds() / 3600.0
    auto_approve_max_h = float(config.get("auto_approve_max_hours", 4.0))

    start_kolkata = start_utc.astimezone(KOLKATA_TZ)
    end_kolkata = end_utc.astimezone(KOLKATA_TZ)
    working_hours_str = str(config.get("working_hours", "08:00-20:00"))
    try:
        wh_parts = working_hours_str.split("-")
        wh_start = dtime.fromisoformat(wh_parts[0].strip())
        wh_end = dtime.fromisoformat(wh_parts[1].strip())
    except Exception:
        wh_start = dtime(8, 0)
        wh_end = dtime(20, 0)

    within_working_hours = (
        start_kolkata.date() == end_kolkata.date()
        and start_kolkata.time() >= wh_start
        and end_kolkata.time() <= wh_end
    )

    if booking_type == "emergency":
        # Emergencies skip manager queue and enter DRIVER_PENDING directly
        system_actor = {"id": "system", "role": "system"}
        transition(booking_id, "APPROVED", system_actor, note="Emergency booking auto-approved")
        win_min = int(config.get("respond_window_emergency_min", 2))
        respond_by_dt = datetime.now(timezone.utc) + timedelta(minutes=win_min)
        created = transition(
            booking_id,
            "DRIVER_PENDING",
            system_actor,
            note="Dispatched to driver (emergency)",
            extra_data={"respond_by": respond_by_dt},
        )
        is_auto_approved = True
    elif (
        booking_type == "scheduled"
        and priority in ("low", "normal")
        and duration_hours <= auto_approve_max_h
        and within_working_hours
    ):
        # Automatically transition PENDING -> APPROVED -> DRIVER_PENDING
        system_actor = {"id": "system", "role": "system"}
        transition(booking_id, "APPROVED", system_actor, note="Auto-approved by policy rule")
        respond_win = int(config.get("respond_window_scheduled_min", 30))
        respond_by_dt = datetime.now(timezone.utc) + timedelta(minutes=respond_win)
        created = transition(
            booking_id,
            "DRIVER_PENDING",
            system_actor,
            note="Dispatched to driver via auto-approve",
            extra_data={"respond_by": respond_by_dt},
        )
        is_auto_approved = True

    options_list = [
        opt.to_dict() if hasattr(opt, "to_dict") else opt
        for opt in alloc_result.options[:3]
    ]

    return jsonify({
        "booking": serialize_booking(created),
        "options": options_list,
        "auto_approved": is_auto_approved,
    }), 201


@bookings_bp.route("/mine", methods=["GET"])
@require_role("employee", "manager", "driver")
def list_my_bookings():
    """List bookings belonging to authenticated user."""
    user = g.current_user
    user_id = user["id"]
    if user.get("role") == "driver":
        drv_id = user.get("driver_id")
        if not drv_id:
            from app.db import get_driver_by_profile_id
            drv = get_driver_by_profile_id(user_id)
            if drv:
                drv_id = drv.get("id")
        bookings = query_bookings(active_only=False, driver_id=drv_id) if drv_id else []
    else:
        bookings = query_bookings(active_only=False, employee_id=user_id)
    return jsonify({
        "bookings": [serialize_booking(b) for b in bookings]
    }), 200


@bookings_bp.route("/<booking_id>", methods=["GET"])
@require_role("employee", "manager", "driver")
def get_booking(booking_id: str):
    """Fetch single booking by ID."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    user = g.current_user
    # Employees can only view own bookings, drivers assigned bookings, managers all
    if user["role"] == "employee" and str(b.get("employee_id")) != user["id"]:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Access denied to booking",
                "alternatives": [],
            }
        }), 403

    return jsonify({"booking": serialize_booking(b)}), 200


@bookings_bp.route("/<booking_id>/cancel", methods=["POST"])
@require_role("employee", "manager")
def cancel_booking(booking_id: str):
    """Cancel booking before trip starts (Employee own, Manager any)."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    user = g.current_user
    if user["role"] == "employee" and str(b.get("employee_id")) != user["id"]:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Cannot cancel another employee's booking",
                "alternatives": [],
            }
        }), 403

    current_status = b.get("status")
    if current_status not in ("PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED"):
        return jsonify({
            "error": {
                "code": "CANNOT_CANCEL",
                "message": f"Cannot cancel booking with status '{current_status}'",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    note = data.get("note") or data.get("reason", "Cancelled by user")

    try:
        updated = transition(booking_id, "CANCELLED", user, note=note)
        return jsonify({
            "booking": serialize_booking(updated),
            "status": "CANCELLED",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


@bookings_bp.route("/<booking_id>/waitlist", methods=["POST"])
@require_role("employee", "manager")
def join_waitlist(booking_id: str):
    """Join waitlist for a bumped or unmet booking request."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    user = g.current_user
    if user["role"] == "employee" and str(b.get("employee_id")) != user["id"]:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Cannot waitlist another employee's booking",
                "alternatives": [],
            }
        }), 403

    current_status = b.get("status")
    if current_status not in ("BUMPED", "WAITLISTED"):
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot join waitlist from status '{current_status}'",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    note = data.get("note", "Employee joined waitlist")

    try:
        updated = transition(
            booking_id,
            "WAITLISTED",
            user,
            note=note,
            extra_data={"was_bumped": b.get("was_bumped", False)},
        )
        return jsonify({
            "booking": serialize_booking(updated),
            "status": "WAITLISTED",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


@bookings_bp.route("/<booking_id>/choose-alternative", methods=["POST"])
@require_role("employee", "manager")
def choose_alternative(booking_id: str):
    """Confirm alternative slot option after failure or bump."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    user = g.current_user
    if user["role"] == "employee" and str(b.get("employee_id")) != user["id"]:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Cannot modify another employee's booking",
                "alternatives": [],
            }
        }), 403

    current_status = b.get("status")
    if current_status not in ("BUMPED", "WAITLISTED"):
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot choose alternative for booking in status '{current_status}'",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    start_raw = data.get("start_time") or data.get("start")
    end_raw = data.get("end_time") or data.get("end")
    alt_data: Dict[str, Any] = {"was_bumped": b.get("was_bumped", False)}

    if start_raw and end_raw:
        st_utc = _to_utc_dt(start_raw)
        et_utc = _to_utc_dt(end_raw)
        if st_utc and et_utc:
            alt_data["start_time"] = st_utc
            alt_data["end_time"] = et_utc
            config = get_app_config()
            buf_min = int(config.get("buffer_minutes", 15))
            alt_data["blocked_until"] = et_utc + timedelta(minutes=buf_min)

    if data.get("vehicle_id"):
        alt_data["vehicle_id"] = str(data["vehicle_id"])
    if data.get("driver_id"):
        alt_data["driver_id"] = str(data["driver_id"])

    note = data.get("note", "Employee selected alternative option")

    try:
        updated = transition(
            booking_id,
            "PENDING",
            user,
            note=note,
            extra_data=alt_data,
        )
        return jsonify({
            "booking": serialize_booking(updated),
            "status": "PENDING",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400
