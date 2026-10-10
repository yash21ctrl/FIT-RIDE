"""Auth routes: /api/me and /api/auth/login."""
from flask import Blueprint, jsonify, request, g

from app.auth import require_auth, create_test_token
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
    Supports email lookup or direct profile_id for local/testing convenience.
    """
    data = request.get_json(silent=True) or {}
    profile_id = data.get("profile_id")
    email = data.get("email")

    profile = None
    if profile_id:
        profile = get_profile_by_id(str(profile_id))
    elif email:
        profile = get_profile_by_email(str(email))

    if not profile:
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid credentials or user not found",
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

    token = create_test_token(profile["id"], role=profile["role"])
    return jsonify({
        "access_token": token,
        "token_type": "bearer",
        "role": profile["role"],
        "driver_id": driver_id,
        "user": profile,
        "profile": profile,
    }), 200
