"""Driver management and mobile PWA workflow endpoints (Team KNIGHT | PS 40).

Endpoints:
- GET   /api/drivers: List all drivers (Manager only)
- GET   /api/drivers/<id>: Single driver (Manager only)
- POST  /api/drivers: Register driver (Manager only)
- PATCH /api/drivers/<id>: Update driver (Manager only)
- GET   /api/driver/requests: Fetch incoming DRIVER_PENDING assignments
- POST  /api/driver/bookings/<id>/accept: Accept assigned trip -> CONFIRMED
- POST  /api/driver/bookings/<id>/reject: Reject with mandatory reason -> driver_responses logged
"""
from typing import Any, Dict
from flask import Blueprint, jsonify, request, g

from app.auth import require_role
from app.db import (
    get_all_drivers,
    get_driver_by_id,
    get_driver_by_profile_id,
    get_profile_by_id,
    create_driver,
    update_driver,
    get_booking_by_id,
    query_bookings,
    serialize_booking,
)
from app.services.transitions import (
    transition,
    IllegalTransitionError,
    ForbiddenTransitionError,
    BookingNotFoundError,
)

drivers_bp = Blueprint("drivers", __name__, url_prefix="/api/drivers")
driver_bp = Blueprint("driver", __name__, url_prefix="/api/driver")

ALLOWED_REJECT_REASONS = {"tired", "vehicle_issue", "personal", "too_far", "unsafe", "other"}


def _get_current_driver_id() -> str | None:
    """Helper to resolve driver ID for the currently authenticated user."""
    user = getattr(g, "current_user", None)
    if not user:
        return None
    if user.get("driver_id"):
        return str(user["driver_id"])
    drv = get_driver_by_profile_id(user["id"])
    if drv:
        return str(drv.get("id"))
    return None


@drivers_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "drivers", "status": "pong"})


# ---------------------------------------------------------
# Manager Driver CRUD
# ---------------------------------------------------------

@drivers_bp.route("", methods=["GET"])
@require_role("manager")
def list_drivers():
    """List drivers with profile info, statuses, ratings, licenses (Manager only)."""
    drivers = get_all_drivers()
    status_filter = request.args.get("status")
    if status_filter:
        drivers = [d for d in drivers if d.get("status") == status_filter]
    return jsonify({"drivers": drivers}), 200


@drivers_bp.route("/<driver_id>", methods=["GET"])
@require_role("manager")
def get_driver(driver_id: str):
    """Get single driver by ID with profile info (Manager only)."""
    driver = get_driver_by_id(driver_id)
    if not driver:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Driver not found with ID {driver_id}",
                "alternatives": [],
            }
        }), 404
    return jsonify({"driver": driver}), 200


@drivers_bp.route("", methods=["POST"])
@require_role("manager")
def add_driver():
    """Register a driver linked to a profile (Manager only)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a JSON object",
                "alternatives": [],
            }
        }), 400

    profile_id = data.get("profile_id")
    profile = None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        driver_name = str(data.get("name", "")).strip()
        if not driver_name:
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Either 'name' or 'profile_id' is required to register a driver",
                    "alternatives": [],
                }
            }), 400
        from app.db import create_profile, get_profile_by_email
        drv_custom_id = str(data.get("id") or "").strip()
        drv_email = str(data.get("email", "")).strip() or f"driver_{driver_name.lower().replace(' ', '')}@fleetride.local"

        if drv_custom_id and get_profile_by_id(drv_custom_id):
            return jsonify({
                "error": {
                    "code": "CONFLICT",
                    "message": f"Profile with ID '{drv_custom_id}' already exists",
                    "alternatives": [],
                }
            }), 409

        if drv_email and get_profile_by_email(drv_email):
            return jsonify({
                "error": {
                    "code": "CONFLICT",
                    "message": f"Profile with email '{drv_email}' already exists",
                    "alternatives": [],
                }
            }), 409

        new_prof = create_profile({
            "id": drv_custom_id or None,
            "name": driver_name,
            "role": "driver",
            "phone": str(data.get("phone", "")).strip() or None,
            "email": drv_email,
        })
        profile_id = new_prof["id"]
        profile = new_prof
    else:
        profile = get_profile_by_id(profile_id.strip())
        if not profile:
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": f"Profile not found with ID {profile_id}",
                    "alternatives": [],
                }
            }), 400

    existing_driver = get_driver_by_profile_id(profile_id.strip())
    if existing_driver:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Driver already registered for profile ID {profile_id}",
                "alternatives": [],
            }
        }), 400

    status = data.get("status", "available")
    if status not in ("off", "available", "on_trip", "break"):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Invalid driver status '{status}'. Must be 'off', 'available', 'on_trip', or 'break'",
                "alternatives": [],
            }
        }), 400

    rating_avg = data.get("rating_avg", 5.0)
    if isinstance(rating_avg, bool) or not isinstance(rating_avg, (int, float)) or rating_avg < 1.0 or rating_avg > 5.0:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Rating must be a number between 1.0 and 5.0",
                "alternatives": [],
            }
        }), 400

    license_no = data.get("license_no", "")
    created = create_driver({
        "profile_id": profile_id.strip(),
        "status": status,
        "rating_avg": float(rating_avg),
        "license_no": license_no,
    })
    return jsonify({"driver": created}), 201


@drivers_bp.route("/<driver_id>", methods=["PATCH"])
@require_role("manager")
def modify_driver(driver_id: str):
    """Update driver status, rating, or license (Manager only)."""
    driver = get_driver_by_id(driver_id)
    if not driver:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Driver not found with ID {driver_id}",
                "alternatives": [],
            }
        }), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a JSON object",
                "alternatives": [],
            }
        }), 400

    if "status" in data:
        status = data["status"]
        if status not in ("off", "available", "on_trip", "break"):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": f"Invalid driver status '{status}'. Must be 'off', 'available', 'on_trip', or 'break'",
                    "alternatives": [],
                }
            }), 400

    if "rating_avg" in data:
        rating = data["rating_avg"]
        if isinstance(rating, bool) or not isinstance(rating, (int, float)) or rating < 1.0 or rating > 5.0:
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Rating must be a number between 1.0 and 5.0",
                    "alternatives": [],
                }
            }), 400

    if "license_no" in data and data["license_no"] is not None:
        if not isinstance(data["license_no"], str):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "License number must be a string",
                    "alternatives": [],
                }
            }), 400

    updated = update_driver(driver_id, data)
    return jsonify({"driver": updated}), 200


# ---------------------------------------------------------
# Driver Workflow Actions: Requests, Accept, Reject
# ---------------------------------------------------------

def handle_driver_requests():
    """Shared handler to list DRIVER_PENDING requests for authenticated driver."""
    drv_id = _get_current_driver_id()
    if not drv_id:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Authenticated user is not registered as a driver",
                "alternatives": [],
            }
        }), 403

    reqs = query_bookings(active_only=False, driver_id=drv_id, status="DRIVER_PENDING")
    serialized = [serialize_booking(b) for b in reqs]
    return jsonify({"requests": serialized, "count": len(serialized)}), 200


def handle_driver_accept(booking_id: str):
    """Shared handler to accept trip assignment -> CONFIRMED."""
    drv_id = _get_current_driver_id()
    if not drv_id:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Authenticated user is not registered as a driver",
                "alternatives": [],
            }
        }), 403

    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    if str(b.get("driver_id")) != drv_id:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Driver is not assigned to this booking",
                "alternatives": [],
            }
        }), 403

    if b.get("status") != "DRIVER_PENDING":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot accept booking in status '{b.get('status')}'; must be DRIVER_PENDING",
                "alternatives": [],
            }
        }), 400

    try:
        updated = transition(booking_id, "CONFIRMED", g.current_user)
        return jsonify({
            "booking": serialize_booking(updated),
            "status": "CONFIRMED",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


def handle_driver_reject(booking_id: str):
    """Shared handler to reject trip assignment with mandatory reason."""
    drv_id = _get_current_driver_id()
    if not drv_id:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Authenticated user is not registered as a driver",
                "alternatives": [],
            }
        }), 403

    b = get_booking_by_id(booking_id)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {booking_id}",
                "alternatives": [],
            }
        }), 404

    if str(b.get("driver_id")) != drv_id:
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Driver is not assigned to this booking",
                "alternatives": [],
            }
        }), 403

    if b.get("status") != "DRIVER_PENDING":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot reject booking in status '{b.get('status')}'; must be DRIVER_PENDING",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason") or data.get("reject_reason") or "").strip().lower()
    if not reason or reason not in ALLOWED_REJECT_REASONS:
        return jsonify({
            "error": {
                "code": "INVALID_REJECT_REASON",
                "message": f"Reject reason must be one of: {sorted(list(ALLOWED_REJECT_REASONS))}",
                "alternatives": [],
            }
        }), 400

    try:
        updated = transition(
            booking_id,
            "PENDING",
            g.current_user,
            note=f"Driver rejected: {reason}",
            extra_data={"reject_reason": reason, "rejecting_driver_id": drv_id},
        )
        return jsonify({
            "booking": serialize_booking(updated),
            "status": updated.get("status"),
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


# Register on driver_bp (/api/driver/...)
@driver_bp.route("/requests", methods=["GET"])
@require_role("driver")
def driver_requests_singular():
    return handle_driver_requests()


@driver_bp.route("/bookings/<booking_id>/accept", methods=["POST"])
@require_role("driver")
def driver_accept_singular(booking_id: str):
    return handle_driver_accept(booking_id)


@driver_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
@require_role("driver")
def driver_reject_singular(booking_id: str):
    return handle_driver_reject(booking_id)


# Also register on drivers_bp (/api/drivers/...) for convenience
@drivers_bp.route("/requests", methods=["GET"])
@require_role("driver")
def driver_requests_plural():
    return handle_driver_requests()


@drivers_bp.route("/bookings/<booking_id>/accept", methods=["POST"])
@require_role("driver")
def driver_accept_plural(booking_id: str):
    return handle_driver_accept(booking_id)


@drivers_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
@require_role("driver")
def driver_reject_plural(booking_id: str):
    return handle_driver_reject(booking_id)
