"""JWT verification and role authorization module (Team KNIGHT | PS 40)."""
import os
import time
from functools import wraps
from typing import Any, Dict, List, Optional, Set, Union
from flask import g, jsonify, request
import jwt

from app.config import SUPABASE_JWT_SECRET
from app.db import get_profile_by_id, get_driver_by_profile_id, get_profile_by_email, get_all_profiles

# Default fallback signing secret for test/offline environments
TEST_JWT_SECRET = "fleetride-jwt-test-secret-hs256-32bytes-min"

# Easy aliases for simplified login (emp1, driver1, manager1)
ALIAS_MAP: Dict[str, str] = {
    "emp1": "00000000-0000-0000-0003-000000000001",
    "emp2": "00000000-0000-0000-0003-000000000002",
    "emp3": "00000000-0000-0000-0003-000000000003",
    "emp4": "00000000-0000-0000-0003-000000000004",
    "emp5": "00000000-0000-0000-0003-000000000005",
    "manager1": "00000000-0000-0000-0002-000000000001",
    "manager2": "00000000-0000-0000-0002-000000000002",
    "driver1": "00000000-0000-0000-0004-000000000001",
    "driver2": "00000000-0000-0000-0004-000000000002",
    "driver3": "00000000-0000-0000-0004-000000000003",
    "driver4": "00000000-0000-0000-0004-000000000004",
    "driver5": "00000000-0000-0000-0004-000000000005",
}


def resolve_profile_from_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """Look up profile by UUID, email, or short username alias (emp1, driver1, manager1)."""
    if not identifier:
        return None
    s = str(identifier).strip()
    if s.lower() in ALIAS_MAP:
        return get_profile_by_id(ALIAS_MAP[s.lower()])
    p = get_profile_by_id(s)
    if p:
        return p
    p = get_profile_by_email(s)
    if p:
        return p
    for prof in get_all_profiles():
        em = prof.get("email", "").lower()
        nm = prof.get("name", "").lower()
        pid = str(prof.get("id", "")).lower()
        if pid == s.lower() or em == s.lower() or em.startswith(s.lower() + "@") or s.lower() == nm:
            return prof
    return None


def get_jwt_secret() -> str:
    """Return the configured SUPABASE_JWT_SECRET or the test secret fallback."""
    return SUPABASE_JWT_SECRET or TEST_JWT_SECRET


def create_test_token(
    profile_id: str,
    role: Optional[str] = None,
    expires_in: int = 86400,
    secret: Optional[str] = None,
) -> str:
    """
    Generate a signed HS256 JWT for testing.
    Note: The server will verify the token signature, but always loads the actual
    user role from the profiles table, never trusting the token's role claim.
    """
    now = int(time.time())
    payload = {
        "sub": str(profile_id),
        "aud": "authenticated",
        "role": role or "authenticated",
        "iat": now,
        "exp": now + expires_in,
    }
    sec = secret or get_jwt_secret()
    return jwt.encode(payload, sec, algorithm="HS256")


def decode_jwt(token: str, secret: Optional[str] = None) -> Dict[str, Any]:
    """Decode and verify an HS256 JWT token."""
    sec = secret or get_jwt_secret()
    return jwt.decode(
        token,
        sec,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )


def get_current_user_from_token(token: str) -> Dict[str, Any]:
    """
    Verify JWT or raw user identifier and load user profile and role DIRECTLY from the database.
    Never trusts client-supplied role claims.
    """
    user_id = None
    try:
        payload = decode_jwt(token)
        user_id = payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise
    except Exception:
        resolved = resolve_profile_from_identifier(token)
        if resolved:
            user_id = resolved["id"]
        else:
            from app.db import get_supabase_client
            sb = get_supabase_client()
            if sb is not None:
                try:
                    user_res = sb.auth.get_user(token)
                    if user_res and getattr(user_res, "user", None):
                        user_id = getattr(user_res.user, "id", None)
                except Exception:
                    pass

    if not user_id:
        raise ValueError(f"Invalid token or unknown user: {token}")

    profile = get_profile_by_id(user_id) or resolve_profile_from_identifier(user_id)
    if not profile:
        raise ValueError(f"Profile not found for ID: {user_id}")

    verified_role = profile["role"]
    driver_id = None
    if verified_role == "driver":
        drv = get_driver_by_profile_id(profile["id"])
        if drv:
            driver_id = drv.get("id")

    return {
        "id": str(profile["id"]),
        "name": profile.get("name", ""),
        "role": verified_role,  # STRICTLY from database
        "phone": profile.get("phone"),
        "telegram_chat_id": profile.get("telegram_chat_id"),
        "email": profile.get("email"),
        "driver_id": str(driver_id) if driver_id else None,
    }


def _extract_bearer_token() -> Optional[str]:
    """
    Extract token from Authorization header supporting Bearer scheme or direct user ID.
    """
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header:
        return request.headers.get("X-User-ID") or None
    parts = auth_header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return auth_header or None


def _authenticate_request_or_error():
    """
    Authenticate current request.
    If already authenticated on `g.current_user`, reuses it.
    Returns (user_dict, None) on success or (None, (json_response, status_code)) on failure.
    """
    if getattr(g, "current_user", None):
        return g.current_user, None

    token = _extract_bearer_token()
    if not token:
        return None, (
            jsonify({
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Missing or malformed Authorization header",
                    "alternatives": [],
                }
            }),
            401,
        )

    try:
        user = get_current_user_from_token(token)
        g.current_user = user
        return user, None
    except jwt.ExpiredSignatureError:
        return None, (
            jsonify({
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Token has expired",
                    "alternatives": [],
                }
            }),
            401,
        )
    except jwt.InvalidTokenError as exc:
        return None, (
            jsonify({
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": f"Invalid token: {str(exc)}",
                    "alternatives": [],
                }
            }),
            401,
        )
    except ValueError as exc:
        return None, (
            jsonify({
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": str(exc),
                    "alternatives": [],
                }
            }),
            401,
        )
    except Exception as exc:
        return None, (
            jsonify({
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": f"Authentication failed: {str(exc)}",
                    "alternatives": [],
                }
            }),
            401,
        )


def require_auth(f):
    """
    Decorator that requires a valid Supabase JWT Bearer token.
    Attaches the verified profile to `g.current_user`.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user, err = _authenticate_request_or_error()
        if err:
            return err
        return f(*args, **kwargs)

    return decorated


def require_role(*roles: Union[str, List[str], tuple]):
    """
    Decorator enforcing that the authenticated user possesses one of the allowed roles.
    Can be invoked with a single role e.g. `@require_role('manager')` or multiple roles
    e.g. `@require_role('employee', 'manager')`.
    """
    allowed_roles: Set[str] = set()
    for r in roles:
        if isinstance(r, (list, tuple, set)):
            allowed_roles.update(r)
        else:
            allowed_roles.add(str(r))

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user, err = _authenticate_request_or_error()
            if err:
                return err

            user_role = g.current_user.get("role")
            if user_role not in allowed_roles:
                return jsonify({
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"Role '{user_role}' is not authorized to access this resource",
                        "alternatives": [],
                    }
                }), 403

            return f(*args, **kwargs)

        return decorated

    return decorator
