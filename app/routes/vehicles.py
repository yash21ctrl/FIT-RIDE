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

    # Reallocation logic when vehicle enters maintenance or is retired
    new_status = data.get("status")
    has_maintenance = (new_status == "maintenance") or ("maintenance_until" in data and data["maintenance_until"] is not None)
    
    realloc_summary = None
    if has_maintenance or new_status == "retired":
        from flask import g
        realloc_summary = reallocate_vehicle_maintenance(vehicle_id, manager_actor=getattr(g, "current_user", None))
    elif existing.get("status") == "maintenance" and new_status == "available":
        # Vehicle became available again: trigger waitlist auto-promotion
        from app.engine.waitlist import promote_waitlisted
        promote_waitlisted()

    resp = {"vehicle": updated}
    if realloc_summary:
        resp["reallocation"] = realloc_summary
    return jsonify(resp), 200


def reallocate_vehicle_maintenance(vehicle_id: str, manager_actor=None):
    """
    Find upcoming slot-holding bookings on maintenance/retired vehicle and either
    reallocate to an alternative vehicle or transition to WAITLISTED.
    """
    from app.db import query_bookings, get_vehicle_by_id, update_booking, add_decision_log, create_notification, _to_utc_dt
    from app.engine.allocate import allocate, BookingRequest
    from app.services.transitions import transition, MANAGER_PROFILE_IDS

    veh = get_vehicle_by_id(vehicle_id)
    veh_name = veh.get("name", "Vehicle") if veh else "Vehicle"

    assigned_bookings = query_bookings(active_only=False, vehicle_id=vehicle_id)
    affected = [
        b for b in assigned_bookings
        if b.get("status") in ("PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED")
    ]

    reallocated_count = 0
    waitlisted_count = 0

    for b in affected:
        req = BookingRequest(
            start=_to_utc_dt(b["start_time"]),
            end=_to_utc_dt(b["end_time"]),
            passengers=int(b.get("passengers", 1)),
            type=b.get("type", "scheduled"),
            priority=b.get("priority", "normal"),
            destination=b.get("destination", ""),
            employee_id=b.get("employee_id"),
            reason=b.get("reason", ""),
        )
        res = allocate(req, exclude_booking_id=b["id"], exclude_vehicle_ids=(vehicle_id,))
        if res.ok and res.options:
            top = res.options[0]
            update_booking(
                b["id"],
                {
                    "vehicle_id": top.vehicle_id,
                    "driver_id": top.driver_id,
                    "decision_reason": f"Reallocated from {veh_name} (in maintenance) to {top.vehicle_name or top.vehicle_id}: {top.reason}",
                }
            )
            actor_id = manager_actor.get("id") if isinstance(manager_actor, dict) else "system"
            add_decision_log(
                b["id"],
                actor_id=actor_id if actor_id != "system" else None,
                action="vehicle_maintenance_reallocated",
                note=f"Reassigned from vehicle {veh_name} to {top.vehicle_name or top.vehicle_id}",
            )
            emp_id = b.get("employee_id")
            if emp_id:
                create_notification(
                    emp_id,
                    f"Your booking {b['id'][:8]} was reassigned to vehicle {top.vehicle_name or top.vehicle_id} due to maintenance on {veh_name}.",
                    booking_id=b["id"],
                )
            reallocated_count += 1
        else:
            transition(
                booking_id=b["id"],
                new_status="WAITLISTED",
                actor=manager_actor or {"id": "system", "role": "manager"},
                note=f"Vehicle {veh_name} entered maintenance; no replacement vehicle available",
                extra_data={
                    "vehicle_id": None,
                    "driver_id": None,
                    "failure_reason": "VEHICLES_IN_MAINTENANCE",
                    "decision_reason": f"Moved to waitlist: vehicle {veh_name} entered maintenance and all alternatives are busy",
                }
            )
            for m_id in MANAGER_PROFILE_IDS:
                create_notification(
                    m_id,
                    f"Booking {b['id'][:8]} moved to waitlist: vehicle {veh_name} entered maintenance with no alternatives.",
                    booking_id=b["id"],
                )
            waitlisted_count += 1

    return {"reallocated": reallocated_count, "waitlisted": waitlisted_count}


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
    from flask import g
    realloc_summary = reallocate_vehicle_maintenance(vehicle_id, manager_actor=getattr(g, "current_user", None))
    return jsonify({
        "vehicle": updated,
        "message": "Vehicle status set to retired",
        "reallocation": realloc_summary,
    }), 200
