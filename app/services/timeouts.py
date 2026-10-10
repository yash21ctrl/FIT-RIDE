"""Driver response timeout background service (Team KNIGHT | PS 40).

Monitors DRIVER_PENDING bookings. When respond_by expires:
1. Records a 'timeout' entry in driver_responses.
2. Re-runs allocate() excluding the timed-out driver (and any prior rejectors).
3. If an eligible driver is found: sets DRIVER_PENDING with the new driver and fresh countdown.
4. If no driver is found: executes Failure Ladder Step 5 (escalates to manager in status PENDING).
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from app.config import get_app_config
from app.db import (
    query_bookings,
    get_booking_by_id,
    update_booking,
    create_driver_response,
    get_driver_responses,
    create_decision_log,
    get_driver_by_id,
    get_all_profiles,
    _to_utc_dt,
)
from app.engine.allocate import allocate, BookingRequest
from app.services.notifications import notify

logger = logging.getLogger(__name__)
_scheduler_instance = None


def check_driver_timeouts() -> List[Dict[str, Any]]:
    """
    Core timeout evaluation function.
    Can be run by APScheduler job or invoked directly in test suites.
    """
    now_utc = datetime.now(timezone.utc)
    expired_bookings = []

    pending_bookings = query_bookings(active_only=False, status="DRIVER_PENDING")
    for b in pending_bookings:
        raw_respond_by = b.get("respond_by")
        if not raw_respond_by:
            continue

        respond_by_dt = _to_utc_dt(raw_respond_by)
        if respond_by_dt <= now_utc:
            expired_bookings.append(b)

    reassigned_results = []

    for b in expired_bookings:
        bid = b["id"]
        timed_out_driver_id = b.get("driver_id")

        # 1. Record timeout row in driver_responses
        if timed_out_driver_id:
            create_driver_response({
                "booking_id": bid,
                "driver_id": timed_out_driver_id,
                "response": "timeout",
                "reject_reason": None,
            })

        # 2. Collect all previously rejected or timed out drivers for this booking
        past_responses = get_driver_responses(booking_id=bid)
        excluded_driver_ids = tuple(
            r["driver_id"] for r in past_responses if r.get("driver_id")
        )

        # 3. Re-run deterministic allocation
        req = BookingRequest(
            start=b["start_time"],
            end=b["end_time"],
            passengers=b["passengers"],
            type=b.get("type", "scheduled"),
            priority=b.get("priority", "normal"),
            dest_lat=b.get("dest_lat"),
            dest_lng=b.get("dest_lng"),
            employee_id=b["employee_id"],
        )
        res = allocate(req, exclude_driver_ids=excluded_driver_ids, exclude_booking_id=bid)

        config = get_app_config()
        is_emergency = b.get("type") == "emergency" or b.get("priority") == "emergency"
        win_min = int(config.get("respond_window_emergency_min", 2)) if is_emergency else int(config.get("respond_window_scheduled_min", 30))
        new_respond_by = now_utc + timedelta(minutes=win_min)

        if res.ok and res.options:
            # Reassignment success!
            top = res.options[0]
            new_driver_id = top.driver_id
            new_vehicle_id = top.vehicle_id or b.get("vehicle_id")

            updated = update_booking(bid, {
                "driver_id": new_driver_id,
                "vehicle_id": new_vehicle_id,
                "status": "DRIVER_PENDING",
                "respond_by": new_respond_by,
                "decision_reason": f"Driver timeout: Reassigned from prior driver to {top.reason}",
            })

            create_decision_log(
                booking_id=bid,
                actor_id=None,
                action="timeout_reassigned",
                note=f"Driver {timed_out_driver_id} timed out. Automatically reassigned to {new_driver_id}.",
            )

            # Notify new driver
            new_drv = get_driver_by_id(new_driver_id)
            if new_drv and new_drv.get("profile_id"):
                notify(
                    new_drv["profile_id"],
                    f"New Trip Dispatch: {b.get('destination')} ({b.get('passengers')} pax) - Response required",
                    booking_id=bid,
                )

            # Notify employee of driver reassignment
            notify(
                b["employee_id"],
                f"Your driver for {b.get('destination')} has been reassigned to {new_drv.get('name') if new_drv else 'a new driver'}.",
                booking_id=bid,
            )

            reassigned_results.append({
                "booking_id": bid,
                "action": "reassigned",
                "new_driver_id": new_driver_id,
                "booking": updated,
            })
        else:
            # Failure Ladder Step 5: Escalate to manager
            updated = update_booking(bid, {
                "driver_id": None,
                "status": "PENDING",
                "failure_reason": "NO_ELIGIBLE_DRIVER",
                "decision_reason": f"Driver {timed_out_driver_id} timed out. No remaining eligible drivers in fleet; escalated to manager.",
            })

            create_decision_log(
                booking_id=bid,
                actor_id=None,
                action="timeout_escalated",
                note=f"Driver {timed_out_driver_id} timed out and no substitute drivers available. Escalated to manager queue.",
            )

            # Notify managers
            all_profiles = get_all_profiles()
            for prof in all_profiles:
                if prof.get("role") == "manager":
                    notify(
                        prof["id"],
                        f"ESCALATION ALERT: Trip {b.get('destination')} has no eligible drivers following timeout. Manual override required.",
                        booking_id=bid,
                    )

            # Notify employee
            notify(
                b["employee_id"],
                f"Your booking for {b.get('destination')} is undergoing manager escalation due to driver availability.",
                booking_id=bid,
            )

            reassigned_results.append({
                "booking_id": bid,
                "action": "escalated",
                "booking": updated,
            })

    return reassigned_results


def init_timeout_scheduler(app):
    """
    Initializes APScheduler background daemon safely.
    Guards against running twice in Flask debug mode or test runners.
    """
    global _scheduler_instance

    if app.config.get("TESTING"):
        return None

    if _scheduler_instance is not None:
        return _scheduler_instance

    # Guard against Werkzeug dual-process spawn in debug mode
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return None

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            func=check_driver_timeouts,
            trigger="interval",
            seconds=30,
            id="driver_timeout_checker",
            replace_existing=True,
        )
        scheduler.start()
        _scheduler_instance = scheduler
        logger.info("APScheduler driver timeout job started (every 30s).")
        return scheduler
    except Exception as exc:
        logger.warning(f"Could not initialize APScheduler: {exc}")
        return None
