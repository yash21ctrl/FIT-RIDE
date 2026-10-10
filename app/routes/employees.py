"""Employee management routes for managers (Team KNIGHT | PS 40)."""
import uuid
from flask import Blueprint, jsonify, request
from app.auth import require_role
from app.db import get_all_profiles, create_profile, get_profile_by_id, get_profile_by_email

employees_bp = Blueprint("employees", __name__, url_prefix="/api/employees")


@employees_bp.route("", methods=["GET"])
@require_role("manager")
def list_employees():
    """List all registered employee profiles (Manager only)."""
    profiles = get_all_profiles()
    employees = [p for p in profiles if p.get("role") == "employee"]
    return jsonify({"employees": employees, "count": len(employees)}), 200


@employees_bp.route("", methods=["POST"])
@require_role("manager")
def add_employee():
    """Register a new employee profile (Manager only)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a JSON object",
                "alternatives": [],
            }
        }), 400

    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Employee name is required",
                "alternatives": [],
            }
        }), 400

    custom_id = str(data.get("id") or "").strip() or str(uuid.uuid4())
    email = str(data.get("email", "")).strip() or f"{custom_id}@fleetride.local"
    phone = str(data.get("phone", "")).strip() or None

    if get_profile_by_id(custom_id):
        return jsonify({
            "error": {
                "code": "CONFLICT",
                "message": f"Profile with ID '{custom_id}' already exists",
                "alternatives": [],
            }
        }), 409

    if get_profile_by_email(email):
        return jsonify({
            "error": {
                "code": "CONFLICT",
                "message": f"Profile with email '{email}' already exists",
                "alternatives": [],
            }
        }), 409

    profile_data = {
        "id": custom_id,
        "name": name,
        "role": "employee",
        "email": email,
        "phone": phone,
    }

    created = create_profile(profile_data)
    return jsonify({
        "employee": created,
        "message": f"Employee '{name}' registered successfully! They can log in with ID '{custom_id}' and password '123'.",
    }), 201
