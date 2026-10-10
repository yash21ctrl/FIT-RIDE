"""Manager operations and approval queue endpoints (Team KNIGHT | PS 40).

Endpoints:
- GET  /api/manager/queue: Fetch pending approval queue with suggestions.
- POST /api/manager/bookings/<id>/approve: Approve booking -> advances to DRIVER_PENDING.
- POST /api/manager/bookings/<id>/override: Override vehicle or driver assignment -> DRIVER_PENDING.
- POST /api/manager/bookings/<id>/reject: Reject booking with mandatory reason.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from flask import Blueprint, jsonify, request, g

from app.auth import require_role
from app.config import get_app_config
from app.db import (
    get_booking_by_id,
    query_bookings,
    get_vehicle_by_id,
    get_driver_by_id,
    serialize_booking,
    _to_utc_dt,
)
from app.services.transitions import (
    transition,
    IllegalTransitionError,
    ForbiddenTransitionError,
    BookingNotFoundError,
)

manager_bp = Blueprint("manager", __name__, url_prefix="/api/manager")


@manager_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "manager", "status": "pong"})


@manager_bp.route("/queue", methods=["GET"])
@require_role("manager")
def approval_queue():
    """List bookings awaiting manager approval (status PENDING)."""
    pending = query_bookings(active_only=False, status="PENDING")
    queue_items = []
    for b in pending:
        item = serialize_booking(b)
        if b.get("vehicle_id"):
            veh = get_vehicle_by_id(b["vehicle_id"])
            if veh:
                item["vehicle_name"] = veh.get("name")
                item["vehicle_capacity"] = veh.get("capacity")
        if b.get("driver_id"):
            drv = get_driver_by_id(b["driver_id"])
            if drv:
                item["driver_name"] = drv.get("name")
        queue_items.append(item)

    return jsonify({"queue": queue_items, "count": len(queue_items)}), 200


@manager_bp.route("/bookings/<booking_id>/approve", methods=["POST"])
@require_role("manager")
def approve_booking(booking_id: str):
    """Approve booking and advance to DRIVER_PENDING with respond_by window."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    if b.get("status") != "PENDING":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot approve booking in status '{b.get('status')}'; must be PENDING",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    note = data.get("note", "Approved by manager")

    try:
        # Step 1: PENDING -> APPROVED
        transition(booking_id, "APPROVED", g.current_user, note=note)

        # Step 2: APPROVED -> DRIVER_PENDING
        config = get_app_config()
        win_min = int(config.get("respond_window_emergency_min", 2)) if b.get("type") == "emergency" else int(config.get("respond_window_scheduled_min", 30))
        respond_by_dt = datetime.now(timezone.utc) + timedelta(minutes=win_min)

        updated = transition(
            booking_id,
            "DRIVER_PENDING",
            {"id": g.current_user["id"], "role": "system"},
            note="Dispatched to driver",
            extra_data={"respond_by": respond_by_dt},
        )

        return jsonify({
            "booking": serialize_booking(updated),
            "status": "DRIVER_PENDING",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


@manager_bp.route("/bookings/<booking_id>/override", methods=["POST"])
@require_role("manager")
def override_booking(booking_id: str):
    """Override vehicle or driver assignment, validating constraints, and advance to DRIVER_PENDING."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    current_status = b.get("status")
    if current_status not in ("PENDING", "APPROVED", "DRIVER_PENDING"):
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot override booking in status '{current_status}'",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a JSON object",
                "alternatives": [],
            }
        }), 400

    new_vehicle_id = data.get("vehicle_id")
    new_driver_id = data.get("driver_id")
    if not new_vehicle_id and not new_driver_id:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Must provide 'vehicle_id' and/or 'driver_id' to override",
                "alternatives": [],
            }
        }), 400

    st_utc = _to_utc_dt(b["start_time"])
    bu_utc = _to_utc_dt(b.get("blocked_until") or b["end_time"])

    # Validate vehicle if supplied
    if new_vehicle_id:
        veh = get_vehicle_by_id(str(new_vehicle_id))
        if not veh:
            return jsonify({
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Vehicle not found with ID {new_vehicle_id}",
                    "alternatives": [],
                }
            }), 404
        if veh.get("status") == "retired":
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Cannot assign a retired vehicle",
                    "alternatives": [],
                }
            }), 400
        if int(veh.get("capacity", 0)) < int(b.get("passengers", 1)):
            return jsonify({
                "error": {
                    "code": "INSUFFICIENT_CAPACITY",
                    "message": f"Vehicle capacity {veh.get('capacity')} is less than requested {b.get('passengers')} passengers",
                    "alternatives": [],
                }
            }), 400

        # Overlap check
        all_bookings = query_bookings(active_only=True)
        for ob in all_bookings:
            if ob["id"] == b["id"]:
                continue
            if str(ob.get("vehicle_id")) == str(new_vehicle_id):
                ob_st = _to_utc_dt(ob["start_time"])
                ob_bu = _to_utc_dt(ob.get("blocked_until") or ob["end_time"])
                if ob_st < bu_utc and st_utc < ob_bu:
                    return jsonify({
                        "error": {
                            "code": "VEHICLE_TAKEN",
                            "message": f"Vehicle '{veh.get('name')}' is already reserved during this time slot",
                            "alternatives": [],
                        }
                    }), 409

    # Validate driver if supplied
    if new_driver_id:
        drv = get_driver_by_id(str(new_driver_id))
        if not drv:
            return jsonify({
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Driver not found with ID {new_driver_id}",
                    "alternatives": [],
                }
            }), 404
        if drv.get("status") == "off":
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Cannot assign an off-duty driver",
                    "alternatives": [],
                }
            }), 400

        all_bookings = query_bookings(active_only=True)
        for ob in all_bookings:
            if ob["id"] == b["id"]:
                continue
            if str(ob.get("driver_id")) == str(new_driver_id):
                ob_st = _to_utc_dt(ob["start_time"])
                ob_bu = _to_utc_dt(ob.get("blocked_until") or ob["end_time"])
                if ob_st < bu_utc and st_utc < ob_bu:
                    return jsonify({
                        "error": {
                            "code": "DRIVER_BUSY",
                            "message": f"Driver '{drv.get('name')}' has a conflicting trip during this window",
                            "alternatives": [],
                        }
                    }), 409

    note = data.get("note") or f"Manual override by manager {g.current_user.get('name', '')}"
    override_data: Dict[str, Any] = {"action": "overridden"}
    if new_vehicle_id:
        override_data["vehicle_id"] = str(new_vehicle_id)
    if new_driver_id:
        override_data["driver_id"] = str(new_driver_id)
    override_data["decision_reason"] = f"Manager override: {note}"

    config = get_app_config()
    win_min = int(config.get("respond_window_emergency_min", 2)) if b.get("type") == "emergency" else int(config.get("respond_window_scheduled_min", 30))
    override_data["respond_by"] = datetime.now(timezone.utc) + timedelta(minutes=win_min)

    try:
        if current_status == "PENDING":
            transition(booking_id, "APPROVED", g.current_user, note=note)

        updated = transition(
            booking_id,
            "DRIVER_PENDING",
            g.current_user,
            note=note,
            extra_data=override_data,
        )

        return jsonify({
            "booking": serialize_booking(updated),
            "status": "DRIVER_PENDING",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


@manager_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
@require_role("manager")
def reject_booking(booking_id: str):
    """Reject booking with mandatory reason."""
    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    if b.get("status") != "PENDING":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot reject booking in status '{b.get('status')}'; must be PENDING",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    if not reason or not str(reason).strip():
        return jsonify({
            "error": {
                "code": "REASON_REQUIRED",
                "message": "Rejection reason is mandatory",
                "alternatives": [],
            }
        }), 400

    try:
        updated = transition(booking_id, "REJECTED", g.current_user, note=str(reason).strip())
        return jsonify({
            "booking": serialize_booking(updated),
            "status": "REJECTED",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400
