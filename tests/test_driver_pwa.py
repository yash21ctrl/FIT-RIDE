"""Unit and integration tests for Driver PWA (Phase 6)."""
import json
import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    create_booking,
    get_booking_by_id,
    get_driver_by_profile_id
)

DRIVER_1_PROFILE_ID = "00000000-0000-0000-0004-000000000001"
DRIVER_1_ID = "00000000-0000-0000-0005-000000000001"
EMP_1_PROFILE_ID = "00000000-0000-0000-0003-000000000001"
VEHICLE_1_ID = "00000000-0000-0000-0001-000000000001"


@pytest.fixture
def app():
    reset_seed_data()
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_driver_pwa_static_routes(client):
    """Test that driver index, manifest, service worker, and app script serve correctly."""
    # 1. Driver Index
    res_index = client.get("/driver")
    assert res_index.status_code in (200, 308)
    if res_index.status_code == 308:
        res_index = client.get("/driver/")
    assert res_index.status_code == 200
    assert "FleetRide Driver PWA" in res_index.get_data(as_text=True)

    # 2. Manifest
    res_manifest = client.get("/driver/manifest.json")
    assert res_manifest.status_code == 200
    manifest = json.loads(res_manifest.get_data(as_text=True))
    assert manifest["short_name"] == "Driver"
    assert manifest["display"] == "standalone"

    # 3. Service Worker
    res_sw = client.get("/driver/sw.js")
    assert res_sw.status_code == 200
    assert "fleetride-driver" in res_sw.get_data(as_text=True)

    # 4. App.js
    res_js = client.get("/driver/app.js")
    assert res_js.status_code == 200
    assert "quickLoginDriver" in res_js.get_data(as_text=True)


def test_driver_requests_and_accept_flow(client):
    """Test driver receiving a request, accepting it, and starting the trip."""
    token = create_test_token(profile_id=DRIVER_1_PROFILE_ID, role="driver")
    headers = {"Authorization": f"Bearer {token}"}

    # Create a booking in DRIVER_PENDING for Driver 1
    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(hours=2)
    end_dt = start_dt + timedelta(hours=2)
    blocked_dt = end_dt + timedelta(minutes=15)
    respond_by = now + timedelta(minutes=30)

    booking = create_booking({
        "employee_id": EMP_1_PROFILE_ID,
        "vehicle_id": VEHICLE_1_ID,
        "driver_id": DRIVER_1_ID,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "blocked_until": blocked_dt.isoformat(),
        "destination": "Koramangala Hub",
        "passengers": 3,
        "reason": "Client Delivery",
        "type": "scheduled",
        "priority": "normal",
        "status": "DRIVER_PENDING",
        "respond_by": respond_by.isoformat()
    })

    # 1. Driver queries requests
    res_reqs = client.get("/api/driver/requests", headers=headers)
    assert res_reqs.status_code == 200
    req_data = res_reqs.get_json()
    assert "requests" in req_data
    assert any(r["id"] == booking["id"] for r in req_data["requests"])

    # 2. Driver accepts request
    res_accept = client.post(f"/api/driver/bookings/{booking['id']}/accept", headers=headers)
    assert res_accept.status_code == 200
    b_updated = get_booking_by_id(booking["id"])
    assert b_updated["status"] == "CONFIRMED"

    # 3. Driver starts trip with checklist
    res_start = client.post(f"/api/trips/{booking['id']}/start", headers=headers, json={
        "start_odometer": 12500,
        "checklist": {"tires": True, "fuel": True, "mirrors": True, "clean": True}
    })
    assert res_start.status_code == 200
    b_started = get_booking_by_id(booking["id"])
    assert b_started["status"] == "IN_PROGRESS"

    # 4. Driver ends trip
    res_end = client.post(f"/api/trips/{booking['id']}/end", headers=headers, json={
        "end_odometer": 12535,
        "fuel_added": 5.0
    })
    assert res_end.status_code == 200
    b_ended = get_booking_by_id(booking["id"])
    assert b_ended["status"] == "COMPLETED"


def test_driver_reject_with_mandatory_reason_reassigns(client):
    """Test driver rejecting with reason tired, recording in driver_responses."""
    token = create_test_token(profile_id=DRIVER_1_PROFILE_ID, role="driver")
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(hours=3)
    end_dt = start_dt + timedelta(hours=2)

    booking = create_booking({
        "employee_id": EMP_1_PROFILE_ID,
        "vehicle_id": VEHICLE_1_ID,
        "driver_id": DRIVER_1_ID,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "blocked_until": (end_dt + timedelta(minutes=15)).isoformat(),
        "destination": "Electronic City",
        "passengers": 2,
        "reason": "Quarterly Review",
        "type": "scheduled",
        "priority": "normal",
        "status": "DRIVER_PENDING",
        "respond_by": (now + timedelta(minutes=30)).isoformat()
    })

    # Reject without reason -> 400
    res_bad = client.post(f"/api/driver/bookings/{booking['id']}/reject", headers=headers, json={})
    assert res_bad.status_code == 400

    # Reject with valid reason -> 200
    res_ok = client.post(f"/api/driver/bookings/{booking['id']}/reject", headers=headers, json={
        "reject_reason": "tired"
    })
    assert res_ok.status_code == 200
    b_after = get_booking_by_id(booking["id"])
    assert b_after["status"] in ("PENDING", "DRIVER_PENDING")
    assert b_after["driver_id"] != DRIVER_1_ID
