"""Trip execution endpoints (Team KNIGHT | PS 40).

Endpoints:
- POST /api/trips/<booking_id>/start: Log starting odometer & checklist -> IN_PROGRESS.
- POST /api/trips/<booking_id>/end: Log ending odometer & fuel -> COMPLETED.
"""
from typing import Any, Dict
from flask import Blueprint, jsonify, request, g

from app.auth import require_role
from app.db import (
    get_booking_by_id,
    get_trip_by_booking_id,
    get_driver_by_profile_id,
    serialize_booking,
)
from app.services.transitions import (
    transition,
    IllegalTransitionError,
    ForbiddenTransitionError,
    BookingNotFoundError,
)

trips_bp = Blueprint("trips", __name__, url_prefix="/api/trips")


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


@trips_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "trips", "status": "pong"})


@trips_bp.route("/<booking_id>/start", methods=["POST"])
@require_role("driver")
def start_trip(booking_id: str):
    """Driver starts trip, logs start_odometer and checklist -> IN_PROGRESS."""
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

    if b.get("status") != "CONFIRMED":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot start trip with booking in status '{b.get('status')}'; must be CONFIRMED",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    start_odo = data.get("start_odometer")
    checklist = data.get("checklist")

    if start_odo is not None:
        try:
            start_odo = float(start_odo)
            if start_odo < 0:
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "start_odometer must be a non-negative number",
                    "alternatives": [],
                }
            }), 400

    try:
        updated = transition(
            booking_id,
            "IN_PROGRESS",
            g.current_user,
            note="Trip started by driver",
            extra_data={"start_odometer": start_odo, "checklist": checklist},
        )
        trip = get_trip_by_booking_id(booking_id)

        return jsonify({
            "booking": serialize_booking(updated),
            "trip": trip,
            "status": "IN_PROGRESS",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400


@trips_bp.route("/<booking_id>/end", methods=["POST"])
@require_role("driver")
def end_trip(booking_id: str):
    """Driver ends trip, logs end_odometer and fuel_added -> COMPLETED."""
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

    if b.get("status") != "IN_PROGRESS":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot end trip with booking in status '{b.get('status')}'; must be IN_PROGRESS",
                "alternatives": [],
            }
        }), 400

    data = request.get_json(silent=True) or {}
    end_odo = data.get("end_odometer")
    fuel = data.get("fuel_added")

    if end_odo is not None:
        try:
            end_odo = float(end_odo)
            if end_odo < 0:
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "end_odometer must be a non-negative number",
                    "alternatives": [],
                }
            }), 400

        # Validate against start odometer
        existing_trip = get_trip_by_booking_id(booking_id)
        if existing_trip and existing_trip.get("start_odometer") is not None:
            st_odo = float(existing_trip["start_odometer"])
            if end_odo < st_odo:
                return jsonify({
                    "error": {
                        "code": "BAD_REQUEST",
                        "message": f"end_odometer ({end_odo}) cannot be less than start_odometer ({st_odo})",
                        "alternatives": [],
                    }
                }), 400

    if fuel is not None:
        try:
            fuel = float(fuel)
            if fuel < 0:
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "fuel_added must be a non-negative number",
                    "alternatives": [],
                }
            }), 400

    try:
        updated = transition(
            booking_id,
            "COMPLETED",
            g.current_user,
            note="Trip completed by driver",
            extra_data={"end_odometer": end_odo, "fuel_added": fuel},
        )
        trip = get_trip_by_booking_id(booking_id)

        return jsonify({
            "booking": serialize_booking(updated),
            "trip": trip,
            "status": "COMPLETED",
        }), 200
    except (IllegalTransitionError, ForbiddenTransitionError) as exc:
        return jsonify({
            "error": {
                "code": "TRANSITION_FAILED",
                "message": str(exc),
                "alternatives": [],
            }
        }), 400
