"""Targeted tests for defensive programming enhancements across routes (Team KNIGHT | PS 40)."""
from datetime import datetime, timedelta, timezone
import pytest
from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    create_booking,
    get_booking_by_id,
)
from app.services.transitions import transition

EMP_1_ID = "00000000-0000-0000-0003-000000000001"
MGR_1_ID = "00000000-0000-0000-0002-000000000001"
DRV_1_ID = "00000000-0000-0000-0005-000000000001"
DRV_1_PROFILE_ID = "00000000-0000-0000-0004-000000000001"
VEH_1_ID = "00000000-0000-0000-0001-000000000001"


@pytest.fixture(autouse=True)
def clean_state():
    reset_seed_data()
    yield
    reset_seed_data()


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth_headers(profile_id: str, role: str) -> dict:
    token = create_test_token(profile_id, role)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_booking_dest_lat_lng_range_validation(client):
    """Ensure dest_lat and dest_lng are strictly range-validated and reject invalid values."""
    headers = _auth_headers(EMP_1_ID, "employee")
    start_dt = (datetime.now(timezone.utc) + timedelta(days=2, hours=10)).isoformat()
    end_dt = (datetime.now(timezone.utc) + timedelta(days=2, hours=12)).isoformat()

    base_payload = {
        "passengers": 2,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Bangalore Airport",
        "reason": "Flight boarding",
        "type": "scheduled",
    }

    # 1. Invalid lat > 90
    bad_payload = dict(base_payload, dest_lat=91.5, dest_lng=77.5)
    resp = client.post("/api/bookings", headers=headers, json=bad_payload)
    assert resp.status_code == 400
    assert "dest_lat" in resp.get_json()["error"]["message"]

    # 2. Invalid lat < -90
    bad_payload = dict(base_payload, dest_lat=-91.5, dest_lng=77.5)
    resp = client.post("/api/bookings", headers=headers, json=bad_payload)
    assert resp.status_code == 400
    assert "dest_lat" in resp.get_json()["error"]["message"]

    # 3. Invalid lng > 180
    bad_payload = dict(base_payload, dest_lat=12.9, dest_lng=181.0)
    resp = client.post("/api/bookings", headers=headers, json=bad_payload)
    assert resp.status_code == 400
    assert "dest_lng" in resp.get_json()["error"]["message"]

    # 4. Invalid lng < -180
    bad_payload = dict(base_payload, dest_lat=12.9, dest_lng=-181.0)
    resp = client.post("/api/bookings", headers=headers, json=bad_payload)
    assert resp.status_code == 400
    assert "dest_lng" in resp.get_json()["error"]["message"]

    # 5. Boolean lat rejected
    bad_payload = dict(base_payload, dest_lat=True, dest_lng=77.5)
    resp = client.post("/api/bookings", headers=headers, json=bad_payload)
    assert resp.status_code == 400

    # 6. Non-numeric string rejected
    bad_payload = dict(base_payload, dest_lat="not_a_float", dest_lng=77.5)
    resp = client.post("/api/bookings", headers=headers, json=bad_payload)
    assert resp.status_code == 400

    # 7. Valid lat and lng accepted
    good_payload = dict(base_payload, dest_lat=12.9716, dest_lng=77.5946)
    resp = client.post("/api/bookings", headers=headers, json=good_payload)
    assert resp.status_code in (201, 200)


def test_post_location_defensive_coordinate_parsing(client):
    """Ensure malformed locations in batch GPS ingestion are skipped without 500 error."""
    # Create active trip in IN_PROGRESS status
    start_dt = datetime.now(timezone.utc) - timedelta(hours=1)
    end_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 1,
        "destination": "Client Office",
        "status": "CONFIRMED",
    })
    drv_user = {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID}
    transition(b["id"], "IN_PROGRESS", actor=drv_user)

    headers = _auth_headers(DRV_1_PROFILE_ID, "driver")

    # Send mix of valid and malformed location entries
    payload = {
        "locations": [
            {"lat": "not_a_number", "lng": 77.5},  # Malformed string
            {"lat": True, "lng": 77.5},            # Boolean
            {"lat": 120.0, "lng": 77.5},           # Out of range latitude
            {"lat": 12.9716, "lng": 77.5946},      # Valid!
            "not_a_dict",                           # Non-dict item
        ]
    }
    resp = client.post(f"/api/trips/{b['id']}/location", headers=headers, json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["saved_count"] == 1
    assert data["locations"][0]["lat"] == 12.9716
    assert data["locations"][0]["lng"] == 77.5946


def test_ratings_boolean_guard(client):
    """Ensure booleans for ratings are rejected with 400 Bad Request."""
    start_dt = datetime.now(timezone.utc) - timedelta(hours=2)
    end_dt = datetime.now(timezone.utc) - timedelta(hours=1)
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 1,
        "destination": "Client Office",
        "status": "CONFIRMED",
    })
    drv_user = {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID}
    transition(b["id"], "IN_PROGRESS", actor=drv_user)
    transition(b["id"], "COMPLETED", actor=drv_user)

    emp_headers = _auth_headers(EMP_1_ID, "employee")

    # 1. /api/trips/<bid>/rate with boolean
    resp = client.post(
        f"/api/trips/{b['id']}/rate",
        headers=emp_headers,
        json={"driver_rating": True, "vehicle_rating": 5},
    )
    assert resp.status_code == 400

    # 2. /api/ratings with boolean
    resp = client.post(
        "/api/ratings",
        headers=emp_headers,
        json={"booking_id": b["id"], "driver_rating": 5, "vehicle_rating": True},
    )
    assert resp.status_code == 400


def test_employee_duplicate_prevention(client):
    """Ensure registering an employee with duplicate ID or email returns 409 Conflict."""
    mgr_headers = _auth_headers(MGR_1_ID, "manager")

    # 1. Duplicate ID
    resp = client.post(
        "/api/employees",
        headers=mgr_headers,
        json={"id": EMP_1_ID, "name": "Duplicate Employee", "email": "unique1@fleetride.local"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "CONFLICT"

    # 2. Duplicate Email
    resp = client.post(
        "/api/employees",
        headers=mgr_headers,
        json={"id": "new-unique-id-999", "name": "Duplicate Email", "email": "emp1@fleetride.local"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "CONFLICT"


def test_admin_trip_merge_defensive_inputs(client):
    """Ensure trip merge check handles invalid coordinate types without 500 error."""
    headers = _auth_headers(MGR_1_ID, "manager")
    start_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    # 1. dest_lat is boolean
    resp = client.post(
        "/api/admin/trip-merge-check",
        headers=headers,
        json={"dest_lat": True, "dest_lng": 77.5, "start_time": start_dt},
    )
    assert resp.status_code == 400

    # 2. dest_lat is invalid string
    resp = client.post(
        "/api/admin/trip-merge-check",
        headers=headers,
        json={"dest_lat": "bad", "dest_lng": 77.5, "start_time": start_dt},
    )
    assert resp.status_code == 400

    # 3. passengers and merge_radius_km are malformed strings -> handled gracefully
    resp = client.post(
        "/api/admin/trip-merge-check",
        headers=headers,
        json={
            "dest_lat": 12.9716,
            "dest_lng": 77.5946,
            "start_time": start_dt,
            "passengers": "not_an_int",
            "merge_radius_km": "not_a_float",
        },
    )
    assert resp.status_code == 200
    assert "mergeable" in resp.get_json()

    # 4. Out of bounds lat/lng returns 400
    resp = client.post(
        "/api/admin/trip-merge-check",
        headers=headers,
        json={"dest_lat": 95.0, "dest_lng": 77.5, "start_time": start_dt},
    )
    assert resp.status_code == 400
    assert "between -90 and 90" in resp.get_json()["message"]


def test_add_driver_defensive_validation(client):
    """Ensure driver registration guards against boolean rating and duplicate credentials."""
    headers = _auth_headers(MGR_1_ID, "manager")

    # 1. Reject boolean rating
    resp = client.post(
        "/api/drivers",
        headers=headers,
        json={"name": "New Driver", "rating_avg": True},
    )
    assert resp.status_code == 400
    assert "Rating must be a number between 1.0 and 5.0" in resp.get_json()["error"]["message"]

    # 2. Duplicate profile ID conflict
    resp = client.post(
        "/api/drivers",
        headers=headers,
        json={"id": DRV_1_PROFILE_ID, "name": "Existing Driver ID"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "CONFLICT"

    # 3. Duplicate profile email conflict
    resp = client.post(
        "/api/drivers",
        headers=headers,
        json={"name": "Dup Email Driver", "email": "driver1@fleetride.local"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "CONFLICT"


def test_add_vehicle_duplicate_id_prevention(client):
    """Ensure adding vehicle with existing ID returns 409 Conflict."""
    headers = _auth_headers(MGR_1_ID, "manager")

    resp = client.post(
        "/api/vehicles",
        headers=headers,
        json={"id": VEH_1_ID, "name": "Duplicate Car", "type": "car", "capacity": 4},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "CONFLICT"


def test_trips_boolean_odometer_and_limit_guards(client):
    """Ensure trip start/end reject boolean odometers and location endpoint handles invalid limits."""
    # Create and advance booking to CONFIRMED
    start_dt = datetime.now(timezone.utc) - timedelta(hours=1)
    end_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 1,
        "destination": "Client Office",
        "status": "CONFIRMED",
    })
    drv_headers = _auth_headers(DRV_1_PROFILE_ID, "driver")

    # 1. start_odometer as boolean -> 400
    resp = client.post(
        f"/api/trips/{b['id']}/start",
        headers=drv_headers,
        json={"start_odometer": True},
    )
    assert resp.status_code == 400
    assert "start_odometer must be a non-negative number" in resp.get_json()["error"]["message"]

    # 2. Valid start
    resp = client.post(
        f"/api/trips/{b['id']}/start",
        headers=drv_headers,
        json={"start_odometer": 1000.0},
    )
    assert resp.status_code == 200

    # 3. end_odometer as boolean -> 400
    resp = client.post(
        f"/api/trips/{b['id']}/end",
        headers=drv_headers,
        json={"end_odometer": True},
    )
    assert resp.status_code == 400

    # 4. fuel_added as boolean -> 400
    resp = client.post(
        f"/api/trips/{b['id']}/end",
        headers=drv_headers,
        json={"end_odometer": 1020.0, "fuel_added": True},
    )
    assert resp.status_code == 400

    # 5. /api/trips/<bid>/location with invalid limit string and negative limit
    resp = client.get(
        f"/api/trips/{b['id']}/location?limit=invalid_param",
        headers=drv_headers,
    )
    assert resp.status_code == 200
    assert "trail" in resp.get_json()

    resp = client.get(
        f"/api/trips/{b['id']}/location?limit=-10",
        headers=drv_headers,
    )
    assert resp.status_code == 200
    assert "trail" in resp.get_json()

