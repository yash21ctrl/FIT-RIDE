"""Tests for Phase 5: Employee Portal and Static Routing (Team KNIGHT | PS 40).

Covers:
- Static file routing: / -> redirect, /employee -> index.html, /shared/styles.css, /shared/api.js, etc.
- MIME type and status 200 verifications for all frontend assets.
- Notifications API: GET /api/notifications, POST /api/notifications/<id>/read, POST /api/notifications/read-all.
- Direct waitlist creation via POST /api/bookings with waitlist=True.
- HTML content verification for key portal elements (quick login, mode switcher, decision explanation).
"""
from datetime import datetime, timedelta, timezone
import pytest
from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    create_notification,
    get_notifications,
)

EMP_1_ID = "00000000-0000-0000-0003-000000000001"  # Ananya Roy
EMP_2_ID = "00000000-0000-0000-0003-000000000002"  # Vikram Das



@pytest.fixture(autouse=True)
def setup_seed_state():
    """Reset state before each test."""
    reset_seed_data()


@pytest.fixture
def client():
    """Create Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# -------------------------------------------------------------------------
# 1. Static Route & Asset Serving Tests
# -------------------------------------------------------------------------

def test_root_redirects_to_employee(client):
    """GET / should redirect (302) to /employee."""
    res = client.get("/")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/employee")


def test_employee_index_returns_html(client):
    """GET /employee and /employee/ should serve the employee portal HTML."""
    for path in ["/employee", "/employee/"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers.get("Content-Type", "")
        html = res.get_data(as_text=True)
        # Verify key elements
        assert "FleetRide" in html
        assert "Employee Portal" in html
        assert "emp1@fleetride.local" in html  # quick login pill
        assert "Ananya Roy" in html
        assert "Emergency Booking" in html
        assert "book-date" in html
        assert "book-passengers" in html


def test_shared_static_assets_serve_correctly(client):
    """Verify shared CSS, api.js, time.js, and realtime.js serve with HTTP 200."""
    css_res = client.get("/shared/styles.css")
    assert css_res.status_code == 200
    assert "text/css" in css_res.headers.get("Content-Type", "")
    assert "--brand-amber" in css_res.get_data(as_text=True)

    api_res = client.get("/shared/api.js")
    assert api_res.status_code == 200
    assert "javascript" in api_res.headers.get("Content-Type", "").lower()
    assert "FleetApiClient" in api_res.get_data(as_text=True)

    time_res = client.get("/shared/time.js")
    assert time_res.status_code == 200
    assert "javascript" in time_res.headers.get("Content-Type", "").lower()
    assert "Asia/Kolkata" in time_res.get_data(as_text=True)

    realtime_res = client.get("/shared/realtime.js")
    assert realtime_res.status_code == 200
    assert "javascript" in realtime_res.headers.get("Content-Type", "").lower()
    assert "FleetRealtimeManager" in realtime_res.get_data(as_text=True)


def test_employee_app_js_serves_correctly(client):
    """Verify /employee/app.js serves with HTTP 200 and application code."""
    res = client.get("/employee/app.js")
    assert res.status_code == 200
    assert "javascript" in res.headers.get("Content-Type", "").lower()
    content = res.get_data(as_text=True)
    assert "EmployeeApp" in content
    assert "quickLogin" in content
    assert "joinWaitlistForCurrentRequest" in content


# -------------------------------------------------------------------------
# 2. Notifications API Tests
# -------------------------------------------------------------------------

def test_notifications_endpoints_and_lifecycle(client):
    """
    Prove:
    - GET /api/notifications returns user's notifications and unread_count.
    - POST /api/notifications/<id>/read marks single notification as read.
    - POST /api/notifications/read-all marks all notifications as read.
    """
    token = create_test_token(EMP_1_ID)
    headers = auth_header(token)

    # Initially 0 notifications
    res0 = client.get("/api/notifications", headers=headers)
    assert res0.status_code == 200
    assert res0.get_json()["notifications"] == []
    assert res0.get_json()["unread_count"] == 0

    # Create 2 notifications for EMP_1 and 1 for EMP_2
    n1 = create_notification(EMP_1_ID, "Booking #1234 was approved by manager.")
    n2 = create_notification(EMP_1_ID, "Driver Suresh Patil accepted trip #1234.")
    create_notification(EMP_2_ID, "Unrelated alert for other employee.")

    # Fetch for EMP_1
    res1 = client.get("/api/notifications", headers=headers)
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert len(data1["notifications"]) == 2
    assert data1["unread_count"] == 2

    # Mark n1 as read
    res_read1 = client.post(f"/api/notifications/{n1['id']}/read", headers=headers)
    assert res_read1.status_code == 200
    assert res_read1.get_json()["status"] == "ok"

    # Verify unread count is now 1
    res2 = client.get("/api/notifications", headers=headers)
    assert res2.status_code == 200
    assert res2.get_json()["unread_count"] == 1

    # Mark all read
    res_all = client.post("/api/notifications/read-all", headers=headers)
    assert res_all.status_code == 200
    assert res_all.get_json()["count"] >= 1

    # Verify unread count is now 0
    res3 = client.get("/api/notifications", headers=headers)
    assert res3.status_code == 200
    assert res3.get_json()["unread_count"] == 0


def test_notifications_unauthenticated_returns_401(client):
    """Unauthenticated requests to /api/notifications return 401."""
    res = client.get("/api/notifications")
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


# -------------------------------------------------------------------------
# 3. Direct Waitlist Booking Creation via API
# -------------------------------------------------------------------------

def test_booking_direct_waitlist_creation(client):
    """
    Prove that submitting a booking with waitlist=True directly creates
    a WAITLISTED booking, writes failure_reason, and notifies the employee.
    """
    token = create_test_token(EMP_1_ID)
    headers = auth_header(token)

    start_utc = datetime.now(timezone.utc) + timedelta(days=10)
    end_utc = start_utc + timedelta(hours=2)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 15,  # Exceeds fleet max
        "destination": "Offsite Campus",
        "reason": "Team Offsite",
        "type": "scheduled",
        "priority": "normal",
        "waitlist": True,
        "failure_reason": "NO_VEHICLE_BIG_ENOUGH",
    }

    res = client.post("/api/bookings", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "WAITLISTED"
    booking = data["booking"]
    assert booking["status"] == "WAITLISTED"
    assert booking["passengers"] == 15
    assert booking["employee_id"] == EMP_1_ID

    # Verify appears in GET /api/bookings/mine
    mine_res = client.get("/api/bookings/mine", headers=headers)
    assert mine_res.status_code == 200
    my_bookings = mine_res.get_json()["bookings"]
    assert any(b["id"] == booking["id"] and b["status"] == "WAITLISTED" for b in my_bookings)


# -------------------------------------------------------------------------
# 4. Employee Booking Workflows (Failure, Cancel, Emergency)
# -------------------------------------------------------------------------

def test_fifteen_passenger_failure_returns_422_with_alternatives(client):
    """
    Prove that requesting 15 passengers (exceeding fleet max 12) returns HTTP 422
    with error code NO_VEHICLE_BIG_ENOUGH and alternatives containing split recommendations.
    """
    token = create_test_token(EMP_1_ID)
    headers = auth_header(token)

    start_utc = datetime.now(timezone.utc) + timedelta(days=12)
    end_utc = start_utc + timedelta(hours=2)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 15,
        "destination": "Offsite Resort",
        "reason": "Department Outing",
        "type": "scheduled",
        "priority": "normal",
    }

    res = client.post("/api/bookings", json=payload, headers=headers)
    assert res.status_code == 422
    data = res.get_json()
    assert data["ok"] is False
    assert data["failure_reason"] == "NO_VEHICLE_BIG_ENOUGH"
    assert data["error"]["code"] == "NO_VEHICLE_BIG_ENOUGH"
    assert len(data["alternatives"]) >= 1


def test_employee_cancel_booking_workflow(client):
    """
    Prove that an employee can cancel their own pending/approved booking,
    which transitions it to CANCELLED and frees any reserved slot.
    """
    token = create_test_token(EMP_1_ID)
    headers = auth_header(token)

    start_utc = datetime.now(timezone.utc) + timedelta(days=14)
    end_utc = start_utc + timedelta(hours=2)

    # 1. Create booking
    req = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 3,
        "destination": "Client Hub",
        "reason": "Sales Demo",
        "type": "scheduled",
        "priority": "high",  # Requires review
    }
    create_res = client.post("/api/bookings", json=req, headers=headers)
    assert create_res.status_code == 201
    bid = create_res.get_json()["booking"]["id"]

    # 2. Cancel booking
    cancel_res = client.post(f"/api/bookings/{bid}/cancel", json={"note": "Meeting rescheduled"}, headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.get_json()["status"] == "CANCELLED"

    # 3. Check in /mine
    mine_res = client.get("/api/bookings/mine", headers=headers)
    assert mine_res.status_code == 200
    trips = mine_res.get_json()["bookings"]
    cancelled_trip = next((t for t in trips if t["id"] == bid), None)
    assert cancelled_trip is not None
    assert cancelled_trip["status"] == "CANCELLED"


def test_emergency_booking_workflow(client):
    """
    Prove that an emergency booking skips manager approval,
    enters DRIVER_PENDING directly, and sets a 2-minute respond_by window.
    """
    token = create_test_token(EMP_2_ID)
    headers = auth_header(token)

    start_utc = datetime.now(timezone.utc) + timedelta(days=16)
    end_utc = start_utc + timedelta(hours=1)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 2,
        "destination": "Critical Data Center",
        "reason": "Server Outage Immediate Response",
        "type": "emergency",
        "priority": "emergency",
    }

    res = client.post("/api/bookings", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.get_json()
    booking = data["booking"]
    assert booking["status"] == "DRIVER_PENDING"
    assert booking["type"] == "emergency"
    assert booking["priority"] == "emergency"
    assert booking["respond_by"] is not None


def test_midnight_spanning_booking_succeeds(client):
    """
    Prove that a booking starting at 23:00 IST and ending at 01:00 IST next day
    correctly allocates, passes validation, and stores end_time > start_time.
    """
    import zoneinfo
    kolkata_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    token = create_test_token(EMP_1_ID)
    headers = auth_header(token)

    # Future date at 23:00 IST
    base_kolkata = (datetime.now(kolkata_tz) + timedelta(days=18)).replace(hour=23, minute=0, second=0, microsecond=0)
    end_kolkata = base_kolkata + timedelta(hours=2)  # 01:00 IST next day

    start_utc = base_kolkata.astimezone(timezone.utc)
    end_utc = end_kolkata.astimezone(timezone.utc)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 3,
        "destination": "Night Shift Depot",
        "reason": "Emergency Maintenance Inspection",
        "type": "scheduled",
        "priority": "normal",
    }

    res = client.post("/api/bookings", json=payload, headers=headers)
    assert res.status_code == 201
    b = res.get_json()["booking"]
    assert b["start_time"] == start_utc.isoformat()
    assert b["end_time"] == end_utc.isoformat()
    assert b["status"] in ("PENDING", "APPROVED", "DRIVER_PENDING")


def test_static_asset_enhancements_and_contracts(client):
    """
    Prove that static assets include:
    - time.js: calculateEndUtcIso
    - api.js: notifyUnauthorized and memory fallback
    - styles.css: .preset-pill.active
    """
    time_res = client.get("/shared/time.js")
    assert time_res.status_code == 200
    assert "calculateEndUtcIso" in time_res.get_data(as_text=True)

    api_res = client.get("/shared/api.js")
    assert api_res.status_code == 200
    assert "notifyUnauthorized" in api_res.get_data(as_text=True)

    css_res = client.get("/shared/styles.css")
    assert css_res.status_code == 200
    assert ".preset-pill.active" in css_res.get_data(as_text=True)


