"""Driver management endpoints (Team KNIGHT | PS 40)."""
from typing import Any
from flask import Blueprint, jsonify, request

from app.auth import require_role
from app.db import (
    get_all_drivers,
    get_driver_by_id,
    get_driver_by_profile_id,
    get_profile_by_id,
    create_driver,
    update_driver,
)

drivers_bp = Blueprint("drivers", __name__, url_prefix="/api/drivers")


@drivers_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "drivers", "status": "pong"})


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
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Profile ID is required and cannot be empty",
                "alternatives": [],
            }
        }), 400

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

    created = create_driver(data)
    return jsonify({"driver": created}), 201


@drivers_bp.route("/<driver_id>", methods=["PATCH"])
@require_role("manager")
def patch_driver(driver_id: str):
    """Update driver status, license, or rating (Manager only)."""
    existing = get_driver_by_id(driver_id)
    if not existing:
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
