"""State machine transition and booking lifecycle tests (Team KNIGHT | PS 40).

Covers all Phase 4 specifications:
1. Full booking lifecycle: Request -> Approve -> Accept -> Start -> End -> COMPLETED.
2. Illegal transition jumps (e.g. PENDING -> COMPLETED, CONFIRMED -> REJECTED, etc.) rejected.
3. Employee cannot cancel another employee's booking (403), manager can cancel any.
4. Driver cannot accept or start another driver's booking (403).
5. 30-second double-submit idempotency guard blocks duplicate requests (409).
6. Auto-approve rule advances qualifying routine bookings to DRIVER_PENDING.
7. Driver reject with mandatory reason records in driver_responses and transitions.
8. Manager override vehicle and driver with capacity validation.
9. Waitlist auto-promotion upon slot-freeing events.
"""
from datetime import datetime, timedelta, timezone
import pytest
import zoneinfo

from app import create_app
from app.auth import create_test_token
from app.db import (
    reset_seed_data,
    get_booking_by_id,
    get_vehicle_by_id,
    get_driver_by_id,
    get_trip_by_booking_id,
    get_decision_logs,
    get_driver_responses,
    get_notifications,
    create_booking,
)
from app.services.transitions import (
    transition,
    ALLOWED,
    IllegalTransitionError,
    ForbiddenTransitionError,
    BookingNotFoundError,
)

KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

# Canonical Seed IDs matching migrations/003_seed.sql
MGR_1_ID = "00000000-0000-0000-0002-000000000001"
MGR_2_ID = "00000000-0000-0000-0002-000000000002"
EMP_1_ID = "00000000-0000-0000-0003-000000000001"
EMP_2_ID = "00000000-0000-0000-0003-000000000002"
DRV_1_PROFILE_ID = "00000000-0000-0000-0004-000000000001"
DRV_1_ID = "00000000-0000-0000-0005-000000000001"
DRV_2_PROFILE_ID = "00000000-0000-0000-0004-000000000002"
DRV_2_ID = "00000000-0000-0000-0005-000000000002"
VEH_1_ID = "00000000-0000-0000-0001-000000000001"
VEH_3_ID = "00000000-0000-0000-0001-000000000003"
VEH_6_ID = "00000000-0000-0000-0001-000000000006"


@pytest.fixture(autouse=True)
def setup_seed():
    """Reset data before each test."""
    reset_seed_data()


@pytest.fixture
def client():
    """Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# =====================================================================
# 1. Full Booking Lifecycle Test
# =====================================================================

def test_full_booking_lifecycle_through_api(client):
    """
    Test complete lifecycle:
    1. Employee submits high-priority request (skips auto-approve) -> PENDING
    2. Manager approves -> DRIVER_PENDING with respond_by
    3. Assigned Driver accepts -> CONFIRMED
    4. Driver starts trip -> IN_PROGRESS, driver status 'on_trip'
    5. Driver ends trip -> COMPLETED, driver & vehicle freed, odometer updated
    """
    emp_token = create_test_token(EMP_1_ID)
    mgr_token = create_test_token(MGR_1_ID)

    # Future window: tomorrow 10:00 to 12:00 in Asia/Kolkata
    base_kolkata = (datetime.now(KOLKATA_TZ) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    start_utc = base_kolkata.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=2)

    # 1. Request (priority='high' requires manager review)
    req_body = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 4,
        "destination": "Client Office Bangalore",
        "reason": "Executive Quarterly Review",
        "type": "scheduled",
        "priority": "high",
    }
    res_req = client.post("/api/bookings", json=req_body, headers=auth_header(emp_token))
    assert res_req.status_code == 201, res_req.get_data(as_text=True)
    req_data = res_req.get_json()
    booking = req_data["booking"]
    booking_id = booking["id"]
    assert booking["status"] == "PENDING"
    assert req_data["auto_approved"] is False
    assert len(req_data["options"]) >= 1
    assigned_driver_id = booking["driver_id"]
    assigned_vehicle_id = booking["vehicle_id"]

    # 2. Manager views queue
    res_queue = client.get("/api/manager/queue", headers=auth_header(mgr_token))
    assert res_queue.status_code == 200
    queue = res_queue.get_json()["queue"]
    assert any(q["id"] == booking_id for q in queue)

    # Manager approves booking
    res_app = client.post(
        f"/api/manager/bookings/{booking_id}/approve",
        json={"note": "Verified executive trip"},
        headers=auth_header(mgr_token),
    )
    assert res_app.status_code == 200
    app_data = res_app.get_json()
    assert app_data["status"] == "DRIVER_PENDING"
    assert app_data["booking"]["respond_by"] is not None

    # 3. Driver fetches assigned requests
    drv_rec = get_driver_by_id(assigned_driver_id)
    drv_token = create_test_token(drv_rec["profile_id"])

    res_drv_reqs = client.get("/api/driver/requests", headers=auth_header(drv_token))
    assert res_drv_reqs.status_code == 200
    requests_list = res_drv_reqs.get_json()["requests"]
    assert any(r["id"] == booking_id for r in requests_list)

    # Driver accepts trip -> CONFIRMED
    res_acc = client.post(
        f"/api/driver/bookings/{booking_id}/accept",
        headers=auth_header(drv_token),
    )
    assert res_acc.status_code == 200
    assert res_acc.get_json()["status"] == "CONFIRMED"

    # 4. Driver starts trip -> IN_PROGRESS
    res_start = client.post(
        f"/api/trips/{booking_id}/start",
        json={"start_odometer": 12500, "checklist": {"fuel_ok": True, "tires_ok": True}},
        headers=auth_header(drv_token),
    )
    assert res_start.status_code == 200
    start_data = res_start.get_json()
    assert start_data["status"] == "IN_PROGRESS"
    assert start_data["trip"]["start_odometer"] == 12500

    # Verify driver status is 'on_trip'
    updated_drv = get_driver_by_id(assigned_driver_id)
    assert updated_drv["status"] == "on_trip"

    # 5. Driver ends trip -> COMPLETED
    res_end = client.post(
        f"/api/trips/{booking_id}/end",
        json={"end_odometer": 12560, "fuel_added": 15.0},
        headers=auth_header(drv_token),
    )
    assert res_end.status_code == 200
    end_data = res_end.get_json()
    assert end_data["status"] == "COMPLETED"
    assert end_data["trip"]["end_odometer"] == 12560
    assert end_data["trip"]["fuel_added"] == 15.0

    # Verify driver status is freed to 'available'
    freed_drv = get_driver_by_id(assigned_driver_id)
    assert freed_drv["status"] == "available"

    # Verify vehicle status is freed to 'available' and odometer updated
    freed_veh = get_vehicle_by_id(assigned_vehicle_id)
    assert freed_veh["status"] == "available"
    assert freed_veh["odometer_km"] == 12560

    # Verify audit decision_log has entries
    logs = get_decision_logs(booking_id)
    actions = [l["action"] for l in logs]
    assert "approved" in actions
    assert "dispatched" in actions
    assert "driver_accepted" in actions
    assert "trip_started" in actions
    assert "trip_completed" in actions


# =====================================================================
# 2. Illegal Transition Jumps Rejected
# =====================================================================

def test_illegal_transition_jumps_rejected(client):
    """
    Prove state machine strictly rejects invalid jumps:
    - PENDING -> COMPLETED
    - CONFIRMED -> REJECTED
    - COMPLETED -> IN_PROGRESS
    - CANCELLED -> APPROVED
    - REJECTED -> CONFIRMED
    - IN_PROGRESS -> CANCELLED
    """
    # Create booking in PENDING
    start_dt = datetime.now(timezone.utc) + timedelta(days=2)
    end_dt = start_dt + timedelta(hours=2)
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Test Destination",
        "passengers": 2,
        "reason": "Test",
        "status": "PENDING",
    })
    bid = b["id"]

    system_actor = {"id": "system", "role": "system"}

    # 1. PENDING -> COMPLETED (Illegal jump)
    with pytest.raises(IllegalTransitionError) as exc_info:
        transition(bid, "COMPLETED", system_actor)
    assert "Illegal status transition from 'PENDING' to 'COMPLETED'" in str(exc_info.value)

    # 2. Advance to CONFIRMED
    transition(bid, "APPROVED", system_actor)
    transition(bid, "DRIVER_PENDING", system_actor)
    transition(bid, "CONFIRMED", {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID})

    # CONFIRMED -> REJECTED (Illegal jump)
    with pytest.raises(IllegalTransitionError):
        transition(bid, "REJECTED", {"id": MGR_1_ID, "role": "manager"})

    # 3. Advance to IN_PROGRESS
    transition(bid, "IN_PROGRESS", {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID})

    # IN_PROGRESS -> CANCELLED (Illegal jump; cannot cancel trip once in progress)
    with pytest.raises(IllegalTransitionError):
        transition(bid, "CANCELLED", {"id": MGR_1_ID, "role": "manager"})

    # 4. Advance to COMPLETED
    transition(bid, "COMPLETED", {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID})

    # COMPLETED -> IN_PROGRESS (Terminal state)
    with pytest.raises(IllegalTransitionError):
        transition(bid, "IN_PROGRESS", system_actor)

    # 5. CANCELLED -> APPROVED
    b_cancel = create_booking({
        "employee_id": EMP_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Test",
        "passengers": 2,
        "reason": "Test",
        "status": "CANCELLED",
    })
    with pytest.raises(IllegalTransitionError):
        transition(b_cancel["id"], "APPROVED", {"id": MGR_1_ID, "role": "manager"})

    # 6. REJECTED -> CONFIRMED
    b_rej = create_booking({
        "employee_id": EMP_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Test",
        "passengers": 2,
        "reason": "Test",
        "status": "REJECTED",
    })
    with pytest.raises(IllegalTransitionError):
        transition(b_rej["id"], "CONFIRMED", {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID})


# =====================================================================
# 3. Cancellation Permissions (Employee own vs another, Manager any)
# =====================================================================

def test_cancellation_permissions_employee_and_manager(client):
    """
    Prove:
    - Employee 2 cannot cancel Employee 1's booking (403 Forbidden).
    - Employee 1 can cancel own booking (200 OK).
    - Manager can cancel any booking before trip starts (200 OK).
    """
    emp1_token = create_test_token(EMP_1_ID)
    emp2_token = create_test_token(EMP_2_ID)
    mgr_token = create_test_token(MGR_1_ID)

    start_dt = datetime.now(timezone.utc) + timedelta(days=3)
    end_dt = start_dt + timedelta(hours=2)

    # Booking 1 owned by Employee 1
    b1 = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Airport",
        "passengers": 2,
        "reason": "Flight",
        "status": "PENDING",
    })

    # A. Employee 2 attempts to cancel Employee 1's booking -> 403
    res_other = client.post(
        f"/api/bookings/{b1['id']}/cancel",
        headers=auth_header(emp2_token),
    )
    assert res_other.status_code == 403
    assert res_other.get_json()["error"]["code"] == "FORBIDDEN"

    # B. Employee 1 cancels own booking -> 200
    res_own = client.post(
        f"/api/bookings/{b1['id']}/cancel",
        headers=auth_header(emp1_token),
    )
    assert res_own.status_code == 200
    assert res_own.get_json()["status"] == "CANCELLED"

    # Booking 2 owned by Employee 1
    b2 = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_3_ID,
        "driver_id": DRV_2_ID,
        "start_time": start_dt + timedelta(days=1),
        "end_time": end_dt + timedelta(days=1),
        "destination": "Client Site",
        "passengers": 3,
        "reason": "Project Kickoff",
        "status": "CONFIRMED",
    })

    # C. Manager cancels Employee 1's booking -> 200
    res_mgr = client.post(
        f"/api/bookings/{b2['id']}/cancel",
        json={"reason": "Project rescheduled by management"},
        headers=auth_header(mgr_token),
    )
    assert res_mgr.status_code == 200
    assert res_mgr.get_json()["status"] == "CANCELLED"


# =====================================================================
# 4. Driver Permissions (Assigned vs Unassigned)
# =====================================================================

def test_driver_cannot_accept_or_start_another_drivers_booking(client):
    """
    Prove:
    - Driver 2 cannot accept Driver 1's booking (403 Forbidden).
    - Driver 2 cannot start Driver 1's trip (403 Forbidden).
    """
    drv1_token = create_test_token(DRV_1_PROFILE_ID)
    drv2_token = create_test_token(DRV_2_PROFILE_ID)

    start_dt = datetime.now(timezone.utc) + timedelta(days=3)
    end_dt = start_dt + timedelta(hours=2)

    # Booking assigned to Driver 1 in DRIVER_PENDING
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Station",
        "passengers": 1,
        "reason": "Transit",
        "status": "DRIVER_PENDING",
    })
    bid = b["id"]

    # Driver 2 tries to accept Driver 1's booking -> 403
    res_acc = client.post(f"/api/driver/bookings/{bid}/accept", headers=auth_header(drv2_token))
    assert res_acc.status_code == 403
    assert res_acc.get_json()["error"]["code"] == "FORBIDDEN"

    # Driver 1 accepts -> 200
    res_acc_ok = client.post(f"/api/driver/bookings/{bid}/accept", headers=auth_header(drv1_token))
    assert res_acc_ok.status_code == 200
    assert res_acc_ok.get_json()["status"] == "CONFIRMED"

    # Driver 2 tries to start Driver 1's trip -> 403
    res_start = client.post(
        f"/api/trips/{bid}/start",
        json={"start_odometer": 12500},
        headers=auth_header(drv2_token),
    )
    assert res_start.status_code == 403
    assert res_start.get_json()["error"]["code"] == "FORBIDDEN"


# =====================================================================
# 5. 30-Second Double-Submit Idempotency Guard
# =====================================================================

def test_idempotency_guard_blocks_duplicate_requests(client):
    """
    Prove:
    - First booking request succeeds (201 Created).
    - Immediate second request from same employee within 30s is rejected (409 Conflict, DUPLICATE_REQUEST).
    """
    emp_token = create_test_token(EMP_1_ID)

    # 10:00 AM - 12:00 PM Kolkata time with priority='high' so it stays PENDING for manager review
    kolkata_time = (datetime.now(KOLKATA_TZ) + timedelta(days=4)).replace(hour=10, minute=0, second=0, microsecond=0)
    start_utc = kolkata_time.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=2)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 3,
        "destination": "Whitefield IT Park",
        "reason": "Client Architecture Workshop",
        "type": "scheduled",
        "priority": "high",
    }

    # 1. First submission succeeds and remains PENDING
    res1 = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res1.status_code == 201
    assert res1.get_json()["booking"]["status"] == "PENDING"

    # 2. Second immediate submission from same employee is blocked by idempotency guard
    res2 = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res2.status_code == 409
    data2 = res2.get_json()
    assert data2["error"]["code"] == "DUPLICATE_REQUEST"
    assert "within the last 30 seconds" in data2["error"]["message"]


# =====================================================================
# 6. Auto-Approve Rule Tests
# =====================================================================

def test_auto_approve_rule_advances_qualifying_booking_to_driver_pending(client):
    """
    Rule:
    - Scheduled
    - Priority 'low' or 'normal'
    - Duration <= auto_approve_max_hours (4h)
    - Within working_hours (08:00 - 20:00 in Asia/Kolkata)
    -> Automatically transitions PENDING -> APPROVED -> DRIVER_PENDING with respond_by set.
    """
    emp_token = create_test_token(EMP_1_ID)

    # 11:00 AM to 02:00 PM in Asia/Kolkata (3h duration, within 08:00-20:00)
    kolkata_target = (datetime.now(KOLKATA_TZ) + timedelta(days=5)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    start_utc = kolkata_target.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=3)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 2,
        "destination": "MG Road Corporate Office",
        "reason": "Routine Client Sync",
        "type": "scheduled",
        "priority": "normal",
    }

    res = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res.status_code == 201
    data = res.get_json()
    assert data["auto_approved"] is True
    booking = data["booking"]
    assert booking["status"] == "DRIVER_PENDING"
    assert booking["respond_by"] is not None

    # Verify decision_log entries
    logs = get_decision_logs(booking["id"])
    actions = [l["action"] for l in logs]
    assert "auto_approved" in actions
    assert "dispatched" in actions


def test_auto_approve_skips_when_duration_exceeds_max_hours(client):
    """Prove trips exceeding auto_approve_max_hours do NOT auto-approve and stay PENDING for manager review."""
    from app.config import set_config_override, clear_config_cache
    set_config_override("auto_approve_max_hours", 2.0)

    emp_token = create_test_token(EMP_1_ID)

    kolkata_target = (datetime.now(KOLKATA_TZ) + timedelta(days=6)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    start_utc = kolkata_target.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=3)  # 3h > 2.0h auto_approve cap, but <= 4h continuous limit

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 2,
        "destination": "Mysore Site Visit",
        "reason": "Full Day Field Inspection",
        "type": "scheduled",
        "priority": "normal",
    }

    try:
        res = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
        assert res.status_code == 201
        data = res.get_json()
        assert data["auto_approved"] is False
        assert data["booking"]["status"] == "PENDING"
    finally:
        clear_config_cache()


def test_auto_approve_skips_when_outside_working_hours(client):
    """Prove trips outside working hours (08:00 - 20:00 in Asia/Kolkata) do not auto-approve."""
    emp_token = create_test_token(EMP_1_ID)

    # 05:00 AM to 07:00 AM in Asia/Kolkata (outside 08:00-20:00)
    kolkata_target = (datetime.now(KOLKATA_TZ) + timedelta(days=6)).replace(
        hour=5, minute=0, second=0, microsecond=0
    )
    start_utc = kolkata_target.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=2)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 2,
        "destination": "Early Morning Flight",
        "reason": "Transit",
        "type": "scheduled",
        "priority": "normal",
    }

    res = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res.status_code == 201
    data = res.get_json()
    assert data["auto_approved"] is False
    assert data["booking"]["status"] == "PENDING"


# =====================================================================
# 7. Driver Reject with Mandatory Reason
# =====================================================================

def test_driver_reject_with_mandatory_reason(client):
    """
    Prove:
    - Driver reject requires valid reason from allowed set ('tired', 'vehicle_issue', 'personal', 'too_far', 'unsafe', 'other').
    - Rejection is recorded in driver_responses table.
    - Transitions back to PENDING and triggers engine reallocation.
    """
    drv1_token = create_test_token(DRV_1_PROFILE_ID)

    start_dt = datetime.now(timezone.utc) + timedelta(days=7)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Electronic City",
        "passengers": 2,
        "reason": "Partner Meeting",
        "status": "DRIVER_PENDING",
    })
    bid = b["id"]

    # 1. Invalid reject reason -> 400
    res_bad = client.post(
        f"/api/driver/bookings/{bid}/reject",
        json={"reason": "not_feeling_like_it"},
        headers=auth_header(drv1_token),
    )
    assert res_bad.status_code == 400
    assert res_bad.get_json()["error"]["code"] == "INVALID_REJECT_REASON"

    # 2. Valid reject reason 'tired' -> 200
    res_ok = client.post(
        f"/api/driver/bookings/{bid}/reject",
        json={"reason": "tired"},
        headers=auth_header(drv1_token),
    )
    assert res_ok.status_code == 200
    updated_b = res_ok.get_json()["booking"]
    assert updated_b["status"] == "PENDING"

    # Verify driver_responses record
    responses = get_driver_responses(bid, DRV_1_ID)
    assert len(responses) == 1
    assert responses[0]["response"] == "rejected"
    assert responses[0]["reject_reason"] == "tired"


# =====================================================================
# 8. Manager Override Validation
# =====================================================================

def test_manager_override_validates_capacity_and_advances(client):
    """
    Prove:
    - Manager override validates vehicle capacity.
    - Successfully reassigns vehicle/driver and advances to DRIVER_PENDING.
    """
    mgr_token = create_test_token(MGR_1_ID)

    start_dt = datetime.now(timezone.utc) + timedelta(days=8)
    end_dt = start_dt + timedelta(hours=2)

    # 7-passenger request initially assigned to 7-seater Ertiga (VEH_3_ID)
    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_3_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Convention Center",
        "passengers": 7,
        "reason": "Delegation Transport",
        "status": "PENDING",
    })
    bid = b["id"]

    # A. Override to 4-seater Swift (VEH_1_ID) fails because capacity (4) < passengers (7)
    res_fail = client.post(
        f"/api/manager/bookings/{bid}/override",
        json={"vehicle_id": VEH_1_ID},
        headers=auth_header(mgr_token),
    )
    assert res_fail.status_code == 400
    assert res_fail.get_json()["error"]["code"] == "INSUFFICIENT_CAPACITY"

    # B. Override to 12-seater Tempo Traveller (VEH_6_ID) and Driver 2 succeeds
    res_ok = client.post(
        f"/api/manager/bookings/{bid}/override",
        json={"vehicle_id": VEH_6_ID, "driver_id": DRV_2_ID, "note": "Assigned luxury minibus"},
        headers=auth_header(mgr_token),
    )
    assert res_ok.status_code == 200
    overridden = res_ok.get_json()["booking"]
    assert overridden["vehicle_id"] == VEH_6_ID
    assert overridden["driver_id"] == DRV_2_ID
    assert overridden["status"] == "DRIVER_PENDING"

    # Verify decision_log
    logs = get_decision_logs(bid)
    assert any(l["action"] == "overridden" for l in logs)


# =====================================================================
# 9. Waitlist Auto-Promotion
# =====================================================================

def test_waitlist_auto_promotion_on_cancellation(client):
    """
    Prove:
    - Booking in WAITLISTED status is promoted to PENDING when a slot-freeing event occurs.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=9)
    end_dt = start_dt + timedelta(hours=2)

    # Waitlisted booking for 4 passengers
    b_wait = create_booking({
        "employee_id": EMP_2_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Tech Park",
        "passengers": 4,
        "reason": "Waitlisted Booking",
        "status": "WAITLISTED",
        "priority": "normal",
    })

    # Another active booking on VEH_1_ID gets cancelled
    b_active = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Client Site",
        "passengers": 3,
        "reason": "Cancelling trip",
        "status": "PENDING",
    })

    # Cancel b_active -> triggers waitlist check
    transition(b_active["id"], "CANCELLED", {"id": EMP_1_ID, "role": "employee"})

    # Check that b_wait was promoted to PENDING with vehicle and driver assigned
    promoted = get_booking_by_id(b_wait["id"])
    assert promoted["status"] == "PENDING"
    assert promoted["vehicle_id"] is not None
    assert promoted["driver_id"] is not None


# =====================================================================
# 10. Additional Edge Cases & Robustness Tests
# =====================================================================

def test_booking_not_found_raises_error():
    """Prove transition on nonexistent ID raises BookingNotFoundError."""
    with pytest.raises(BookingNotFoundError):
        transition("00000000-0000-0000-9999-999999999999", "APPROVED", {"id": MGR_1_ID, "role": "manager"})


def test_manager_reject_without_reason_returns_400(client):
    """Prove manager rejection requires a non-empty reason string."""
    mgr_token = create_test_token(MGR_1_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=10)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Test",
        "passengers": 2,
        "reason": "Test",
        "status": "PENDING",
    })

    # Empty reason
    res = client.post(
        f"/api/manager/bookings/{b['id']}/reject",
        json={"reason": "   "},
        headers=auth_header(mgr_token),
    )
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "REASON_REQUIRED"


def test_trip_odometer_validation_errors(client):
    """
    Prove:
    - Negative start_odometer returns 400.
    - end_odometer < start_odometer returns 400.
    """
    drv1_token = create_test_token(DRV_1_PROFILE_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=11)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Airport",
        "passengers": 2,
        "reason": "Trip",
        "status": "CONFIRMED",
    })
    bid = b["id"]

    # 1. Negative start odometer -> 400
    res_neg = client.post(
        f"/api/trips/{bid}/start",
        json={"start_odometer": -50},
        headers=auth_header(drv1_token),
    )
    assert res_neg.status_code == 400
    assert "start_odometer" in res_neg.get_json()["error"]["message"]

    # 2. Valid start
    res_st = client.post(
        f"/api/trips/{bid}/start",
        json={"start_odometer": 1000},
        headers=auth_header(drv1_token),
    )
    assert res_st.status_code == 200

    # 3. End odometer less than start odometer -> 400
    res_less = client.post(
        f"/api/trips/{bid}/end",
        json={"end_odometer": 900},
        headers=auth_header(drv1_token),
    )
    assert res_less.status_code == 400
    assert "cannot be less than start_odometer" in res_less.get_json()["error"]["message"]


def test_cannot_cancel_trip_in_progress(client):
    """Prove cancelling an in-progress trip is rejected."""
    emp_token = create_test_token(EMP_1_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=12)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Airport",
        "passengers": 2,
        "reason": "Trip",
        "status": "IN_PROGRESS",
    })

    res = client.post(f"/api/bookings/{b['id']}/cancel", headers=auth_header(emp_token))
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "CANNOT_CANCEL"


def test_bumping_lifecycle_and_was_bumped_preservation():
    """
    Prove:
    - Booking bumped moves to BUMPED and sets was_bumped=True.
    - BUMPED -> PENDING preserves was_bumped=True.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=13)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Test",
        "passengers": 2,
        "reason": "Routine",
        "status": "CONFIRMED",
        "was_bumped": False,
    })
    bid = b["id"]

    # Transition to BUMPED
    bumped = transition(bid, "BUMPED", {"id": "engine", "role": "system"}, note="Emergency request bumped this trip")
    assert bumped["status"] == "BUMPED"
    assert bumped["was_bumped"] is True

    # Transition BUMPED -> PENDING (employee picks alternative)
    reassigned = transition(bid, "PENDING", {"id": EMP_1_ID, "role": "employee"}, note="Picked alternative slot")
    assert reassigned["status"] == "PENDING"
    assert reassigned["was_bumped"] is True


def test_booking_request_input_validation_errors(client):
    """
    Prove:
    - Passengers < 1 or > 60 -> 400.
    - Start time in past -> 400.
    - End time <= start time -> 400.
    """
    emp_token = create_test_token(EMP_1_ID)
    future_start = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    future_end = (datetime.now(timezone.utc) + timedelta(days=14, hours=2)).isoformat()

    # 1. Invalid passenger counts
    res_zero = client.post("/api/bookings", json={"passengers": 0, "start_time": future_start, "end_time": future_end, "destination": "D", "reason": "R"}, headers=auth_header(emp_token))
    assert res_zero.status_code == 400
    assert res_zero.get_json()["error"]["code"] == "INVALID_PASSENGERS"

    res_65 = client.post("/api/bookings", json={"passengers": 65, "start_time": future_start, "end_time": future_end, "destination": "D", "reason": "R"}, headers=auth_header(emp_token))
    assert res_65.status_code == 400
    assert res_65.get_json()["error"]["code"] == "INVALID_PASSENGERS"

    # 2. Start time in past
    past_start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    res_past = client.post("/api/bookings", json={"passengers": 2, "start_time": past_start, "end_time": future_end, "destination": "D", "reason": "R"}, headers=auth_header(emp_token))
    assert res_past.status_code == 400
    assert res_past.get_json()["error"]["code"] == "INVALID_TIME"

    # 3. End time before start time
    res_rev = client.post("/api/bookings", json={"passengers": 2, "start_time": future_end, "end_time": future_start, "destination": "D", "reason": "R"}, headers=auth_header(emp_token))
    assert res_rev.status_code == 400
    assert res_rev.get_json()["error"]["code"] == "INVALID_TIME"


def test_get_mine_endpoint(client):
    """Prove GET /api/bookings/mine returns personal booking history."""
    emp_token = create_test_token(EMP_1_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=15)
    end_dt = start_dt + timedelta(hours=2)

    create_booking({
        "employee_id": EMP_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Site A",
        "passengers": 2,
        "reason": "Visit",
        "status": "PENDING",
    })

    res = client.get("/api/bookings/mine", headers=auth_header(emp_token))
    assert res.status_code == 200
    bookings = res.get_json()["bookings"]
    assert len(bookings) >= 1
    assert all(b["employee_id"] == EMP_1_ID for b in bookings)


# =====================================================================
# 11. Rigorous Edge Cases & Fix Verification Tests
# =====================================================================

def test_driver_reject_reassigns_to_different_driver(client):
    """
    Prove:
    - When Driver 1 rejects, the booking re-runs allocation excluding Driver 1.
    - The booking driver_id is updated to Driver 2 (or other eligible driver), NOT Driver 1.
    - driver_responses records Driver 1's rejection.
    """
    drv1_token = create_test_token(DRV_1_PROFILE_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=16)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Whitefield",
        "passengers": 2,
        "reason": "Meeting",
        "status": "DRIVER_PENDING",
    })
    bid = b["id"]

    res = client.post(
        f"/api/driver/bookings/{bid}/reject",
        json={"reason": "tired"},
        headers=auth_header(drv1_token),
    )
    assert res.status_code == 200
    updated_b = res.get_json()["booking"]
    assert updated_b["status"] == "PENDING"
    # Ensure rejected driver is NOT reassigned!
    assert updated_b["driver_id"] is not None
    assert updated_b["driver_id"] != DRV_1_ID

    # Verify driver_responses
    responses = get_driver_responses(bid, DRV_1_ID)
    assert len(responses) == 1
    assert responses[0]["response"] == "rejected"
    assert responses[0]["reject_reason"] == "tired"


def test_manager_override_on_driver_pending_booking(client):
    """
    Prove:
    - A booking in DRIVER_PENDING can be overridden by the manager without IllegalTransitionError.
    - Driver or vehicle can be reassigned, respond_by is reset, and status remains DRIVER_PENDING.
    """
    mgr_token = create_test_token(MGR_1_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=17)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Indiranagar",
        "passengers": 2,
        "reason": "Client Visit",
        "status": "DRIVER_PENDING",
    })
    bid = b["id"]

    res = client.post(
        f"/api/manager/bookings/{bid}/override",
        json={"driver_id": DRV_2_ID, "note": "Driver 1 unavailable; manager re-assigned Driver 2"},
        headers=auth_header(mgr_token),
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["status"] == "DRIVER_PENDING"
    assert data["booking"]["driver_id"] == DRV_2_ID
    assert data["booking"]["vehicle_id"] == VEH_1_ID

    # Verify decision_log
    logs = get_decision_logs(bid)
    assert any(l["action"] == "overridden" for l in logs)


def test_employee_cannot_confirm_or_start_trips():
    """
    Prove:
    - Non-driver (employee) cannot confirm, start, or end a trip via the state machine.
    - Raises ForbiddenTransitionError.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=18)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Airport",
        "passengers": 2,
        "reason": "Test",
        "status": "DRIVER_PENDING",
    })
    bid = b["id"]

    employee_actor = {"id": EMP_1_ID, "role": "employee"}

    with pytest.raises(ForbiddenTransitionError):
        transition(bid, "CONFIRMED", employee_actor)

    # Now let driver confirm
    transition(bid, "CONFIRMED", {"id": DRV_1_PROFILE_ID, "role": "driver", "driver_id": DRV_1_ID})

    # Employee tries to start trip
    with pytest.raises(ForbiddenTransitionError):
        transition(bid, "IN_PROGRESS", employee_actor)


def test_emergency_booking_skips_manager_queue_and_sets_2min_window(client):
    """
    Prove:
    - Emergency booking request skips manager queue and automatically advances to DRIVER_PENDING.
    - respond_by is set with respond_window_emergency_min (2 minutes).
    """
    emp_token = create_test_token(EMP_1_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    end_dt = start_dt + timedelta(hours=2)

    payload = {
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "passengers": 3,
        "destination": "Hospital Emergency Wing",
        "reason": "Medical Emergency",
        "type": "emergency",
        "priority": "emergency",
    }

    res = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res.status_code == 201, res.get_data(as_text=True)
    data = res.get_json()
    assert data["auto_approved"] is True
    booking = data["booking"]
    assert booking["status"] == "DRIVER_PENDING"
    assert booking["respond_by"] is not None

    # Check that respond_by is within ~2 minutes
    now_utc = datetime.now(timezone.utc)
    resp_dt = datetime.fromisoformat(booking["respond_by"])
    diff_seconds = (resp_dt - now_utc).total_seconds()
    assert 60 <= diff_seconds <= 180  # ~120s (2 min)


def test_idempotency_guard_blocks_duplicate_requests_even_when_auto_approved(client):
    """
    Prove:
    - Rapid duplicate submission is blocked with 409 DUPLICATE_REQUEST
      even when the first request was auto-approved to DRIVER_PENDING.
    """
    emp_token = create_test_token(EMP_1_ID)

    # 10:00 AM - 12:00 PM routine booking that auto-approves
    kolkata_target = (datetime.now(KOLKATA_TZ) + timedelta(days=20)).replace(hour=10, minute=0, second=0, microsecond=0)
    start_utc = kolkata_target.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(hours=2)

    payload = {
        "start_time": start_utc.isoformat(),
        "end_time": end_utc.isoformat(),
        "passengers": 2,
        "destination": "Tech Park",
        "reason": "Sync",
        "type": "scheduled",
        "priority": "normal",
    }

    # First submission succeeds and auto-approves
    res1 = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res1.status_code == 201
    assert res1.get_json()["booking"]["status"] == "DRIVER_PENDING"

    # Immediate second submission within 30s is rejected by idempotency guard
    res2 = client.post("/api/bookings", json=payload, headers=auth_header(emp_token))
    assert res2.status_code == 409
    assert res2.get_json()["error"]["code"] == "DUPLICATE_REQUEST"


def test_initial_booking_transitions_via_state_machine():
    """
    Prove:
    - transition(None, 'PENDING', ...) creates booking, soft-holds slot, notifies manager, and logs decision_log.
    - transition(None, 'WAITLISTED', ...) creates booking in WAITLISTED status and notifies employee.
    """
    start_dt = datetime.now(timezone.utc) + timedelta(days=21)
    end_dt = start_dt + timedelta(hours=2)

    booking_data = {
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "blocked_until": end_dt + timedelta(minutes=15),
        "destination": "Conference Hall",
        "passengers": 3,
        "reason": "Keynote",
        "type": "scheduled",
        "priority": "normal",
        "decision_reason": "Top scored vehicle and driver",
    }

    actor = {"id": EMP_1_ID, "role": "employee"}
    created = transition(None, "PENDING", actor, note="Top scored allocation", extra_data=booking_data)
    assert created["id"] is not None
    assert created["status"] == "PENDING"

    # Verify decision_log
    logs = get_decision_logs(created["id"])
    assert any(l["action"] == "requested" for l in logs)

    # Verify waitlisted creation
    wait_data = {
        "employee_id": EMP_2_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "blocked_until": end_dt + timedelta(minutes=15),
        "destination": "Field Office",
        "passengers": 4,
        "reason": "Inspection",
        "type": "scheduled",
        "priority": "normal",
        "failure_reason": "ALL_VEHICLES_BUSY",
    }
    wait_created = transition(None, "WAITLISTED", {"id": "engine", "role": "system"}, note="Capacity full", extra_data=wait_data)
    assert wait_created["status"] == "WAITLISTED"
    wait_logs = get_decision_logs(wait_created["id"])
    assert any(l["action"] == "waitlisted" for l in wait_logs)


def test_waitlist_and_choose_alternative_api_endpoints(client):
    """
    Prove:
    - POST /api/bookings/<id>/waitlist transitions bumped booking to WAITLISTED.
    - POST /api/bookings/<id>/choose-alternative transitions bumped booking to PENDING with alternative slot.
    """
    emp_token = create_test_token(EMP_1_ID)
    start_dt = datetime.now(timezone.utc) + timedelta(days=22)
    end_dt = start_dt + timedelta(hours=2)

    b = create_booking({
        "employee_id": EMP_1_ID,
        "vehicle_id": VEH_1_ID,
        "driver_id": DRV_1_ID,
        "start_time": start_dt,
        "end_time": end_dt,
        "destination": "Test",
        "passengers": 2,
        "reason": "Test",
        "status": "BUMPED",
        "was_bumped": True,
    })
    bid = b["id"]

    # 1. Join waitlist
    res_wait = client.post(f"/api/bookings/{bid}/waitlist", headers=auth_header(emp_token))
    assert res_wait.status_code == 200
    assert res_wait.get_json()["status"] == "WAITLISTED"
    assert res_wait.get_json()["booking"]["was_bumped"] is True

    # 2. Choose alternative slot
    alt_start = start_dt + timedelta(days=1)
    alt_end = alt_start + timedelta(hours=2)
    res_alt = client.post(
        f"/api/bookings/{bid}/choose-alternative",
        json={
            "start_time": alt_start.isoformat(),
            "end_time": alt_end.isoformat(),
            "vehicle_id": VEH_3_ID,
            "driver_id": DRV_2_ID,
            "note": "Selected alternative day",
        },
        headers=auth_header(emp_token),
    )
    assert res_alt.status_code == 200
    alt_booking = res_alt.get_json()["booking"]
    assert alt_booking["status"] == "PENDING"
    assert alt_booking["vehicle_id"] == VEH_3_ID
    assert alt_booking["driver_id"] == DRV_2_ID
    assert alt_booking["was_bumped"] is True

