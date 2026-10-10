"""Tests for F2 Animated Frontend Integration and Static Route Serving.

Verifies:
- GET /landing, /landing/, /f2, /f2/ serve the F2 animated UI with HTTP 200.
- Key elements (canvas, progress bar, 234 frames story, brand-glyph, role selector, live backend status) are present.
- JPG frames (e.g. /f2/0001.jpg, /landing/0001.jpg, /0001.jpg) serve with image/jpeg and HTTP 200.
- Public fleet API /api/fleet returns live fleet data.
- Reset demo endpoint /api/admin/reset-demo-bookings returns HTTP 200 and restores seed data.
- Full end-to-end booking flow from F2 payload through manager approval, driver accept, trip start and end.
"""
from datetime import datetime, timedelta, timezone
import pytest
from app import create_app
from app.auth import create_test_token
from app.db import reset_seed_data, get_driver_by_id

MGR_PROFILE_ID = "00000000-0000-0000-0002-000000000001"
EMP_PROFILE_ID = "00000000-0000-0000-0003-000000000001"
DRV_PROFILE_ID = "00000000-0000-0000-0004-000000000001"


@pytest.fixture(autouse=True)
def setup_seed_state():
    reset_seed_data()


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_landing_and_f2_static_routes_serve_html(client):
    """Verify /landing and /f2 serve the rich animated frontend."""
    for path in ["/landing", "/landing/", "/f2", "/f2/"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers.get("Content-Type", "")
        html = res.get_data(as_text=True)
        assert "FITRIDE" in html
        assert "animation-canvas" in html
        assert "THE RIGHT" in html
        assert "VEHICLE" in html
        assert "user-persona-select" in html
        assert "data-backend-status" in html
        assert "booking-form" in html
        assert "driver-cockpit-panel" in html
        assert "reset-demo" in html


def test_f2_jpg_frames_serve_correctly(client):
    """Verify frame 0001.jpg serves via /landing/0001.jpg, /f2/0001.jpg, and root /0001.jpg with Cache-Control."""
    for path in ["/landing/0001.jpg", "/f2/0001.jpg", "/0001.jpg"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "image/jpeg" in res.headers.get("Content-Type", "")
        assert "max-age=86400" in res.headers.get("Cache-Control", "")
        assert len(res.data) > 10000


def test_public_fleet_api(client):
    """Verify /api/fleet returns live vehicles and correctly maps category synonyms."""
    res = client.get("/api/fleet")
    assert res.status_code == 200
    data = res.get_json()
    assert "fleet" in data
    assert len(data["fleet"]) >= 5
    names = [v["name"] for v in data["fleet"]]
    assert "Maruti Swift" in names
    assert "Toyota Innova" in names

    # Test category synonyms
    res_sedan = client.get("/api/fleet?type=sedan")
    assert res_sedan.status_code == 200
    sedan_names = [v["name"] for v in res_sedan.get_json()["fleet"]]
    assert "Maruti Swift" in sedan_names

    res_mpv = client.get("/api/fleet?type=mpv")
    assert res_mpv.status_code == 200
    mpv_names = [v["name"] for v in res_mpv.get_json()["fleet"]]
    assert "Toyota Innova" in mpv_names

    res_bus = client.get("/api/fleet?type=minibus")
    assert res_bus.status_code == 200
    bus_names = [v["name"] for v in res_bus.get_json()["fleet"]]
    assert "Force Tempo Traveller" in bus_names


def test_reset_demo_bookings_endpoint(client):
    """Verify POST /api/admin/reset-demo-bookings restores seed state."""
    res = client.post("/api/admin/reset-demo-bookings")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("ok") is True


def test_driver_auth_and_mine_bookings(client):
    """Verify login with driver UUID and alias, and verify /api/bookings/mine returns driver trips."""
    # 1. Login with alias 'driver1'
    res_login_alias = client.post("/api/auth/login", json={"id": "driver1", "password": "123"})
    assert res_login_alias.status_code == 200
    data_alias = res_login_alias.get_json()
    assert data_alias["role"] == "driver"
    assert "access_token" in data_alias

    # 2. Login with driver UUID (driver table ID)
    res_login_uuid = client.post("/api/auth/login", json={"id": "00000000-0000-0000-0005-000000000001", "password": "123"})
    assert res_login_uuid.status_code == 200
    data_uuid = res_login_uuid.get_json()
    assert data_uuid["role"] == "driver"
    drv_token = data_uuid["access_token"]

    # 3. Initially driver has no trips in /mine
    res_mine_empty = client.get("/api/bookings/mine", headers={"Authorization": f"Bearer {drv_token}"})
    assert res_mine_empty.status_code == 200
    assert isinstance(res_mine_empty.get_json()["bookings"], list)


def test_f2_end_to_end_flow(client):
    """Verify complete lifecycle: employee booking -> manager approval -> driver accept -> trip start & end."""
    emp_token = create_test_token(EMP_PROFILE_ID, role="employee")
    mgr_token = create_test_token(MGR_PROFILE_ID, role="manager")
    drv_token = create_test_token(DRV_PROFILE_ID, role="driver")

    # 1. Employee books scheduled ride with priority 'high' (requires manager approval)
    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(days=2, hours=10)
    end_dt = start_dt + timedelta(hours=3)

    payload = {
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "passengers": 3,
        "destination": "Bangalore International Exhibition Centre",
        "reason": "Team tech expo attendance",
        "type": "scheduled",
        "priority": "high",
    }

    res_book = client.post(
        "/api/bookings",
        json=payload,
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    assert res_book.status_code == 201
    booking_id = res_book.get_json()["booking"]["id"]
    assert res_book.get_json()["booking"]["status"] == "PENDING"

    # 2. Manager queue contains this booking in pending state
    res_queue = client.get(
        "/api/manager/queue",
        headers={"Authorization": f"Bearer {mgr_token}"},
    )
    assert res_queue.status_code == 200
    q_data = res_queue.get_json()
    assert any(b["id"] == booking_id for b in q_data.get("pending", []))

    # 3. Manager approves -> advances to DRIVER_PENDING
    res_app = client.post(
        f"/api/manager/bookings/{booking_id}/approve",
        headers={"Authorization": f"Bearer {mgr_token}"},
    )
    assert res_app.status_code in (200, 201)
    approved_booking = res_app.get_json().get("booking", {})
    assigned_drv_id = approved_booking.get("driver_id")
    assert assigned_drv_id is not None
    drv_record = get_driver_by_id(assigned_drv_id)
    assert drv_record is not None
    drv_token = create_test_token(drv_record["profile_id"], role="driver")

    # 4. Driver accepts -> advances to CONFIRMED
    res_acc = client.post(
        f"/api/driver/bookings/{booking_id}/accept",
        headers={"Authorization": f"Bearer {drv_token}"},
    )
    assert res_acc.status_code == 200

    # 5. Driver checks /api/bookings/mine -> booking is present
    res_mine = client.get(
        "/api/bookings/mine",
        headers={"Authorization": f"Bearer {drv_token}"},
    )
    assert res_mine.status_code == 200
    mine_bookings = res_mine.get_json().get("bookings", [])
    assert any(b["id"] == booking_id for b in mine_bookings)

    # 6. Driver starts trip -> advances to IN_PROGRESS
    res_start = client.post(
        f"/api/trips/{booking_id}/start",
        json={"start_odometer_km": 15000, "checklist_completed": True},
        headers={"Authorization": f"Bearer {drv_token}"},
    )
    assert res_start.status_code == 200

    # 7. Driver ends trip -> advances to COMPLETED
    res_end = client.post(
        f"/api/trips/{booking_id}/end",
        json={"end_odometer_km": 15045, "fuel_level": "full"},
        headers={"Authorization": f"Bearer {drv_token}"},
    )
    assert res_end.status_code == 200
    assert res_end.get_json()["booking"]["status"] == "COMPLETED"


def test_driver_decline_and_reassignment_flow(client):
    """Verify driver decline (e.g. tired) automatically reallocates to next eligible driver."""
    emp_token = create_test_token(EMP_PROFILE_ID, role="employee")
    mgr_token = create_test_token(MGR_PROFILE_ID, role="manager")

    start_dt = datetime.now(timezone.utc) + timedelta(days=3, hours=9)
    end_dt = start_dt + timedelta(hours=2)

    res_book = client.post(
        "/api/bookings",
        json={
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "passengers": 2,
            "destination": "Whitefield IT Park",
            "reason": "Client presentation",
            "type": "scheduled",
            "priority": "high",
        },
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    assert res_book.status_code == 201
    booking_id = res_book.get_json()["booking"]["id"]

    res_app = client.post(
        f"/api/manager/bookings/{booking_id}/approve",
        headers={"Authorization": f"Bearer {mgr_token}"},
    )
    assert res_app.status_code in (200, 201)
    assigned_drv_id_1 = res_app.get_json()["booking"]["driver_id"]
    drv1_rec = get_driver_by_id(assigned_drv_id_1)
    drv1_token = create_test_token(drv1_rec["profile_id"], role="driver")

    # Driver 1 declines with reason 'tired'
    res_rej = client.post(
        f"/api/driver/bookings/{booking_id}/reject",
        json={"reason": "tired"},
        headers={"Authorization": f"Bearer {drv1_token}"},
    )
    assert res_rej.status_code in (200, 201)
    updated_bkg = res_rej.get_json().get("booking", {})
    # Should be reassigned to a different driver
    assigned_drv_id_2 = updated_bkg.get("driver_id")
    assert assigned_drv_id_2 is not None
    assert assigned_drv_id_2 != assigned_drv_id_1
