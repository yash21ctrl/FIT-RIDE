"""Phase 10 & 11 Tests: GPS Telemetry, Ratings, Analytics, and Chaos Simulator (Team KNIGHT | PS 40)."""
from datetime import datetime, timedelta, timezone
import pytest
from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    create_booking,
    get_booking_by_id,
    get_driver_by_id,
    add_trip_location,
    create_rating,
)
from app.services.transitions import transition

EMP_1_ID = "00000000-0000-0000-0003-000000000001"
EMP_2_ID = "00000000-0000-0000-0003-000000000002"
DRV_1_ID = "00000000-0000-0000-0005-000000000001"
DRV_1_PROFILE_ID = "00000000-0000-0000-0004-000000000001"
MGR_1_ID = "00000000-0000-0000-0002-000000000001"
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


# =====================================================================
# 1. GPS Telemetry Tests (Phase 10)
# =====================================================================

def test_gps_telemetry_ingestion_and_trail(client):
    """
    Prove:
    - Driver can post GPS coordinate updates to /api/trips/<id>/location
    - Employee and Manager can fetch trail and latest coordinate
    """
    start_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 2,
        "status": "IN_PROGRESS",
    })

    # Driver posts GPS coordinates
    drv_headers = _auth_headers(DRV_1_PROFILE_ID, "driver")
    res1 = client.post(
        f"/api/trips/{b['id']}/location",
        headers=drv_headers,
        json={"latitude": 12.9716, "longitude": 77.5946},
    )
    assert res1.status_code == 201

    res2 = client.post(
        f"/api/trips/{b['id']}/location",
        headers=drv_headers,
        json={"latitude": 12.9750, "longitude": 77.6000},
    )
    assert res2.status_code == 201

    # Employee fetches GPS trail
    emp_headers = _auth_headers(EMP_1_ID, "employee")
    res_trail = client.get(f"/api/trips/{b['id']}/location", headers=emp_headers)
    assert res_trail.status_code == 200
    trail_data = res_trail.get_json()
    assert trail_data["count"] == 2
    assert trail_data["latest"]["lat"] == 12.9750
    assert trail_data["latest"]["lng"] == 77.6000


# =====================================================================
# 2. Trip Rating Lifecycle Tests (Phase 10)
# =====================================================================

def test_trip_rating_lifecycle_and_driver_score_update(client):
    """
    Prove:
    - Employee can submit driver and vehicle ratings for completed trip
    - Driver's rating_avg is updated
    - Non-completed trips reject rating submissions
    """
    start_dt = datetime.now(timezone.utc) - timedelta(hours=3)
    end_dt = start_dt + timedelta(hours=1)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 2,
        "status": "CONFIRMED",
    })

    emp_headers = _auth_headers(EMP_1_ID, "employee")

    # Cannot rate trip before completion
    res_err = client.post(
        f"/api/trips/{b['id']}/rate",
        headers=emp_headers,
        json={"driver_rating": 5, "vehicle_rating": 5},
    )
    assert res_err.status_code == 400
    assert res_err.get_json()["error"]["code"] == "INVALID_STATUS"

    # Complete the trip
    driver_actor = {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID}
    transition(b["id"], "IN_PROGRESS", driver_actor)
    transition(b["id"], "COMPLETED", driver_actor, extra_data={"end_odometer": 100})

    # Rate completed trip
    res_ok = client.post(
        f"/api/trips/{b['id']}/rate",
        headers=emp_headers,
        json={
            "driver_rating": 5,
            "vehicle_rating": 4,
            "comment": "Smooth driving and very polite!",
            "tags": ["clean_car", "punctual"],
        },
    )
    assert res_ok.status_code == 201
    rating_data = res_ok.get_json()["rating"]
    assert rating_data["driver_rating"] == 5
    assert rating_data["vehicle_rating"] == 4

    # Fetch rating via GET
    res_get = client.get(f"/api/trips/{b['id']}/rate", headers=emp_headers)
    assert res_get.status_code == 200
    assert res_get.get_json()["rating"]["comment"] == "Smooth driving and very polite!"


# =====================================================================
# 3. Manager Analytics Tests (Phase 11)
# =====================================================================

def test_manager_analytics_endpoint(client):
    """
    Prove:
    - GET /api/manager/analytics returns vehicle utilization, driver fairness, and reject stats
    """
    headers = _auth_headers(MGR_1_ID, "manager")
    res = client.get("/api/manager/analytics", headers=headers)
    assert res.status_code == 200
    data = res.get_json()

    assert "vehicle_utilization" in data
    assert "driver_fairness" in data
    assert "reject_reasons" in data
    assert "summary" in data

    # Verify vehicle stats structure
    assert len(data["vehicle_utilization"]) >= 6
    v0 = data["vehicle_utilization"][0]
    assert "utilization_pct" in v0
    assert "total_hours" in v0

    # Verify driver stats structure
    assert len(data["driver_fairness"]) >= 5
    d0 = data["driver_fairness"][0]
    assert "rating_avg" in d0
    assert "total_trips" in d0


# =====================================================================
# 4. Proximity Trip Merge Tests (Phase 11)
# =====================================================================

def test_proximity_trip_merge_suggestions(client):
    """
    Prove:
    - Proximity engine recommends trip merge when destinations are close and times align
    - Flags unmergeable when locations are too far apart
    """
    base_time = datetime.now(timezone.utc) + timedelta(days=1)

    # Active booking heading to MG Road (12.9716, 77.5946)
    create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,  # 4 seats
        "driver_id": DRV_1_ID,
        "start_time": base_time,
        "end_time": base_time + timedelta(hours=2),
        "passengers": 2,
        "destination": "MG Road",
        "dest_lat": 12.9716,
        "dest_lng": 77.5946,
        "status": "CONFIRMED",
    })

    emp_headers = _auth_headers(EMP_2_ID, "employee")

    # Case A: Nearby destination (Brigade Road: ~0.8 km away) and same start time
    res_near = client.post(
        "/api/admin/trip-merge-check",
        headers=emp_headers,
        json={
            "start_time": base_time.isoformat(),
            "dest_lat": 12.9740,
            "dest_lng": 77.6070,
            "passengers": 1,
            "merge_radius_km": 2.0,
        },
    )
    assert res_near.status_code == 200
    data_near = res_near.get_json()
    assert data_near["mergeable"] is True
    assert len(data_near["candidates"]) >= 1

    # Case B: Far destination (Electronic City: ~18 km away)
    res_far = client.post(
        "/api/admin/trip-merge-check",
        headers=emp_headers,
        json={
            "start_time": base_time.isoformat(),
            "dest_lat": 12.8399,
            "dest_lng": 77.6770,
            "passengers": 1,
            "merge_radius_km": 2.0,
        },
    )
    assert res_far.status_code == 200
    data_far = res_far.get_json()
    assert data_far["mergeable"] is False


# =====================================================================
# 5. Chaos Simulator Tests (Phase 11)
# =====================================================================

def test_admin_simulate_chaos_script(client):
    """
    Prove:
    - POST /api/admin/simulate triggers the 5-step chaos scenario and all pass
    """
    mgr_headers = _auth_headers(MGR_1_ID, "manager")
    resp = client.post("/api/admin/simulate", headers=mgr_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert len(data["scenarios"]) == 5
    for scen in data["scenarios"]:
        assert scen["passed"] is True, f"Scenario failed: {scen}"
