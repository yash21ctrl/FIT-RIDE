"""Auth routes: /api/me and /api/auth/login."""
from flask import Blueprint, jsonify, request, g

from app.auth import require_auth, create_test_token, resolve_profile_from_identifier
from app.db import get_profile_by_id, get_profile_by_email

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


@auth_bp.route("/me", methods=["GET"])
@require_auth
def get_me():
    """Return the profile and verified role of the authenticated user."""
    user = g.current_user
    return jsonify({
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "phone": user.get("phone"),
        "telegram_chat_id": user.get("telegram_chat_id"),
        "email": user.get("email"),
        "driver_id": user.get("driver_id"),
        "profile": user,
        "user": user,
    }), 200


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    """
    Authenticate a user and return an access token, profile, and role.
    Supports simple ID (emp1, driver1, manager1), email, or UUID, and password '123'.
    """
    data = request.get_json(silent=True) or {}
    identifier = (
        data.get("id")
        or data.get("username")
        or data.get("email")
        or data.get("profile_id")
        or data.get("driver_id")
    )
    password = str(data.get("password") or "").strip()

    if not identifier:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "User ID, username, or email is required",
                "alternatives": [],
            }
        }), 400

    profile = resolve_profile_from_identifier(str(identifier))
    if not profile:
        profile = get_profile_by_id(str(identifier)) or get_profile_by_email(str(identifier))

    if not profile:
        from app.db import get_driver_by_id
        drv = get_driver_by_id(str(identifier))
        if drv and drv.get("profile_id"):
            profile = get_profile_by_id(drv["profile_id"])

    if not profile:
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": f"User '{identifier}' not found. Use ID (e.g. emp1, driver1, manager1)",
                "alternatives": [],
            }
        }), 401

    driver_id = None
    if profile.get("role") == "driver":
        from app.db import get_driver_by_profile_id
        drv = get_driver_by_profile_id(profile["id"])
        if drv:
            driver_id = drv.get("id")
            profile["driver_id"] = driver_id

    # Token can be used directly as Bearer token
    token = create_test_token(profile["id"], role=profile["role"])
    return jsonify({
        "access_token": token,
        "token": profile["id"],
        "user_id": profile["id"],
        "token_type": "bearer",
        "role": profile["role"],
        "driver_id": driver_id,
        "user": profile,
        "profile": profile,
    }), 200
