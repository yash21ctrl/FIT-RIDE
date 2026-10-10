"""Tests for driver response timeouts and notifications (Phase 8)."""
import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.db import (
    reset_seed_data,
    create_booking,
    get_booking_by_id,
    get_driver_responses,
    get_decision_logs,
)
from app.services.timeouts import check_driver_timeouts
from app.services.notifications import notify, get_user_notifications

DRIVER_1_PROFILE_ID = "00000000-0000-0000-0004-000000000001"
DRIVER_1_ID = "00000000-0000-0000-0005-000000000001"
DRIVER_2_ID = "00000000-0000-0000-0005-000000000002"
EMP_1_PROFILE_ID = "00000000-0000-0000-0003-000000000001"
VEH_1_ID = "00000000-0000-0000-0001-000000000001"


@pytest.fixture
def app():
    reset_seed_data()
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_driver_timeout_automatically_reassigns_to_next_driver(app):
    """
    Test setting respond_by to the past and proving:
    1. A timeout response row is logged.
    2. The booking is reallocated to a different eligible driver.
    3. respond_by is reset to the future.
    """
    with app.app_context():
        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc + timedelta(days=2)
        end_dt = start_dt + timedelta(hours=2)
        past_respond_by = now_utc - timedelta(minutes=5)

        booking = create_booking({
            "employee_id": EMP_1_PROFILE_ID,
            "vehicle_id": VEH_1_ID,
            "driver_id": DRIVER_1_ID,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "blocked_until": (end_dt + timedelta(minutes=15)).isoformat(),
            "destination": "Whitefield Hub",
            "passengers": 3,
            "reason": "Technical Meeting",
            "type": "scheduled",
            "priority": "normal",
            "status": "DRIVER_PENDING",
            "respond_by": past_respond_by.isoformat(),
        })

        # Run timeout evaluation
        results = check_driver_timeouts()
        assert len(results) >= 1
        res = next((r for r in results if r["booking_id"] == booking["id"]), None)
        assert res is not None
        assert res["action"] == "reassigned"

        # Verify booking in DB
        b_after = get_booking_by_id(booking["id"])
        assert b_after["status"] == "DRIVER_PENDING"
        assert b_after["driver_id"] != DRIVER_1_ID
        from app.db import _to_utc_dt
        assert _to_utc_dt(b_after["respond_by"]) > now_utc

        # Verify timeout row in driver_responses
        responses = get_driver_responses(booking_id=booking["id"])
        timeout_entry = next((r for r in responses if r["response"] == "timeout"), None)
        assert timeout_entry is not None
        assert timeout_entry["driver_id"] == DRIVER_1_ID

        # Verify decision log audit trail
        dlog = get_decision_logs(booking_id=booking["id"])
        assert any(d["action"] == "timeout_reassigned" for d in dlog)


def test_driver_timeout_escalates_to_manager_when_no_driver_available(app):
    """
    Test that when all remaining drivers are excluded, timeout escalates to manager.
    """
    with app.app_context():
        from app.db import create_driver_response, get_all_drivers

        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc + timedelta(days=3)
        end_dt = start_dt + timedelta(hours=2)

        booking = create_booking({
            "employee_id": EMP_1_PROFILE_ID,
            "vehicle_id": VEH_1_ID,
            "driver_id": DRIVER_1_ID,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "blocked_until": (end_dt + timedelta(minutes=15)).isoformat(),
            "destination": "Airport Terminal",
            "passengers": 3,
            "reason": "Executive Transit",
            "type": "scheduled",
            "priority": "normal",
            "status": "DRIVER_PENDING",
            "respond_by": (now_utc - timedelta(minutes=2)).isoformat(),
        })

        # Simulate that all other drivers have already rejected this booking
        all_drvs = get_all_drivers()
        for d in all_drvs:
            if d["id"] != DRIVER_1_ID:
                create_driver_response({
                    "booking_id": booking["id"],
                    "driver_id": d["id"],
                    "response": "rejected",
                    "reject_reason": "tired",
                })

        # Now Driver 1 times out
        results = check_driver_timeouts()
        res = next((r for r in results if r["booking_id"] == booking["id"]), None)
        assert res is not None
        assert res["action"] == "escalated"

        b_after = get_booking_by_id(booking["id"])
        assert b_after["status"] == "PENDING"
        assert b_after["failure_reason"] == "NO_ELIGIBLE_DRIVER"


def test_notification_service_dispatches_in_app(app):
    """Test that notify() creates persistent in-app notifications."""
    with app.app_context():
        notif = notify(
            user_id=EMP_1_PROFILE_ID,
            message="Your booking has been approved by management.",
            booking_id="sample-booking-id",
        )
        assert notif["message"] == "Your booking has been approved by management."

        user_notifs = get_user_notifications(EMP_1_PROFILE_ID)
        assert any("approved by management" in n["message"] for n in user_notifs)
