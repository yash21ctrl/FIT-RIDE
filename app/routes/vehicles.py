"""Vehicle management endpoints (Team KNIGHT | PS 40)."""
from datetime import datetime
from typing import Any, Optional
from flask import Blueprint, jsonify, request

from app.auth import require_role
from app.db import (
    get_all_vehicles,
    get_vehicle_by_id,
    create_vehicle,
    update_vehicle,
)

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/api/vehicles")


def _is_valid_iso_datetime(val: Any) -> bool:
    """Validate that val is a parseable ISO 8601 timestamp string or datetime object."""
    if val is None:
        return True
    if isinstance(val, datetime):
        return True
    if not isinstance(val, str) or not val.strip():
        return False
    s = val.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


@vehicles_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "vehicles", "status": "pong"})


@vehicles_bp.route("", methods=["GET"])
@require_role("manager")
def list_vehicles():
    """List fleet vehicles with statuses, capacities, and maintenance (Manager only)."""
    vehicles = get_all_vehicles()
    
    # Optional query filters
    status_filter = request.args.get("status")
    if status_filter:
        vehicles = [v for v in vehicles if v.get("status") == status_filter]
        
    type_filter = request.args.get("type")
    if type_filter:
        vehicles = [v for v in vehicles if v.get("type") == type_filter]

    min_capacity = request.args.get("min_capacity")
    if min_capacity and min_capacity.isdigit():
        vehicles = [v for v in vehicles if int(v.get("capacity", 0)) >= int(min_capacity)]

    return jsonify({"vehicles": vehicles}), 200


@vehicles_bp.route("/<vehicle_id>", methods=["GET"])
@require_role("manager")
def get_vehicle(vehicle_id: str):
    """Get single fleet vehicle by ID (Manager only)."""
    vehicle = get_vehicle_by_id(vehicle_id)
    if not vehicle:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Vehicle not found with ID {vehicle_id}",
                "alternatives": [],
            }
        }), 404
    return jsonify({"vehicle": vehicle}), 200


@vehicles_bp.route("", methods=["POST"])
@require_role("manager")
def add_vehicle():
    """Add a new vehicle to the fleet (Manager only)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a JSON object",
                "alternatives": [],
            }
        }), 400

    name = data.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Vehicle name is required and cannot be empty",
                "alternatives": [],
            }
        }), 400

    veh_type = data.get("type")
    if not veh_type or not isinstance(veh_type, str) or not veh_type.strip():
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Vehicle type is required and cannot be empty",
                "alternatives": [],
            }
        }), 400

    capacity = data.get("capacity")
    if capacity is None or isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Capacity must be an integer greater than 0",
                "alternatives": [],
            }
        }), 400

    status = data.get("status", "available")
    if status not in ("available", "maintenance", "retired"):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Invalid vehicle status '{status}'. Must be 'available', 'maintenance', or 'retired'",
                "alternatives": [],
            }
        }), 400

    if "maintenance_until" in data and data["maintenance_until"] is not None:
        if not _is_valid_iso_datetime(data["maintenance_until"]):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Invalid maintenance_until format; must be an ISO 8601 datetime string",
                    "alternatives": [],
                }
            }), 400

    if "odometer_km" in data:
        odo = data["odometer_km"]
        if isinstance(odo, bool) or not isinstance(odo, (int, float)) or odo < 0:
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Odometer must be a non-negative number",
                    "alternatives": [],
                }
            }), 400

    created = create_vehicle(data)
    return jsonify({"vehicle": created}), 201


@vehicles_bp.route("/<vehicle_id>", methods=["PATCH"])
@require_role("manager")
def patch_vehicle(vehicle_id: str):
    """Update vehicle status, capacity, or maintenance window (Manager only)."""
    existing = get_vehicle_by_id(vehicle_id)
    if not existing:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Vehicle not found with ID {vehicle_id}",
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

    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Vehicle name cannot be empty",
                    "alternatives": [],
                }
            }), 400

    if "type" in data:
        veh_type = data["type"]
        if not isinstance(veh_type, str) or not veh_type.strip():
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Vehicle type cannot be empty",
                    "alternatives": [],
                }
            }), 400

    if "status" in data:
        status = data["status"]
        if status not in ("available", "maintenance", "retired"):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": f"Invalid vehicle status '{status}'. Must be 'available', 'maintenance', or 'retired'",
                    "alternatives": [],
                }
            }), 400

    if "capacity" in data:
        capacity = data["capacity"]
        if capacity is None or isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Capacity must be an integer greater than 0",
                    "alternatives": [],
                }
            }), 400

    if "maintenance_until" in data and data["maintenance_until"] is not None:
        if not _is_valid_iso_datetime(data["maintenance_until"]):
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Invalid maintenance_until format; must be an ISO 8601 datetime string or null",
                    "alternatives": [],
                }
            }), 400

    if "odometer_km" in data:
        odo = data["odometer_km"]
        if isinstance(odo, bool) or not isinstance(odo, (int, float)) or odo < 0:
            return jsonify({
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Odometer must be a non-negative number",
                    "alternatives": [],
                }
            }), 400

    updated = update_vehicle(vehicle_id, data)
    return jsonify({"vehicle": updated}), 200


@vehicles_bp.route("/<vehicle_id>", methods=["DELETE"])
@require_role("manager")
def delete_vehicle(vehicle_id: str):
    """Retire vehicle from active fleet (Manager only)."""
    existing = get_vehicle_by_id(vehicle_id)
    if not existing:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Vehicle not found with ID {vehicle_id}",
                "alternatives": [],
            }
        }), 404

    updated = update_vehicle(vehicle_id, {"status": "retired"})
    return jsonify({"vehicle": updated, "message": "Vehicle status set to retired"}), 200
