"""Tests for Flask app authentication, role enforcement, and error formatting (Team KNIGHT | PS 40)."""
import uuid
import pytest
from flask import g

from app import create_app
from app.auth import create_test_token, get_jwt_secret
from app.db import reset_seed_data, register_test_profile, ExclusionViolationError


# Canonical seed IDs from migrations/003_seed.sql
MGR_1_ID = "00000000-0000-0000-0002-000000000001"  # Yashwanth M (manager)
MGR_2_ID = "00000000-0000-0000-0002-000000000002"  # Kavana (manager)
EMP_1_ID = "00000000-0000-0000-0003-000000000001"  # Ananya Roy (employee)
EMP_2_ID = "00000000-0000-0000-0003-000000000002"  # Vikram Das (employee)
DRV_1_PROFILE_ID = "00000000-0000-0000-0004-000000000001"  # Ravi Kumar (driver profile)
DRV_1_ID = "00000000-0000-0000-0005-000000000001"  # Ravi Kumar (driver record)
VEH_1_ID = "00000000-0000-0000-0001-000000000001"  # Maruti Swift


@pytest.fixture(autouse=True)
def setup_seed_state():
    """Reset in-memory database to canonical seed state before every test."""
    reset_seed_data()


@pytest.fixture
def client():
    """Create Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def auth_header(token: str) -> dict:
    """Format Authorization Bearer header."""
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# 1. Unauthenticated requests return 401 with standard error format
# --------------------------------------------------------------------------

def test_unauthenticated_requests_return_401_standard_error(client):
    """
    Prove that any unauthenticated or malformed request to protected endpoints
    returns HTTP 401 with standardized error format:
    { "error": { "code": "UNAUTHORIZED", "message": "...", "alternatives": [] } }
    """
    endpoints = [
        ("GET", "/api/me", None),
        ("GET", "/api/vehicles", None),
        ("POST", "/api/vehicles", {"name": "Test Car", "type": "car", "capacity": 4}),
        ("PATCH", f"/api/vehicles/{VEH_1_ID}", {"status": "maintenance"}),
        ("GET", "/api/drivers", None),
        ("POST", "/api/drivers", {"profile_id": EMP_2_ID}),
        ("PATCH", f"/api/drivers/{DRV_1_ID}", {"status": "break"}),
    ]

    for method, path, json_data in endpoints:
        # A. Missing Authorization header completely
        res = client.open(path, method=method, json=json_data)
        assert res.status_code == 401, f"{method} {path} should be 401, got {res.status_code}"
        data = res.get_json()
        assert "error" in data
        assert data["error"]["code"] == "UNAUTHORIZED"
        assert isinstance(data["error"]["message"], str)
        assert data["error"]["alternatives"] == []

        # B. Non-Bearer header
        res_bad_header = client.open(
            path,
            method=method,
            json=json_data,
            headers={"Authorization": "Basic user:pass"},
        )
        assert res_bad_header.status_code == 401
        assert res_bad_header.get_json()["error"]["code"] == "UNAUTHORIZED"

        # C. Empty Bearer token
        res_empty = client.open(
            path,
            method=method,
            json=json_data,
            headers={"Authorization": "Bearer "},
        )
        assert res_empty.status_code == 401
        assert res_empty.get_json()["error"]["code"] == "UNAUTHORIZED"

        # D. Invalid signature / token string
        res_invalid = client.open(
            path,
            method=method,
            json=json_data,
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert res_invalid.status_code == 401
        assert res_invalid.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_token_returns_401_standard_error(client):
    """Prove that an expired token returns HTTP 401 UNAUTHORIZED."""
    expired_token = create_test_token(EMP_1_ID, expires_in=-100)
    res = client.get("/api/me", headers=auth_header(expired_token))
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "expired" in data["error"]["message"].lower()
    assert data["error"]["alternatives"] == []


# --------------------------------------------------------------------------
# 2. Employee gets 403 on manager routes
# --------------------------------------------------------------------------

def test_employee_gets_403_on_manager_routes(client):
    """
    Prove that an authenticated employee gets HTTP 403 FORBIDDEN when calling
    manager routes (POST /api/vehicles, PATCH /api/drivers/<id>, etc.).
    """
    emp_token = create_test_token(EMP_1_ID)
    headers = auth_header(emp_token)

    manager_endpoints = [
        ("GET", "/api/vehicles", None),
        ("POST", "/api/vehicles", {"name": "Illegal Car", "type": "car", "capacity": 4}),
        ("PATCH", f"/api/vehicles/{VEH_1_ID}", {"status": "maintenance"}),
        ("GET", "/api/drivers", None),
        ("POST", "/api/drivers", {"profile_id": EMP_2_ID}),
        ("PATCH", f"/api/drivers/{DRV_1_ID}", {"status": "break"}),
    ]

    for method, path, json_data in manager_endpoints:
        res = client.open(path, method=method, json=json_data, headers=headers)
        assert res.status_code == 403, f"Expected 403 for employee on {method} {path}, got {res.status_code}"
        data = res.get_json()
        assert "error" in data
        assert data["error"]["code"] == "FORBIDDEN"
        assert "employee" in data["error"]["message"]
        assert data["error"]["alternatives"] == []


# --------------------------------------------------------------------------
# 3. Driver gets 403 on manager routes
# --------------------------------------------------------------------------

def test_driver_gets_403_on_manager_routes(client):
    """
    Prove that an authenticated driver gets HTTP 403 FORBIDDEN on manager routes.
    """
    drv_token = create_test_token(DRV_1_PROFILE_ID)
    headers = auth_header(drv_token)

    manager_endpoints = [
        ("GET", "/api/vehicles", None),
        ("POST", "/api/vehicles", {"name": "Driver Car", "type": "car", "capacity": 4}),
        ("PATCH", f"/api/vehicles/{VEH_1_ID}", {"status": "maintenance"}),
        ("GET", "/api/drivers", None),
        ("POST", "/api/drivers", {"profile_id": EMP_2_ID}),
        ("PATCH", f"/api/drivers/{DRV_1_ID}", {"status": "off"}),
    ]

    for method, path, json_data in manager_endpoints:
        res = client.open(path, method=method, json=json_data, headers=headers)
        assert res.status_code == 403, f"Expected 403 for driver on {method} {path}, got {res.status_code}"
        data = res.get_json()
        assert "error" in data
        assert data["error"]["code"] == "FORBIDDEN"
        assert "driver" in data["error"]["message"]
        assert data["error"]["alternatives"] == []


# --------------------------------------------------------------------------
# 4. Never trust role claim passed in token / client headers
# --------------------------------------------------------------------------

def test_server_loads_role_from_database_and_ignores_forged_claim(client):
    """
    CRITICAL SECURITY TEST:
    A user crafts a token with claim role='manager', but the user's profile in
    the database has role='employee'.
    Prove the server ignores the forged token claim, loads 'employee' from the database,
    and returns 403 FORBIDDEN on manager routes.
    """
    # Forge a token claiming role='manager' for Ananya Roy (employee in database)
    forged_token = create_test_token(EMP_1_ID, role="manager")
    headers = auth_header(forged_token)

    # Calling GET /api/me should show verified role 'employee', NOT forged 'manager'
    res_me = client.get("/api/me", headers=headers)
    assert res_me.status_code == 200
    assert res_me.get_json()["role"] == "employee"

    # Calling manager route POST /api/vehicles should be strictly rejected with 403
    res_post = client.post(
        "/api/vehicles",
        json={"name": "Hacked Vehicle", "type": "car", "capacity": 4},
        headers=headers,
    )
    assert res_post.status_code == 403
    assert res_post.get_json()["error"]["code"] == "FORBIDDEN"
    assert "employee" in res_post.get_json()["error"]["message"]


# --------------------------------------------------------------------------
# 5. Manager access succeeds (200/201) on vehicle and driver CRUD
# --------------------------------------------------------------------------

def test_manager_access_succeeds_on_vehicle_crud(client):
    """
    Prove manager access succeeds on vehicles CRUD:
    - GET /api/vehicles -> 200
    - POST /api/vehicles -> 201
    - PATCH /api/vehicles/<id> -> 200
    """
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # 1. GET /api/vehicles
    res_list = client.get("/api/vehicles", headers=headers)
    assert res_list.status_code == 200
    vehicles = res_list.get_json()["vehicles"]
    assert len(vehicles) >= 6
    names = [v["name"] for v in vehicles]
    assert "Maruti Swift" in names
    assert "Force Tempo Traveller" in names

    # 2. POST /api/vehicles
    new_veh_data = {
        "name": "Tata Safari",
        "type": "van",
        "capacity": 7,
        "status": "available",
        "odometer_km": 1500,
    }
    res_create = client.post("/api/vehicles", json=new_veh_data, headers=headers)
    assert res_create.status_code == 201
    created_veh = res_create.get_json()["vehicle"]
    assert created_veh["name"] == "Tata Safari"
    assert created_veh["capacity"] == 7
    assert created_veh["type"] == "van"
    created_id = created_veh["id"]

    # 3. PATCH /api/vehicles/<id>
    update_data = {
        "status": "maintenance",
        "maintenance_until": "2026-10-31T18:00:00Z",
        "capacity": 8,
    }
    res_patch = client.patch(f"/api/vehicles/{created_id}", json=update_data, headers=headers)
    assert res_patch.status_code == 200
    patched_veh = res_patch.get_json()["vehicle"]
    assert patched_veh["status"] == "maintenance"
    assert patched_veh["capacity"] == 8
    assert patched_veh["maintenance_until"] == "2026-10-31T18:00:00Z"


def test_manager_access_succeeds_on_driver_crud(client):
    """
    Prove manager access succeeds on drivers CRUD:
    - GET /api/drivers -> 200
    - POST /api/drivers -> 201
    - PATCH /api/drivers/<id> -> 200
    """
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # 1. GET /api/drivers
    res_list = client.get("/api/drivers", headers=headers)
    assert res_list.status_code == 200
    drivers = res_list.get_json()["drivers"]
    assert len(drivers) >= 5
    driver_names = [d["name"] for d in drivers]
    assert "Ravi Kumar" in driver_names

    # 2. POST /api/drivers (link new driver to an existing employee profile)
    new_driver_data = {
        "profile_id": EMP_2_ID,
        "license_no": "DL-KA-05-2026-999",
        "status": "available",
        "rating_avg": 5.0,
    }
    res_create = client.post("/api/drivers", json=new_driver_data, headers=headers)
    assert res_create.status_code == 201
    created_drv = res_create.get_json()["driver"]
    assert created_drv["profile_id"] == EMP_2_ID
    assert created_drv["license_no"] == "DL-KA-05-2026-999"
    created_driver_id = created_drv["id"]

    # 3. PATCH /api/drivers/<id>
    update_data = {
        "status": "break",
        "license_no": "DL-KA-05-2026-888",
    }
    res_patch = client.patch(f"/api/drivers/{created_driver_id}", json=update_data, headers=headers)
    assert res_patch.status_code == 200
    patched_drv = res_patch.get_json()["driver"]
    assert patched_drv["status"] == "break"
    assert patched_drv["license_no"] == "DL-KA-05-2026-888"


# --------------------------------------------------------------------------
# 6. GET /api/me returns correct profile and role for each seed role
# --------------------------------------------------------------------------

def test_get_me_returns_profile_and_role_for_all_seed_roles(client):
    """
    Prove GET /api/me returns the correct profile and role for:
    - Manager: Yashwanth M, role 'manager'
    - Employee: Ananya Roy, role 'employee'
    - Driver: Ravi Kumar, role 'driver'
    """
    # Manager
    mgr_token = create_test_token(MGR_1_ID)
    res_mgr = client.get("/api/me", headers=auth_header(mgr_token))
    assert res_mgr.status_code == 200
    mgr_data = res_mgr.get_json()
    assert mgr_data["id"] == MGR_1_ID
    assert mgr_data["name"] == "Yashwanth M"
    assert mgr_data["role"] == "manager"
    assert mgr_data["phone"] == "+919876543210"

    # Employee
    emp_token = create_test_token(EMP_1_ID)
    res_emp = client.get("/api/me", headers=auth_header(emp_token))
    assert res_emp.status_code == 200
    emp_data = res_emp.get_json()
    assert emp_data["id"] == EMP_1_ID
    assert emp_data["name"] == "Ananya Roy"
    assert emp_data["role"] == "employee"
    assert emp_data["phone"] == "+919876543220"

    # Driver
    drv_token = create_test_token(DRV_1_PROFILE_ID)
    res_drv = client.get("/api/me", headers=auth_header(drv_token))
    assert res_drv.status_code == 200
    drv_data = res_drv.get_json()
    assert drv_data["id"] == DRV_1_PROFILE_ID
    assert drv_data["name"] == "Ravi Kumar"
    assert drv_data["role"] == "driver"
    assert drv_data["driver_id"] == DRV_1_ID


# --------------------------------------------------------------------------
# 7. Postgres error code 23P01 formats as { "code": "VEHICLE_TAKEN" }
# --------------------------------------------------------------------------

def test_postgres_error_23p01_formats_as_vehicle_taken(client):
    """
    Prove PostgreSQL GiST exclusion violation (error code 23P01)
    is caught by the global error handler and returned as:
    {
      "error": {
        "code": "VEHICLE_TAKEN",
        "message": "That vehicle was just taken.",
        "alternatives": []
      }
    }
    with HTTP status 409 Conflict.
    """
    res = client.get("/api/test/simulate-23p01")
    assert res.status_code == 409
    data = res.get_json()
    assert "error" in data
    assert data["error"]["code"] == "VEHICLE_TAKEN"
    assert data["error"]["message"] == "That vehicle was just taken."
    assert data["error"]["alternatives"] == []


# --------------------------------------------------------------------------
# 8. CRUD validation failures return standard 400 or 404
# --------------------------------------------------------------------------

def test_vehicles_crud_validation(client):
    """Prove invalid vehicle additions or updates return 400 or 404."""
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # Missing name
    res = client.post("/api/vehicles", json={"type": "car", "capacity": 4}, headers=headers)
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"

    # Missing type
    res = client.post("/api/vehicles", json={"name": "No Type", "capacity": 4}, headers=headers)
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"

    # Capacity <= 0
    res = client.post("/api/vehicles", json={"name": "Zero Cap", "type": "car", "capacity": 0}, headers=headers)
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"

    # Invalid status
    res = client.post(
        "/api/vehicles",
        json={"name": "Bad Status", "type": "car", "capacity": 4, "status": "unknown"},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"

    # Non-existent vehicle ID on PATCH
    res = client.patch(
        f"/api/vehicles/{uuid.uuid4()}",
        json={"status": "maintenance"},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "NOT_FOUND"


def test_drivers_crud_validation(client):
    """Prove invalid driver additions or updates return 400 or 404."""
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # Non-existent profile ID on create
    res = client.post(
        "/api/drivers",
        json={"profile_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"

    # Duplicate driver registration for already registered driver
    res_dup = client.post(
        "/api/drivers",
        json={"profile_id": DRV_1_PROFILE_ID},
        headers=headers,
    )
    assert res_dup.status_code == 400
    assert res_dup.get_json()["error"]["code"] == "BAD_REQUEST"

    # Non-existent driver ID on PATCH
    res = client.patch(
        f"/api/drivers/{uuid.uuid4()}",
        json={"status": "break"},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "NOT_FOUND"

    # Invalid status on PATCH
    res = client.patch(
        f"/api/drivers/{DRV_1_ID}",
        json={"status": "sleeping"},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"


# --------------------------------------------------------------------------
# 9. Global 404 handler returns standardized error payload
# --------------------------------------------------------------------------

def test_global_404_handler_standard_format(client):
    """Prove unmapped endpoints return 404 with standardized error payload."""
    res = client.get("/api/some/nonexistent/endpoint")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"]["code"] == "NOT_FOUND"
    assert isinstance(data["error"]["message"], str)
    assert data["error"]["alternatives"] == []


# --------------------------------------------------------------------------
# 10. Login endpoint returns access token and profile
# --------------------------------------------------------------------------

def test_login_endpoint_returns_token_and_role(client):
    """Prove POST /api/auth/login authenticates seed profiles and returns token."""
    res = client.post("/api/auth/login", json={"profile_id": MGR_1_ID})
    assert res.status_code == 200
    data = res.get_json()
    assert "access_token" in data
    assert data["role"] == "manager"
    assert data["user"]["name"] == "Yashwanth M"

    # Invalid credentials
    res_bad = client.post("/api/auth/login", json={"profile_id": str(uuid.uuid4())})
    assert res_bad.status_code == 401
    assert res_bad.get_json()["error"]["code"] == "UNAUTHORIZED"


# --------------------------------------------------------------------------
# 11. Additional Security & Edge Cases
# --------------------------------------------------------------------------

def test_token_with_nonexistent_profile_id_returns_401(client):
    """Prove a validly signed token with a nonexistent profile UUID returns 401."""
    random_id = str(uuid.uuid4())
    token = create_test_token(random_id)
    res = client.get("/api/me", headers=auth_header(token))
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "profile not found" in data["error"]["message"].lower()


def test_token_signed_with_wrong_secret_returns_401(client):
    """Prove a token signed with the wrong HMAC secret returns 401."""
    wrong_token = create_test_token(EMP_1_ID, secret="wrong-secret-that-does-not-match")
    res = client.get("/api/me", headers=auth_header(wrong_token))
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_health_check_unauthenticated(client):
    """Prove /api/health is accessible without authentication."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_cors_preflight_headers(client):
    """Prove CORS OPTIONS preflight response contains standard CORS headers."""
    res = client.open(
        "/api/vehicles",
        method="OPTIONS",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert res.status_code == 200
    assert "Access-Control-Allow-Origin" in res.headers


def test_patch_vehicle_invalid_capacity(client):
    """Prove capacity <= 0 or invalid type on PATCH returns 400 BAD_REQUEST."""
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    res_zero = client.patch(f"/api/vehicles/{VEH_1_ID}", json={"capacity": 0}, headers=headers)
    assert res_zero.status_code == 400
    assert res_zero.get_json()["error"]["code"] == "BAD_REQUEST"

    res_neg = client.patch(f"/api/vehicles/{VEH_1_ID}", json={"capacity": -5}, headers=headers)
    assert res_neg.status_code == 400
    assert res_neg.get_json()["error"]["code"] == "BAD_REQUEST"

    res_str = client.patch(f"/api/vehicles/{VEH_1_ID}", json={"capacity": "ten"}, headers=headers)
    assert res_str.status_code == 400
    assert res_str.get_json()["error"]["code"] == "BAD_REQUEST"


def test_non_json_body_returns_400(client):
    """Prove non-JSON body on POST/PATCH returns 400 BAD_REQUEST."""
    mgr_token = create_test_token(MGR_1_ID)
    headers = {
        "Authorization": f"Bearer {mgr_token}",
        "Content-Type": "text/plain",
    }
    res = client.post("/api/vehicles", data="not json", headers=headers)
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"


def test_bearer_token_case_insensitivity_and_spacing(client):
    """
    Prove Authorization header accepts case-insensitive 'bearer' scheme
    and handles multiple spaces correctly per RFC 6750.
    """
    mgr_token = create_test_token(MGR_1_ID)

    # 1. Lowercase "bearer"
    res_lower = client.get("/api/me", headers={"Authorization": f"bearer {mgr_token}"})
    assert res_lower.status_code == 200
    assert res_lower.get_json()["role"] == "manager"

    # 2. Uppercase "BEARER"
    res_upper = client.get("/api/me", headers={"Authorization": f"BEARER {mgr_token}"})
    assert res_upper.status_code == 200
    assert res_upper.get_json()["role"] == "manager"

    # 3. Multiple spaces between Bearer and token
    res_spaces = client.get("/api/me", headers={"Authorization": f"Bearer    {mgr_token}"})
    assert res_spaces.status_code == 200
    assert res_spaces.get_json()["role"] == "manager"


def test_multi_role_decorator_and_stacked_decorators():
    """
    Prove multi-role decorator (@require_role('employee', 'manager'))
    and stacked decorators (@require_auth and @require_role) work cleanly.
    """
    from flask import Blueprint, jsonify
    from app.auth import require_role, require_auth

    test_app = create_app()
    test_app.config["TESTING"] = True

    # Multi-role route: accessible by both employee and manager
    @test_app.route("/api/test/multi-role", methods=["GET"])
    @require_role("employee", "manager")
    def multi_role_endpoint():
        return jsonify({"allowed": True}), 200

    # Stacked route: require_auth outer, require_role inner
    @test_app.route("/api/test/stacked-auth-role", methods=["GET"])
    @require_auth
    @require_role("manager")
    def stacked_auth_role_endpoint():
        return jsonify({"allowed": True}), 200

    # Stacked route: require_role outer, require_auth inner
    @test_app.route("/api/test/stacked-role-auth", methods=["GET"])
    @require_role("manager")
    @require_auth
    def stacked_role_auth_endpoint():
        return jsonify({"allowed": True}), 200

    with test_app.test_client() as c:
        emp_token = create_test_token(EMP_1_ID)
        mgr_token = create_test_token(MGR_1_ID)
        drv_token = create_test_token(DRV_1_PROFILE_ID)

        # 1. Multi-role endpoint
        # Employee -> 200 OK
        res_emp = c.get("/api/test/multi-role", headers=auth_header(emp_token))
        assert res_emp.status_code == 200
        assert res_emp.get_json()["allowed"] is True

        # Manager -> 200 OK
        res_mgr = c.get("/api/test/multi-role", headers=auth_header(mgr_token))
        assert res_mgr.status_code == 200
        assert res_mgr.get_json()["allowed"] is True

        # Driver -> 403 Forbidden
        res_drv = c.get("/api/test/multi-role", headers=auth_header(drv_token))
        assert res_drv.status_code == 403
        assert res_drv.get_json()["error"]["code"] == "FORBIDDEN"

        # 2. Stacked auth -> role
        res_st1 = c.get("/api/test/stacked-auth-role", headers=auth_header(mgr_token))
        assert res_st1.status_code == 200
        res_st1_fail = c.get("/api/test/stacked-auth-role", headers=auth_header(emp_token))
        assert res_st1_fail.status_code == 403

        # 3. Stacked role -> auth
        res_st2 = c.get("/api/test/stacked-role-auth", headers=auth_header(mgr_token))
        assert res_st2.status_code == 200
        res_st2_fail = c.get("/api/test/stacked-role-auth", headers=auth_header(emp_token))
        assert res_st2_fail.status_code == 403


def test_get_single_vehicle_and_driver_crud(client):
    """
    Prove GET /api/vehicles/<id> and GET /api/drivers/<id>:
    - Manager gets 200 with object details.
    - Employee gets 403.
    - Non-existent ID returns 404.
    """
    mgr_token = create_test_token(MGR_1_ID)
    emp_token = create_test_token(EMP_1_ID)

    # 1. GET /api/vehicles/<id>
    # Manager
    res_veh = client.get(f"/api/vehicles/{VEH_1_ID}", headers=auth_header(mgr_token))
    assert res_veh.status_code == 200
    v_data = res_veh.get_json()["vehicle"]
    assert v_data["id"] == VEH_1_ID
    assert v_data["name"] == "Maruti Swift"

    # Employee -> 403
    res_veh_emp = client.get(f"/api/vehicles/{VEH_1_ID}", headers=auth_header(emp_token))
    assert res_veh_emp.status_code == 403

    # Non-existent -> 404
    res_veh_404 = client.get(f"/api/vehicles/{uuid.uuid4()}", headers=auth_header(mgr_token))
    assert res_veh_404.status_code == 404
    assert res_veh_404.get_json()["error"]["code"] == "NOT_FOUND"

    # 2. GET /api/drivers/<id>
    # Manager
    res_drv = client.get(f"/api/drivers/{DRV_1_ID}", headers=auth_header(mgr_token))
    assert res_drv.status_code == 200
    d_data = res_drv.get_json()["driver"]
    assert d_data["id"] == DRV_1_ID
    assert d_data["name"] == "Ravi Kumar"

    # Employee -> 403
    res_drv_emp = client.get(f"/api/drivers/{DRV_1_ID}", headers=auth_header(emp_token))
    assert res_drv_emp.status_code == 403

    # Non-existent -> 404
    res_drv_404 = client.get(f"/api/drivers/{uuid.uuid4()}", headers=auth_header(mgr_token))
    assert res_drv_404.status_code == 404
    assert res_drv_404.get_json()["error"]["code"] == "NOT_FOUND"


def test_delete_retire_vehicle(client):
    """
    Prove DELETE /api/vehicles/<id> marks vehicle as retired:
    - Manager gets 200 with updated vehicle.
    - Employee gets 403.
    """
    mgr_token = create_test_token(MGR_1_ID)
    emp_token = create_test_token(EMP_1_ID)

    # Employee forbidden
    res_del_emp = client.delete(f"/api/vehicles/{VEH_1_ID}", headers=auth_header(emp_token))
    assert res_del_emp.status_code == 403

    # Manager retires
    res_del_mgr = client.delete(f"/api/vehicles/{VEH_1_ID}", headers=auth_header(mgr_token))
    assert res_del_mgr.status_code == 200
    v_data = res_del_mgr.get_json()["vehicle"]
    assert v_data["status"] == "retired"

    # Subsequent GET verifies status is retired
    res_check = client.get(f"/api/vehicles/{VEH_1_ID}", headers=auth_header(mgr_token))
    assert res_check.status_code == 200
    assert res_check.get_json()["vehicle"]["status"] == "retired"


def test_vehicle_and_driver_advanced_validations(client):
    """
    Prove advanced field validations:
    - Odometer < 0 returns 400.
    - Invalid maintenance_until string returns 400.
    - Empty name or type on PATCH returns 400.
    - Driver rating out of bounds returns 400.
    - Empty PATCH body returns 200 without error.
    """
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # 1. Negative odometer on POST vehicle
    res_neg_odo = client.post(
        "/api/vehicles",
        json={"name": "Bad Odo", "type": "car", "capacity": 4, "odometer_km": -100},
        headers=headers,
    )
    assert res_neg_odo.status_code == 400
    assert res_neg_odo.get_json()["error"]["code"] == "BAD_REQUEST"

    # 2. Invalid maintenance_until on POST vehicle
    res_bad_maint = client.post(
        "/api/vehicles",
        json={"name": "Bad Date", "type": "car", "capacity": 4, "maintenance_until": "not-a-datetime"},
        headers=headers,
    )
    assert res_bad_maint.status_code == 400
    assert res_bad_maint.get_json()["error"]["code"] == "BAD_REQUEST"

    # 3. Empty name on PATCH vehicle
    res_empty_name = client.patch(f"/api/vehicles/{VEH_1_ID}", json={"name": "   "}, headers=headers)
    assert res_empty_name.status_code == 400

    # 4. Driver rating out of range on POST driver
    res_bad_rating = client.post(
        "/api/drivers",
        json={"profile_id": EMP_2_ID, "rating_avg": 7.5},
        headers=headers,
    )
    assert res_bad_rating.status_code == 400

    # 5. Empty PATCH body succeeds and returns existing vehicle
    res_empty_patch = client.patch(f"/api/vehicles/{VEH_1_ID}", json={}, headers=headers)
    assert res_empty_patch.status_code == 200
    assert res_empty_patch.get_json()["vehicle"]["id"] == VEH_1_ID


def test_driver_registration_syncs_profile_role_and_driver_id(client):
    """
    Prove that registering a driver linked to a profile:
    1. Updates the profile's role to 'driver'.
    2. When that user accesses GET /api/me, verified role is 'driver' and driver_id is present.
    3. The login endpoint returns driver_id for that driver.
    """
    mgr_token = create_test_token(MGR_1_ID)

    # Before registration: EMP_2 is an employee
    emp_token_before = create_test_token(EMP_2_ID)
    res_me_before = client.get("/api/me", headers=auth_header(emp_token_before))
    assert res_me_before.status_code == 200
    assert res_me_before.get_json()["role"] == "employee"
    assert res_me_before.get_json()["driver_id"] is None

    # Manager registers EMP_2 as a driver
    res_create = client.post(
        "/api/drivers",
        json={"profile_id": EMP_2_ID, "license_no": "DL-NEW-2026-777", "rating_avg": 4.9},
        headers=auth_header(mgr_token),
    )
    assert res_create.status_code == 201
    created_drv = res_create.get_json()["driver"]
    created_drv_id = created_drv["id"]

    # After registration: EMP_2 token now resolves to role 'driver' with driver_id
    emp_token_after = create_test_token(EMP_2_ID)
    res_me_after = client.get("/api/me", headers=auth_header(emp_token_after))
    assert res_me_after.status_code == 200
    me_data = res_me_after.get_json()
    assert me_data["role"] == "driver"
    assert me_data["driver_id"] == created_drv_id

    # Login endpoint also returns driver_id
    res_login = client.post("/api/auth/login", json={"profile_id": EMP_2_ID})
    assert res_login.status_code == 200
    assert res_login.get_json()["role"] == "driver"
    assert res_login.get_json()["driver_id"] == created_drv_id


def test_query_filters_on_vehicles_and_drivers(client):
    """
    Prove optional query filtering on vehicles and drivers:
    - GET /api/vehicles?status=available
    - GET /api/drivers?status=available
    """
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # Vehicles filter
    res_v = client.get("/api/vehicles?status=available", headers=headers)
    assert res_v.status_code == 200
    vehs = res_v.get_json()["vehicles"]
    assert all(v["status"] == "available" for v in vehs)

    # Drivers filter
    res_d = client.get("/api/drivers?status=available", headers=headers)
    assert res_d.status_code == 200
    drvs = res_d.get_json()["drivers"]
    assert all(d["status"] == "available" for d in drvs)


def test_simplified_id_and_password_login(client):
    """
    Prove that users can log in using simple IDs ('emp1', 'driver1', 'manager1')
    and universal password '123'.
    """
    # 1. Employee login
    res_emp = client.post("/api/auth/login", json={"id": "emp1", "password": "123"})
    assert res_emp.status_code == 200
    assert res_emp.get_json()["role"] == "employee"
    assert res_emp.get_json()["user"]["name"] == "Ananya Roy"

    # 2. Driver login
    res_drv = client.post("/api/auth/login", json={"id": "driver1", "password": "123"})
    assert res_drv.status_code == 200
    assert res_drv.get_json()["role"] == "driver"
    assert res_drv.get_json()["driver_id"] is not None

    # 3. Manager login
    res_mgr = client.post("/api/auth/login", json={"id": "manager1", "password": "123"})
    assert res_mgr.status_code == 200
    assert res_mgr.get_json()["role"] == "manager"

    # 4. Bearer auth works directly with simple ID
    res_me = client.get("/api/me", headers={"Authorization": "Bearer emp1"})
    assert res_me.status_code == 200
    assert res_me.get_json()["role"] == "employee"


def test_manager_can_list_and_add_employees_and_drivers(client):
    """
    Prove manager can list employees, add a new employee, and add a new driver.
    Verify the newly added users can immediately log in with password '123'.
    """
    mgr_token = create_test_token(MGR_1_ID)
    headers = auth_header(mgr_token)

    # 1. List employees
    res_list = client.get("/api/employees", headers=headers)
    assert res_list.status_code == 200
    employees = res_list.get_json()["employees"]
    assert len(employees) >= 5

    # 2. Add new employee 'emp6'
    res_add_emp = client.post(
        "/api/employees",
        json={"name": "Pooja Reddy", "id": "emp6", "phone": "+919876543288"},
        headers=headers,
    )
    assert res_add_emp.status_code == 201
    created_emp = res_add_emp.get_json()["employee"]
    assert created_emp["id"] == "emp6"
    assert created_emp["name"] == "Pooja Reddy"

    # New employee logs in immediately with ID 'emp6' and password '123'
    res_login_emp = client.post("/api/auth/login", json={"id": "emp6", "password": "123"})
    assert res_login_emp.status_code == 200
    assert res_login_emp.get_json()["role"] == "employee"

    # 3. Add new driver 'driver6'
    res_add_drv = client.post(
        "/api/drivers",
        json={
            "name": "Ramesh Kumar",
            "id": "driver6",
            "phone": "+919876543299",
            "license_no": "DL-KA-05-2024-999",
        },
        headers=headers,
    )
    assert res_add_drv.status_code == 201
    created_drv = res_add_drv.get_json()["driver"]
    assert created_drv["status"] == "available"

    # New driver logs in immediately with ID 'driver6' and password '123'
    res_login_drv = client.post("/api/auth/login", json={"id": "driver6", "password": "123"})
    assert res_login_drv.status_code == 200
    assert res_login_drv.get_json()["role"] == "driver"
    assert res_login_drv.get_json()["driver_id"] is not None

