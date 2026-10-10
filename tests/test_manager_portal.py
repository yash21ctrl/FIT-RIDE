"""Integration tests for Manager Portal and Gantt endpoints (Phase 7)."""
import json
import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    create_booking,
    get_booking_by_id,
)

MGR_1_PROFILE_ID = "00000000-0000-0000-0002-000000000001"
EMP_1_PROFILE_ID = "00000000-0000-0000-0003-000000000001"
VEH_1_ID = "00000000-0000-0000-0001-000000000001"
VEH_2_ID = "00000000-0000-0000-0001-000000000002"
DRV_1_ID = "00000000-0000-0000-0005-000000000001"
DRV_2_ID = "00000000-0000-0000-0005-000000000002"


@pytest.fixture
def app():
    reset_seed_data()
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_manager_portal_static_routes(client):
    """Test that manager index and app script serve correctly."""
    res_index = client.get("/manager")
    assert res_index.status_code in (200, 308)
    if res_index.status_code == 308:
        res_index = client.get("/manager/")
    assert res_index.status_code == 200
    assert "Fleet Operations Manager" in res_index.get_data(as_text=True)

    res_js = client.get("/manager/app.js")
    assert res_js.status_code == 200
    assert "loadApprovalQueue" in res_js.get_data(as_text=True)


def test_manager_gantt_and_history_endpoints(client):
    """Test Gantt timeline data, history, and alerts."""
    token = create_test_token(profile_id=MGR_1_PROFILE_ID, role="manager")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Gantt data
    res_gantt = client.get("/api/manager/gantt", headers=headers)
    assert res_gantt.status_code == 200
    g_data = res_gantt.get_json()
    assert "vehicles" in g_data
    assert "drivers" in g_data
    assert "bookings" in g_data
    assert len(g_data["vehicles"]) >= 5

    # 2. History data
    res_hist = client.get("/api/manager/history", headers=headers)
    assert res_hist.status_code == 200
    h_data = res_hist.get_json()
    assert "history" in h_data

    # 3. Alerts data
    res_alerts = client.get("/api/manager/alerts", headers=headers)
    assert res_alerts.status_code == 200
    a_data = res_alerts.get_json()
    assert "emergencies" in a_data
    assert "waitlisted" in a_data
    assert "bumped" in a_data


def test_manager_queue_approval_and_override_workflow(client):
    """Test manager reviewing queue, approving, and overriding vehicle assignment."""
    token = create_test_token(profile_id=MGR_1_PROFILE_ID, role="manager")
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(hours=4)
    end_dt = start_dt + timedelta(hours=2)

    booking = create_booking({
        "employee_id": EMP_1_PROFILE_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "blocked_until": (end_dt + timedelta(minutes=15)).isoformat(),
        "destination": "Whitefield Campus",
        "passengers": 3,
        "reason": "Department Workshop",
        "type": "scheduled",
        "priority": "normal",
        "status": "PENDING"
    })

    # Check Queue
    res_queue = client.get("/api/manager/queue", headers=headers)
    assert res_queue.status_code == 200
    q_data = res_queue.get_json()
    assert any(b["id"] == booking["id"] for b in q_data["queue"])

    # Override Vehicle
    res_override = client.post(f"/api/manager/bookings/{booking['id']}/override", headers=headers, json={
        "vehicle_id": VEH_2_ID,
        "driver_id": DRV_2_ID,
        "note": "Assigned Honda City instead of Swift"
    })
    assert res_override.status_code == 200
    b_updated = get_booking_by_id(booking["id"])
    assert b_updated["status"] == "DRIVER_PENDING"
    assert b_updated["vehicle_id"] == VEH_2_ID
    assert b_updated["driver_id"] == DRV_2_ID
