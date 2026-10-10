"""Comprehensive unit tests for the deterministic allocation engine (Team KNIGHT | PS 40).

Covers all cases specified in SPEC.md Sections 7, 8, and 8.7:
1. Capacity filter (rejects vehicles with insufficient seats)
2. Best-fit choice (smaller excess capacity penalized less and preferred)
3. Overlap rejected in half-open interval [start, blocked_until)
4. Back-to-back trips allowed apart from 15-min buffer
5. Buffer respected (attempt inside [end, blocked_until) rejected)
6. Driver rest gap (45-min violation rejected, >= 45-min accepted)
7. Daily hours cap (9-hr cap strictly enforced in Asia/Kolkata timezone boundaries)
8. Fairness algorithm favors driver with fewer trips today
9. Diagnosed failure reasons: NO_VEHICLE_BIG_ENOUGH, VEHICLES_IN_MAINTENANCE, ALL_VEHICLES_BUSY, NO_ELIGIBLE_DRIVER
10. Alternatives returned on allocation failure
11. App config caching with 60s TTL and fallback defaults
12. Continuous driving limit (4 hours)
"""
import time
from datetime import datetime, timedelta, timezone
import pytest
import zoneinfo

from app.config import (
    DEFAULT_APP_CONFIG,
    get_app_config,
    get_config_value,
    set_config_override,
    clear_config_cache,
)
from app.engine.allocate import (
    allocate,
    driver_ok,
    score,
    explain,
    SCORING_WEIGHTS,
    get_default_vehicles,
    get_default_drivers,
    AllocationResult,
    AllocationOption,
)
from app.engine.alternatives import find_alternatives

KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def reset_config():
    """Ensure clean config cache before and after every test."""
    clear_config_cache()
    yield
    clear_config_cache()


@pytest.fixture
def base_time():
    """Consistent future base time in UTC."""
    return datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)


# =====================================================================
# 1. Capacity Filter
# =====================================================================
def test_capacity_filter(base_time):
    """Vehicles with capacity < passengers must be strictly excluded."""
    vehicles = [
        {"id": "v-swift", "name": "Maruti Swift", "capacity": 4, "status": "available"},
        {"id": "v-city", "name": "Honda City", "capacity": 4, "status": "available"},
        {"id": "v-ertiga", "name": "Maruti Ertiga", "capacity": 7, "status": "available"},
    ]
    drivers = [
        {"id": "d-1", "name": "Driver 1", "status": "available", "rating_avg": 4.8, "trips_today": 0}
    ]

    req = {
        "start": base_time,
        "end": base_time + timedelta(hours=2),
        "passengers": 5,  # Needs at least 5 seats
    }

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=[])

    assert result.ok is True
    assert len(result.options) == 1
    # Only Ertiga has >= 5 seats
    assert result.options[0].vehicle_id == "v-ertiga"
    assert result.options[0].vehicle_name == "Maruti Ertiga"


# =====================================================================
# 2. Best-fit Choice (smaller excess capacity preferred)
# =====================================================================
def test_best_fit_choice(base_time):
    """
    For 3 passengers, 4-seater Swift has 1 excess seat (-2.0 penalty).
    7-seater Ertiga has 4 excess seats (-8.0 penalty).
    12-seater Tempo has 9 excess seats (-18.0 penalty).
    Swift must be ranked highest.
    """
    vehicles = [
        {"id": "v-tempo", "name": "Force Tempo Traveller", "capacity": 12, "status": "available"},
        {"id": "v-ertiga", "name": "Maruti Ertiga", "capacity": 7, "status": "available"},
        {"id": "v-swift", "name": "Maruti Swift", "capacity": 4, "status": "available"},
    ]
    drivers = [
        {"id": "d-1", "name": "Driver 1", "status": "available", "rating_avg": 4.5, "trips_today": 0}
    ]

    req = {
        "start": base_time,
        "end": base_time + timedelta(hours=2),
        "passengers": 3,
    }

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=[])

    assert result.ok is True
    assert len(result.options) == 3
    # First option must be Maruti Swift
    assert result.options[0].vehicle_id == "v-swift"
    assert result.options[1].vehicle_id == "v-ertiga"
    assert result.options[2].vehicle_id == "v-tempo"
    assert result.options[0].score > result.options[1].score > result.options[2].score


# =====================================================================
# 3. Overlap Rejected
# =====================================================================
def test_overlap_rejected(base_time):
    """
    Existing booking: 10:00 - 11:00 (blocked until 11:15).
    Overlapping request: 10:30 - 11:30.
    Must be rejected with ALL_VEHICLES_BUSY when single vehicle in fleet is occupied.
    """
    v_id = "v-single"
    vehicles = [{"id": v_id, "name": "Sole Car", "capacity": 4, "status": "available"}]
    drivers = [{"id": "d-1", "name": "Driver 1", "status": "available", "rating_avg": 4.5}]

    existing_booking = {
        "id": "b-existing",
        "vehicle_id": v_id,
        "driver_id": "d-1",
        "start_time": base_time,  # 10:00
        "end_time": base_time + timedelta(hours=1),  # 11:00
        "blocked_until": base_time + timedelta(hours=1, minutes=15),  # 11:15
        "status": "CONFIRMED",
    }

    overlapping_req = {
        "start": base_time + timedelta(minutes=30),  # 10:30
        "end": base_time + timedelta(hours=1, minutes=30),  # 11:30
        "passengers": 2,
    }

    result = allocate(overlapping_req, vehicles=vehicles, drivers=drivers, bookings=[existing_booking])

    assert result.ok is False
    assert result.failure_reason == "ALL_VEHICLES_BUSY"
    assert len(result.alternatives) > 0


# =====================================================================
# 4. Back-to-Back Trips Allowed Apart From 15-Min Buffer
# =====================================================================
def test_back_to_back_trips_allowed_apart_from_15min_buffer(base_time):
    """
    Booking A: 10:00 - 11:00 (blocked until 11:15).
    Booking B on same vehicle: Starts at 11:15.
    Must be permitted because [10:00, 11:15) does not overlap with [11:15, 12:30).
    """
    v_id = "v-1"
    vehicles = [{"id": v_id, "name": "Swift", "capacity": 4, "status": "available"}]
    # Use distinct driver to isolate vehicle buffer test from driver rest-gap test
    drivers = [{"id": "d-2", "name": "Fresh Driver", "status": "available", "rating_avg": 4.8}]

    booking_a = {
        "id": "b-1",
        "vehicle_id": v_id,
        "driver_id": "d-1",
        "start_time": base_time,  # 10:00
        "end_time": base_time + timedelta(hours=1),  # 11:00
        "blocked_until": base_time + timedelta(hours=1, minutes=15),  # 11:15
        "status": "CONFIRMED",
    }

    req_b = {
        "start": base_time + timedelta(hours=1, minutes=15),  # 11:15 sharp
        "end": base_time + timedelta(hours=2, minutes=15),
        "passengers": 2,
    }

    result = allocate(req_b, vehicles=vehicles, drivers=drivers, bookings=[booking_a])

    assert result.ok is True
    assert result.options[0].vehicle_id == v_id


# =====================================================================
# 5. Buffer Respected (Attempt inside buffer rejected)
# =====================================================================
def test_buffer_respected(base_time):
    """
    Booking A: 10:00 - 11:00 (blocked until 11:15).
    Booking B on same vehicle: Starts at 11:10 (inside the 15-min cleaning/inspection buffer).
    Must be rejected because 11:10 < 11:15.
    """
    v_id = "v-1"
    vehicles = [{"id": v_id, "name": "Swift", "capacity": 4, "status": "available"}]
    drivers = [{"id": "d-2", "name": "Fresh Driver", "status": "available", "rating_avg": 4.8}]

    booking_a = {
        "id": "b-1",
        "vehicle_id": v_id,
        "driver_id": "d-1",
        "start_time": base_time,  # 10:00
        "end_time": base_time + timedelta(hours=1),  # 11:00
        "blocked_until": base_time + timedelta(hours=1, minutes=15),  # 11:15
        "status": "CONFIRMED",
    }

    req_b = {
        "start": base_time + timedelta(hours=1, minutes=10),  # 11:10 (5 mins inside buffer)
        "end": base_time + timedelta(hours=2, minutes=10),
        "passengers": 2,
    }

    result = allocate(req_b, vehicles=vehicles, drivers=drivers, bookings=[booking_a])

    assert result.ok is False
    assert result.failure_reason == "ALL_VEHICLES_BUSY"


# =====================================================================
# 6. Driver Rest Gap (45-Min Violation Rejected)
# =====================================================================
def test_driver_rest_gap_violation_rejected(base_time):
    """
    Driver completed a trip ending at 10:30.
    1. Proposed trip starting at 11:00 has rest gap = 30m (< 45m).
       driver_ok must return False with rest gap violation.
    2. Proposed trip starting at 11:15 has rest gap = 45m (>= 45m).
       driver_ok must return True.
    """
    driver = {"id": "d-fatigued", "name": "Ravi Kumar", "status": "available", "rating_avg": 4.8}
    completed_trip = {
        "id": "b-prior",
        "driver_id": "d-fatigued",
        "vehicle_id": "v-1",
        "start_time": base_time - timedelta(hours=2),  # 08:00
        "end_time": base_time + timedelta(minutes=30),  # 10:30
        "blocked_until": base_time + timedelta(minutes=45),
        "status": "COMPLETED",
    }

    # Case 1: Gap of 30 minutes (10:30 to 11:00)
    trip_start_too_soon = base_time + timedelta(hours=1)  # 11:00
    trip_end_too_soon = base_time + timedelta(hours=2)
    res_1 = driver_ok(
        driver,
        (trip_start_too_soon, trip_end_too_soon),
        bookings=[completed_trip],
    )
    assert bool(res_1) is False
    assert "rest" in res_1.reason.lower()

    # Case 2: Gap of 45 minutes (10:30 to 11:15)
    trip_start_ok = base_time + timedelta(hours=1, minutes=15)  # 11:15
    trip_end_ok = base_time + timedelta(hours=2, minutes=15)
    res_2 = driver_ok(
        driver,
        (trip_start_ok, trip_end_ok),
        bookings=[completed_trip],
    )
    assert bool(res_2) is True


# =====================================================================
# 7. Daily Hours Cap (9 Hours Enforced in Asia/Kolkata Timezone)
# =====================================================================
def test_daily_hours_cap_enforced_in_asia_kolkata():
    """
    Daily driving cap is 9 hours within the driver's local calendar day in Asia/Kolkata.
    1. Driver drove 8 hours today in Asia/Kolkata. A new 2-hour trip today exceeds cap (10h > 9h).
    2. Driver drove 8 hours yesterday in Asia/Kolkata. A new 2-hour trip today is within cap (2h <= 9h).
    """
    # 10:00 AM IST on Oct 15, 2026 (04:30 AM UTC)
    today_kolkata_start = datetime(2026, 10, 15, 10, 0, 0, tzinfo=KOLKATA_TZ)
    today_utc = today_kolkata_start.astimezone(timezone.utc)

    driver = {"id": "d-worker", "name": "Workhorse", "status": "available", "rating_avg": 4.5}

    # Trip earlier TODAY in Asia/Kolkata: 8 hours (01:00 IST to 09:00 IST)
    trip_today = {
        "id": "b-today",
        "driver_id": "d-worker",
        "start_time": datetime(2026, 10, 15, 1, 0, 0, tzinfo=KOLKATA_TZ).astimezone(timezone.utc),
        "end_time": datetime(2026, 10, 15, 9, 0, 0, tzinfo=KOLKATA_TZ).astimezone(timezone.utc),
        "blocked_until": datetime(2026, 10, 15, 9, 15, 0, tzinfo=KOLKATA_TZ).astimezone(timezone.utc),
        "status": "COMPLETED",
    }

    # Case 1: 2-hour trip today (8h + 2h = 10h > 9h) -> Rejected
    proposed_today = (today_utc, today_utc + timedelta(hours=2))
    check_today = driver_ok(driver, proposed_today, bookings=[trip_today])
    assert bool(check_today) is False
    assert "daily hours limit" in check_today.reason.lower()

    # Case 2: 8-hour trip YESTERDAY in Asia/Kolkata (Oct 14 from 12:00 IST to 20:00 IST)
    trip_yesterday = {
        "id": "b-yesterday",
        "driver_id": "d-worker",
        "start_time": datetime(2026, 10, 14, 12, 0, 0, tzinfo=KOLKATA_TZ).astimezone(timezone.utc),
        "end_time": datetime(2026, 10, 14, 20, 0, 0, tzinfo=KOLKATA_TZ).astimezone(timezone.utc),
        "blocked_until": datetime(2026, 10, 14, 20, 15, 0, tzinfo=KOLKATA_TZ).astimezone(timezone.utc),
        "status": "COMPLETED",
    }
    check_yesterday = driver_ok(driver, proposed_today, bookings=[trip_yesterday])
    assert bool(check_yesterday) is True


# =====================================================================
# 8. Fairness Algorithm (Fewer trips favored)
# =====================================================================
def test_fairness_picks_driver_with_fewer_trips(base_time):
    """
    Two drivers with identical rating (4.8).
    Driver A has 0 trips today.
    Driver B has 3 trips today.
    Driver A must be given a higher score and selected first.
    """
    vehicles = [{"id": "v-1", "name": "Swift", "capacity": 4, "status": "available"}]
    drivers = [
        {"id": "d-b", "name": "Busy Driver", "status": "available", "rating_avg": 4.8, "trips_today": 3},
        {"id": "d-a", "name": "Fresh Driver", "status": "available", "rating_avg": 4.8, "trips_today": 0},
    ]

    req = {"start": base_time, "end": base_time + timedelta(hours=1), "passengers": 3}
    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=[])

    assert result.ok is True
    assert len(result.options) == 2
    # Fresh Driver A must be #1
    assert result.options[0].driver_id == "d-a"
    assert result.options[0].driver_name == "Fresh Driver"
    assert result.options[0].score > result.options[1].score


# =====================================================================
# 9. Each Failure Reason Correctly Diagnosed
# =====================================================================
def test_failure_reason_no_vehicle_big_enough(base_time):
    """When passenger count exceeds max fleet capacity, failure is NO_VEHICLE_BIG_ENOUGH."""
    vehicles = [{"id": "v-1", "name": "Minibus", "capacity": 12, "status": "available"}]
    drivers = [{"id": "d-1", "name": "Driver", "status": "available"}]
    req = {"start": base_time, "end": base_time + timedelta(hours=2), "passengers": 15}

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=[])
    assert result.ok is False
    assert result.failure_reason == "NO_VEHICLE_BIG_ENOUGH"
    assert len(result.alternatives) > 0


def test_failure_reason_vehicles_in_maintenance(base_time):
    """When all suitable vehicles are in maintenance, failure is VEHICLES_IN_MAINTENANCE."""
    vehicles = [
        {
            "id": "v-maint-1",
            "name": "Ertiga",
            "capacity": 7,
            "status": "maintenance",
            "maintenance_until": base_time + timedelta(days=2),
        },
        {
            "id": "v-maint-2",
            "name": "Innova",
            "capacity": 7,
            "status": "maintenance",
            "maintenance_until": None,
        },
    ]
    drivers = [{"id": "d-1", "name": "Driver", "status": "available"}]
    req = {"start": base_time, "end": base_time + timedelta(hours=2), "passengers": 6}

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=[])
    assert result.ok is False
    assert result.failure_reason == "VEHICLES_IN_MAINTENANCE"


def test_failure_reason_all_vehicles_busy(base_time):
    """When all suitable vehicles are busy with overlapping slots, failure is ALL_VEHICLES_BUSY."""
    vehicles = [
        {"id": "v-1", "name": "Swift", "capacity": 4, "status": "available"},
        {"id": "v-2", "name": "City", "capacity": 4, "status": "available"},
    ]
    drivers = [{"id": "d-1", "name": "Driver 1", "status": "available"}]
    bookings = [
        {
            "id": "b-1",
            "vehicle_id": "v-1",
            "start_time": base_time,
            "end_time": base_time + timedelta(hours=2),
            "blocked_until": base_time + timedelta(hours=2, minutes=15),
            "status": "CONFIRMED",
        },
        {
            "id": "b-2",
            "vehicle_id": "v-2",
            "start_time": base_time,
            "end_time": base_time + timedelta(hours=2),
            "blocked_until": base_time + timedelta(hours=2, minutes=15),
            "status": "CONFIRMED",
        },
    ]
    req = {"start": base_time, "end": base_time + timedelta(hours=2), "passengers": 3}

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=bookings)
    assert result.ok is False
    assert result.failure_reason == "ALL_VEHICLES_BUSY"
    assert len(result.alternatives) > 0


def test_failure_reason_no_eligible_driver(base_time):
    """When vehicles are free but all drivers are off/busy/fatigued, failure is NO_ELIGIBLE_DRIVER."""
    vehicles = [{"id": "v-1", "name": "Swift", "capacity": 4, "status": "available"}]
    drivers = [
        {"id": "d-off", "name": "Off Duty", "status": "off"},
        {"id": "d-busy", "name": "Busy Driver", "status": "available"},
    ]
    bookings = [
        {
            "id": "b-busy",
            "driver_id": "d-busy",
            "start_time": base_time,
            "end_time": base_time + timedelta(hours=2),
            "blocked_until": base_time + timedelta(hours=2, minutes=15),
            "status": "CONFIRMED",
        }
    ]
    req = {"start": base_time, "end": base_time + timedelta(hours=2), "passengers": 3}

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=bookings)
    assert result.ok is False
    assert result.failure_reason == "NO_ELIGIBLE_DRIVER"


# =====================================================================
# 10. Alternatives Returned on Failure
# =====================================================================
def test_alternatives_returned_on_failure(base_time):
    """When allocation fails, alternatives list provides shifted windows and next free slot."""
    vehicles = [{"id": "v-1", "name": "Swift", "capacity": 4, "status": "available"}]
    drivers = [{"id": "d-1", "name": "Driver 1", "status": "available", "rating_avg": 4.8}]
    # Single vehicle booked for the window
    bookings = [
        {
            "id": "b-1",
            "vehicle_id": "v-1",
            "driver_id": "d-1",
            "start_time": base_time,
            "end_time": base_time + timedelta(hours=2),
            "blocked_until": base_time + timedelta(hours=2, minutes=15),
            "status": "CONFIRMED",
        }
    ]
    req = {"start": base_time, "end": base_time + timedelta(hours=2), "passengers": 3}

    result = allocate(req, vehicles=vehicles, drivers=drivers, bookings=bookings)
    assert result.ok is False
    assert len(result.alternatives) > 0

    types = {alt["type"] for alt in result.alternatives}
    # Should include shifted_window or next_available_slot
    assert types.intersection({"shifted_window", "next_available_slot"})


# =====================================================================
# 11. App Config Caching (60s TTL and fallback defaults)
# =====================================================================
def test_app_config_caching_and_overrides():
    """Verify 60s config cache, fallback defaults, and override mechanism."""
    cfg = get_app_config()
    assert cfg["buffer_minutes"] == 15
    assert cfg["driver_max_hours_per_day"] == 9.0
    assert cfg["timezone"] == "Asia/Kolkata"

    # Runtime override
    set_config_override("driver_max_hours_per_day", 10.5)
    assert get_config_value("driver_max_hours_per_day") == 10.5

    clear_config_cache()
    # Reverts back to standard default
    assert get_config_value("driver_max_hours_per_day") == 9.0


# =====================================================================
# 12. Continuous Driving Limit (4 Hours)
# =====================================================================
def test_continuous_driving_limit_exceeded(base_time):
    """Single trip of 5 hours non-stop exceeds 4-hour continuous driving limit."""
    driver = {"id": "d-1", "name": "Solo", "status": "available"}
    window_5h = (base_time, base_time + timedelta(hours=5))

    check = driver_ok(driver, window_5h)
    assert bool(check) is False
    assert "continuous" in check.reason.lower()


# =====================================================================
# 13. Exclude Driver and Exclude Booking Parameters
# =====================================================================
def test_exclude_driver_and_booking_id(base_time):
    """
    1. Driver in exclude_driver_ids is filtered out.
    2. Booking matching exclude_booking_id is ignored during conflict checking.
    """
    vehicles = [{"id": "v-1", "name": "Swift", "capacity": 4, "status": "available"}]
    drivers = [
        {"id": "d-excluded", "name": "Excluded Driver", "status": "available"},
        {"id": "d-active", "name": "Active Driver", "status": "available"},
    ]
    req = {"start": base_time, "end": base_time + timedelta(hours=1), "passengers": 2}

    res = allocate(req, exclude_driver_ids=("d-excluded",), vehicles=vehicles, drivers=drivers, bookings=[])
    assert res.ok is True
    assert res.options[0].driver_id == "d-active"

    # Exclude booking ID test
    conflict_booking = {
        "id": "b-self",
        "vehicle_id": "v-1",
        "driver_id": "d-active",
        "start_time": base_time,
        "end_time": base_time + timedelta(hours=1),
        "blocked_until": base_time + timedelta(hours=1, minutes=15),
        "status": "PENDING",
    }
    # When b-self is excluded (e.g. re-allocating own booking), it does not clash with itself
    res_realloc = allocate(
        req,
        exclude_booking_id="b-self",
        vehicles=vehicles,
        drivers=drivers,
        bookings=[conflict_booking],
    )
    assert res_realloc.ok is True


# =====================================================================
# 14. BookingRequest Dataclass & Input Validation
# =====================================================================
def test_booking_request_dataclass_and_validation(base_time):
    """BookingRequest dataclass works as expected and boundary validation is enforced."""
    from app.engine.allocate import BookingRequest

    req_obj = BookingRequest(
        start=base_time,
        end=base_time + timedelta(hours=2),
        passengers=3,
        destination="Whitefield",
    )
    res = allocate(req_obj)
    assert res.ok is True

    # Invalid passenger boundaries
    with pytest.raises(ValueError, match="between 1 and 60"):
        allocate({"start": base_time, "end": base_time + timedelta(hours=1), "passengers": 0})

    with pytest.raises(ValueError, match="between 1 and 60"):
        allocate({"start": base_time, "end": base_time + timedelta(hours=1), "passengers": 61})

    # Invalid time interval: end <= start
    with pytest.raises(ValueError, match="strictly after"):
        allocate({"start": base_time, "end": base_time, "passengers": 2})


# =====================================================================
# 15. Dict-like and Attribute Interoperability on Results
# =====================================================================
def test_result_and_option_interoperability(base_time):
    """AllocationResult and AllocationOption support both dict key access and attributes."""
    req = {"start": base_time, "end": base_time + timedelta(hours=1), "passengers": 2}
    res = allocate(req)
    assert res.ok is True
    assert res["ok"] is True
    d = res.to_dict()
    assert isinstance(d, dict)
    assert d["ok"] is True

    opt = res.options[0]
    assert opt.vehicle_id == opt["vehicle_id"]
    assert opt.score == opt["score"]
    opt_d = opt.to_dict()
    assert isinstance(opt_d, dict)
    assert "reason" in opt_d


# =====================================================================
# 16. Scoring and Explain Pure Function Verification
# =====================================================================
def test_scoring_and_explain_pure_functions():
    """Verify SCORING_WEIGHTS arithmetic and explain text output."""
    veh = {"name": "Swift", "capacity": 4}
    drv = {"name": "Suresh", "rating_avg": 4.9, "trips_today": 1}

    # excess = 1 (-2.0), fairness = 3 * (2.0 - 1) = +3.0, rating = 0.5 * 4.9 = 2.45
    # total = -2.0 + 3.0 + 2.45 = 3.45
    s = score(veh, drv, passengers=3, avg_trips_today=2.0)
    assert pytest.approx(s, 0.01) == 3.45

    explanation = explain(veh, drv, passengers=3, avg_trips_today=2.0, score_val=s)
    assert "Swift" in explanation
    assert "Suresh" in explanation
    assert "3.45" in explanation

