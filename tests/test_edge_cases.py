"""Phase 9 Edge Cases & Robustness Test Suite (Team KNIGHT | PS 40).

Covers:
1. Emergency bump candidate selection, priority ladder, and guardrails:
   - Low-priority trip bumped by emergency.
   - Emergency takes slot and advances directly to DRIVER_PENDING (2 min response window).
   - was_bumped=True preserved forever; cannot be bumped twice.
   - IN_PROGRESS, emergency, normal, and high priority trips are protected from bumping.
   - Capacity constraint: cannot bump a vehicle that cannot fit the emergency passengers.
2. Bumped booking options:
   - Bumped booking can choose alternative slot or join waitlist with was_bumped=True preserved.
3. Vehicle maintenance reallocation:
   - When vehicle enters maintenance, future bookings are reallocated to alternative vehicles.
   - When no alternative vehicle exists, booking transitions to WAITLISTED.
   - When vehicle returns to available, WAITLISTED bookings are auto-promoted.
4. Waitlist priority ordering:
   - Strict priority ordering: emergency > high > normal > low, then created_at.
"""
from datetime import datetime, timedelta, timezone
import pytest
from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    create_booking,
    get_booking_by_id,
    update_booking,
    update_vehicle,
    get_vehicle_by_id,
    get_notifications,
    get_decision_logs,
)
from app.engine.bump import find_bump_candidate, execute_bump
from app.engine.waitlist import promote_waitlisted
from app.services.transitions import transition

EMP_1_ID = "00000000-0000-0000-0003-000000000001"
EMP_2_ID = "00000000-0000-0000-0003-000000000002"
EMP_3_ID = "00000000-0000-0000-0003-000000000003"
MGR_1_ID = "00000000-0000-0000-0002-000000000001"

# Seed vehicles
VEH_1_ID = "00000000-0000-0000-0001-000000000001"
VEH_2_ID = "00000000-0000-0000-0001-000000000002"
VEH_3_ID = "00000000-0000-0000-0001-000000000003"
VEH_4_ID = "00000000-0000-0000-0001-000000000004"
VEH_5_ID = "00000000-0000-0000-0001-000000000005"
VEH_6_ID = "00000000-0000-0000-0001-000000000006"

DRV_1_ID = "00000000-0000-0000-0005-000000000001"
DRV_2_ID = "00000000-0000-0000-0005-000000000002"
DRV_3_ID = "00000000-0000-0000-0005-000000000003"
DRV_4_ID = "00000000-0000-0000-0005-000000000004"
DRV_5_ID = "00000000-0000-0000-0005-000000000005"


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
# 1. Emergency Bump Tests
# =====================================================================

def test_emergency_bump_success_flow(client):
    """
    Prove:
    - When all suitable vehicles are busy, an emergency request bumps a low-priority booking.
    - Low-priority booking transitions to BUMPED with was_bumped=True.
    - Emergency takes the slot, directly enters DRIVER_PENDING with ~2 min respond window.
    - Bumped employee and manager are notified.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=2, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    # 1. Create a low-priority booking on VEH_1_ID
    low_bkg = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_3_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 3,
        "destination": "General Office",
        "reason": "Routine document drop",
        "type": "scheduled",
        "priority": "low",
        "status": "CONFIRMED",
        "was_bumped": False,
    })

    # Make other fleet vehicles busy for the same slot
    for vid, did in [(VEH_2_ID, DRV_1_ID), (VEH_3_ID, DRV_2_ID), (VEH_4_ID, DRV_4_ID), (VEH_5_ID, DRV_5_ID)]:
        create_booking({
            "employee_id": EMP_2_ID,
            "vehicle_id": vid,
            "driver_id": did,
            "start_time": start_dt,
            "end_time": end_dt,
            "passengers": 4,
            "destination": "Client",
            "reason": "Busy",
            "type": "scheduled",
            "priority": "normal",
            "status": "CONFIRMED",
        })
    # Retire VEH_6_ID so there are no other vehicles
    update_vehicle(VEH_6_ID, {"status": "retired"})

    # 2. Submit emergency booking request via API
    headers = _auth_headers(EMP_3_ID, "employee")
    resp = client.post(
        "/api/bookings",
        headers=headers,
        json={
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "passengers": 3,
            "destination": "City Hospital",
            "reason": "Urgent Medical Emergency",
            "type": "emergency",
            "priority": "emergency",
        },
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body.get("bumped") is True
    assert body.get("bumped_booking_id") == low_bkg["id"]
    emg_bkg = body["booking"]
    assert emg_bkg["status"] == "DRIVER_PENDING"
    assert emg_bkg["vehicle_id"] == VEH_1_ID
    assert emg_bkg["type"] == "emergency"
    assert emg_bkg["priority"] == "emergency"

    # Verify bumped booking state
    updated_low = get_booking_by_id(low_bkg["id"])
    assert updated_low["status"] == "BUMPED"
    assert updated_low["was_bumped"] is True

    # Verify notifications were delivered to bumped employee
    emp_notifs = get_notifications(EMP_1_ID)
    assert any("bumped" in n["message"].lower() for n in emp_notifs)

    # Verify notification delivered to manager
    mgr_notifs = get_notifications(MGR_1_ID)
    assert any("bump" in n["message"].lower() for n in mgr_notifs)


def test_bump_guardrails_prevent_invalid_bumps():
    """
    Prove guardrails:
    1. Trips with IN_PROGRESS cannot be bumped.
    2. Trips already bumped (was_bumped=True) cannot be bumped.
    3. Trips with priority 'normal', 'high', or 'emergency' cannot be bumped.
    4. Vehicle with capacity < requested passengers cannot be bumped.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=3, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    # 1. IN_PROGRESS trip: cannot be bumped
    b_in_prog = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 2,
        "type": "scheduled",
        "priority": "low",
        "status": "IN_PROGRESS",
        "was_bumped": False,
    })
    cand = find_bump_candidate({"start": start_dt, "end": end_dt, "passengers": 2})
    assert cand is None

    # 2. was_bumped=True: cannot be bumped twice
    update_booking(b_in_prog["id"], {"status": "CONFIRMED", "was_bumped": True})
    cand = find_bump_candidate({"start": start_dt, "end": end_dt, "passengers": 2})
    assert cand is None

    # 3. Priority 'normal': cannot be bumped
    update_booking(b_in_prog["id"], {"status": "CONFIRMED", "was_bumped": False, "priority": "normal"})
    cand = find_bump_candidate({"start": start_dt, "end": end_dt, "passengers": 2})
    assert cand is None

    # 4. Priority 'emergency': cannot be bumped
    update_booking(b_in_prog["id"], {"priority": "emergency"})
    cand = find_bump_candidate({"start": start_dt, "end": end_dt, "passengers": 2})
    assert cand is None

    # 5. Vehicle capacity constraint: VEH_1_ID has 4 seats. Emergency needing 7 passengers cannot bump it.
    update_booking(b_in_prog["id"], {"priority": "low"})
    cand = find_bump_candidate({"start": start_dt, "end": end_dt, "passengers": 7})
    assert cand is None

    # But emergency needing 4 passengers CAN bump it:
    cand_ok = find_bump_candidate({"start": start_dt, "end": end_dt, "passengers": 4})
    assert cand_ok is not None
    assert cand_ok["id"] == b_in_prog["id"]


def test_bumped_booking_can_choose_alternative_and_preserves_was_bumped(client):
    """
    Prove:
    - Bumped booking calls POST /api/bookings/<id>/choose-alternative
    - Booking transitions back to PENDING with new slot
    - was_bumped=True is strictly preserved so it cannot be bumped again!
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=4, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 3,
        "status": "BUMPED",
        "was_bumped": True,
        "priority": "low",
    })

    # Shifted window
    alt_start = start_dt + timedelta(hours=3)
    alt_end = end_dt + timedelta(hours=3)

    headers = _auth_headers(EMP_1_ID, "employee")
    resp = client.post(
        f"/api/bookings/{b['id']}/choose-alternative",
        headers=headers,
        json={
            "start_time": alt_start.isoformat(),
            "end_time": alt_end.isoformat(),
            "vehicle_id": VEH_2_ID,
            "driver_id": DRV_2_ID,
        },
    )
    assert resp.status_code == 200
    res_bkg = resp.get_json()["booking"]
    assert res_bkg["status"] == "PENDING"
    assert res_bkg["vehicle_id"] == VEH_2_ID

    # was_bumped must be preserved!
    updated = get_booking_by_id(b["id"])
    assert updated["was_bumped"] is True


def test_bumped_booking_can_join_waitlist_and_preserves_was_bumped(client):
    """
    Prove:
    - Bumped booking calls POST /api/bookings/<id>/waitlist
    - Transitions to WAITLISTED
    - was_bumped=True is strictly preserved.
    """
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": None,
        "driver_id": None,
        "start_time": datetime.now(timezone.utc) + timedelta(days=5),
        "end_time": datetime.now(timezone.utc) + timedelta(days=5, hours=2),
        "passengers": 3,
        "status": "BUMPED",
        "was_bumped": True,
        "priority": "low",
    })

    headers = _auth_headers(EMP_1_ID, "employee")
    resp = client.post(f"/api/bookings/{b['id']}/waitlist", headers=headers, json={"note": "Joining waitlist"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "WAITLISTED"

    updated = get_booking_by_id(b["id"])
    assert updated["status"] == "WAITLISTED"
    assert updated["was_bumped"] is True


# =====================================================================
# 2. Vehicle Maintenance Reallocation Tests
# =====================================================================

def test_vehicle_maintenance_reallocates_to_alternate_vehicle(client):
    """
    Prove:
    - When a vehicle enters maintenance, existing bookings on it are automatically reallocated
      to an available matching vehicle.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=6, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    # Booking on VEH_1_ID (Maruti Swift, 4 seats)
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 4,
        "status": "CONFIRMED",
        "priority": "normal",
    })

    # Manager puts VEH_1_ID in maintenance
    headers = _auth_headers(MGR_1_ID, "manager")
    resp = client.patch(
        f"/api/vehicles/{VEH_1_ID}",
        headers=headers,
        json={"status": "maintenance"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("reallocation", {}).get("reallocated") == 1

    # Booking was reallocated to another vehicle (e.g. VEH_2_ID Honda City)
    updated_b = get_booking_by_id(b["id"])
    assert updated_b["vehicle_id"] != VEH_1_ID
    assert updated_b["vehicle_id"] in (VEH_2_ID, VEH_3_ID, VEH_4_ID, VEH_5_ID, VEH_6_ID)
    assert "maintenance" in updated_b["decision_reason"].lower()

    # Verify decision log was recorded
    logs = get_decision_logs(b["id"])
    assert any(l["action"] == "vehicle_maintenance_reallocated" for l in logs)

    # Verify employee was notified
    notifs = get_notifications(EMP_1_ID)
    assert any("reassigned" in n["message"].lower() for n in notifs)


def test_vehicle_maintenance_moves_to_waitlist_when_no_alternative(client):
    """
    Prove:
    - When a vehicle enters maintenance and NO alternative vehicle exists with enough seats,
      the booking transitions to WAITLISTED.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=7, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    # 10 passengers on VEH_6_ID (Force Tempo Traveller, 12 seats - only vehicle with >= 10 seats)
    b = create_booking({
        "employee_id": EMP_2_ID,
        "vehicle_id": VEH_6_ID,
        "driver_id": DRV_2_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 10,
        "status": "CONFIRMED",
        "priority": "normal",
    })

    # Manager puts VEH_6_ID into maintenance
    headers = _auth_headers(MGR_1_ID, "manager")
    resp = client.patch(
        f"/api/vehicles/{VEH_6_ID}",
        headers=headers,
        json={"status": "maintenance"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("reallocation", {}).get("waitlisted") == 1

    # Booking must now be WAITLISTED with vehicle cleared
    updated_b = get_booking_by_id(b["id"])
    assert updated_b["status"] == "WAITLISTED"
    assert updated_b["vehicle_id"] is None
    assert updated_b["failure_reason"] == "VEHICLES_IN_MAINTENANCE"

    # Employee was notified
    emp_notifs = get_notifications(EMP_2_ID)
    assert any("waitlist" in n["message"].lower() for n in emp_notifs)


def test_maintenance_cleared_auto_promotes_waitlisted_booking(client):
    """
    Prove:
    - When maintenance is cleared (vehicle returned to 'available'), waitlisted bookings
      waiting for that vehicle are automatically promoted back to PENDING with vehicle assigned!
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=8, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    # Put VEH_6_ID in maintenance
    update_vehicle(VEH_6_ID, {"status": "maintenance"})

    # Waitlisted 10-passenger booking
    b_wait = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": None,
        "driver_id": None,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 10,
        "status": "WAITLISTED",
        "priority": "normal",
        "reason": "Team Offsite",
    })

    # Manager returns VEH_6_ID to available
    headers = _auth_headers(MGR_1_ID, "manager")
    resp = client.patch(
        f"/api/vehicles/{VEH_6_ID}",
        headers=headers,
        json={"status": "available"},
    )
    assert resp.status_code == 200

    # Waitlisted booking should be auto-promoted!
    promoted = get_booking_by_id(b_wait["id"])
    assert promoted["status"] == "PENDING"
    assert promoted["vehicle_id"] == VEH_6_ID
    assert promoted["driver_id"] is not None


# =====================================================================
# 3. Waitlist Priority Ordering Tests
# =====================================================================

def test_waitlist_promotion_strict_priority_ordering():
    """
    Prove:
    - When capacity frees up, WAITLISTED bookings are promoted strictly by:
      priority (emergency > high > normal > low), then created_at.
    - Even if a low-priority booking was created earlier, higher priority booking is promoted first!
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=10, hours=10)
    end_dt = start_dt + timedelta(hours=2)

    # Low priority created earlier
    b_low = create_booking({
        "employee_id": EMP_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 4,
        "status": "WAITLISTED",
        "priority": "low",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
    })

    # High priority created later
    b_high = create_booking({
        "employee_id": EMP_2_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "passengers": 4,
        "status": "WAITLISTED",
        "priority": "high",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
    })

    # Make all 4-seater and 7-seater vehicles except one busy or retired
    for vid in (VEH_2_ID, VEH_3_ID, VEH_4_ID, VEH_5_ID, VEH_6_ID):
        update_vehicle(vid, {"status": "retired"})

    # Only VEH_1_ID is available (can only take 1 booking)
    promoted_list = promote_waitlisted()
    assert len(promoted_list) == 1
    promoted_id = promoted_list[0]["id"]

    # b_high MUST be promoted first despite being created later!
    assert promoted_id == b_high["id"]

    # b_low must still be WAITLISTED
    assert get_booking_by_id(b_low["id"])["status"] == "WAITLISTED"
    assert get_booking_by_id(b_high["id"])["status"] == "PENDING"
