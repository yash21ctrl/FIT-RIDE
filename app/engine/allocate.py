"""Core deterministic allocation engine, driver eligibility, scoring, and explanation.

Team KNIGHT | PS 40 | Fleet Operations System
Zero AI/ML: Pure deterministic rules engine with full auditability.
"""
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
import zoneinfo

from app.config import get_app_config
from app.db import query_vehicles, query_drivers, query_bookings

KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

# Section 8.2 Step 5: Scoring Weights
SCORING_WEIGHTS = {
    "capacity_penalty": -2.0,   # Best fit: smaller excess capacity preferred
    "fairness_multiplier": 3.0, # Fewer trips today favored: 3 * (avg_trips_today - driver.trips_today)
    "rating_multiplier": 0.5,   # Tie breaker: 0.5 * rating_avg
    "merge_bonus": 5.0          # Optional proximity trip-merge bonus
}

SLOT_HOLDING_STATUSES = ("PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED", "IN_PROGRESS")


class DriverCheckResult:
    """Helper wrapper for driver_ok returning bool and reason while supporting tuple unpacking."""
    def __init__(self, ok: bool, reason: str = ""):
        self.ok = bool(ok)
        self.reason = str(reason)

    def __bool__(self) -> bool:
        return self.ok

    def __iter__(self):
        return iter((self.ok, self.reason))

    def __getitem__(self, idx: int):
        return (self.ok, self.reason)[idx]

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return self.ok == other
        if isinstance(other, tuple) and len(other) == 2:
            return (self.ok, self.reason) == other
        if isinstance(other, DriverCheckResult):
            return self.ok == other.ok and self.reason == other.reason
        return False

    def __repr__(self) -> str:
        return f"DriverCheckResult(ok={self.ok}, reason={self.reason!r})"


@dataclass
class BookingRequest:
    start: Any
    end: Any
    passengers: int
    type: str = "scheduled"
    priority: str = "normal"
    destination: str = ""
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None
    employee_id: Optional[str] = None
    reason: str = ""


@dataclass
class AllocationOption:
    vehicle_id: str
    driver_id: str
    score: float
    reason: str
    skipped: List[str] = field(default_factory=list)
    vehicle_name: Optional[str] = None
    driver_name: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "score": round(self.score, 3),
            "reason": self.reason,
            "skipped": self.skipped,
            "vehicle_name": self.vehicle_name,
            "driver_name": self.driver_name,
        }


@dataclass
class AllocationResult:
    ok: bool
    options: List[AllocationOption]
    failure_reason: Optional[str] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "options": [opt.to_dict() for opt in self.options],
            "failure_reason": self.failure_reason,
            "alternatives": self.alternatives,
        }


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Helper to safely retrieve an attribute or dict key."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_dt(dt_val: Any) -> datetime:
    """Normalize timestamp value to timezone-aware UTC datetime."""
    if isinstance(dt_val, str):
        clean = dt_val.replace("Z", "+00:00")
        dt_val = datetime.fromisoformat(clean)
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=timezone.utc)
    return dt_val.astimezone(timezone.utc)


def get_default_vehicles() -> List[Dict[str, Any]]:
    """Default fleet vehicles matching 003_seed.sql."""
    return [
        {
            "id": "00000000-0000-0000-0001-000000000001",
            "name": "Maruti Swift",
            "type": "car",
            "capacity": 4,
            "status": "available",
            "maintenance_until": None,
            "odometer_km": 12500,
        },
        {
            "id": "00000000-0000-0000-0001-000000000002",
            "name": "Honda City",
            "type": "car",
            "capacity": 4,
            "status": "available",
            "maintenance_until": None,
            "odometer_km": 28400,
        },
        {
            "id": "00000000-0000-0000-0001-000000000003",
            "name": "Maruti Ertiga",
            "type": "van",
            "capacity": 7,
            "status": "available",
            "maintenance_until": None,
            "odometer_km": 45200,
        },
        {
            "id": "00000000-0000-0000-0001-000000000004",
            "name": "Toyota Innova Crysta",
            "type": "van",
            "capacity": 7,
            "status": "available",
            "maintenance_until": None,
            "odometer_km": 61000,
        },
        {
            "id": "00000000-0000-0000-0001-000000000005",
            "name": "Mahindra Bolero",
            "type": "van",
            "capacity": 7,
            "status": "available",
            "maintenance_until": None,
            "odometer_km": 78300,
        },
        {
            "id": "00000000-0000-0000-0001-000000000006",
            "name": "Force Tempo Traveller",
            "type": "minibus",
            "capacity": 12,
            "status": "available",
            "maintenance_until": None,
            "odometer_km": 94000,
        },
    ]


def get_default_drivers() -> List[Dict[str, Any]]:
    """Default drivers matching 003_seed.sql."""
    return [
        {
            "id": "00000000-0000-0000-0005-000000000001",
            "name": "Ravi Kumar",
            "status": "available",
            "rating_avg": 4.8,
            "license_no": "DL-KA-01-2019-001",
        },
        {
            "id": "00000000-0000-0000-0005-000000000002",
            "name": "Suresh Patil",
            "status": "available",
            "rating_avg": 4.9,
            "license_no": "DL-KA-01-2020-002",
        },
        {
            "id": "00000000-0000-0000-0005-000000000003",
            "name": "Amit Singh",
            "status": "available",
            "rating_avg": 4.7,
            "license_no": "DL-KA-01-2021-003",
        },
        {
            "id": "00000000-0000-0000-0005-000000000004",
            "name": "Priya Sharma",
            "status": "available",
            "rating_avg": 4.6,
            "license_no": "DL-KA-01-2022-004",
        },
        {
            "id": "00000000-0000-0000-0005-000000000005",
            "name": "Rajesh Verma",
            "status": "available",
            "rating_avg": 4.9,
            "license_no": "DL-KA-01-2023-005",
        },
    ]


def score(
    vehicle: Any,
    driver: Any,
    passengers: int,
    avg_trips_today: float = 0.0,
    merge_bonus: float = 0.0,
) -> float:
    """
    Deterministic scoring function from SPEC.md Section 8.2:
    score = -2 * (vehicle.capacity - passengers) + 3 * (avg_trips_today - driver.trips_today) + 0.5 * driver.rating_avg + merge_bonus
    """
    capacity = int(_get(vehicle, "capacity", 0))
    excess_capacity = max(0, capacity - passengers)

    trips_today = float(_get(driver, "trips_today", 0))
    rating_avg = float(_get(driver, "rating_avg", 0.0))

    val = (
        SCORING_WEIGHTS["capacity_penalty"] * excess_capacity
        + SCORING_WEIGHTS["fairness_multiplier"] * (avg_trips_today - trips_today)
        + SCORING_WEIGHTS["rating_multiplier"] * rating_avg
        + merge_bonus
    )
    return float(val)


def explain(
    vehicle: Any,
    driver: Any,
    passengers: int,
    avg_trips_today: float = 0.0,
    score_val: Optional[float] = None,
) -> str:
    """Generate human-readable justification for the candidate allocation."""
    v_name = _get(vehicle, "name", "Vehicle")
    v_cap = int(_get(vehicle, "capacity", 0))
    excess = max(0, v_cap - passengers)

    d_name = _get(driver, "name", "Driver")
    d_rating = float(_get(driver, "rating_avg", 0.0))
    d_trips = int(_get(driver, "trips_today", 0))

    if score_val is None:
        score_val = score(vehicle, driver, passengers, avg_trips_today)

    excess_str = "exact capacity fit" if excess == 0 else f"{excess} extra seat{'s' if excess > 1 else ''}"
    return (
        f"Selected {v_name} ({v_cap} seats, {excess_str}) with Driver {d_name} "
        f"(rating {d_rating:.1f}, {d_trips} trips today vs {avg_trips_today:.1f} fleet avg). "
        f"Total score: {score_val:.2f}."
    )


def driver_ok(
    driver: Any,
    window: Union[Tuple[datetime, datetime], List[datetime], Tuple[datetime, datetime, datetime]],
    bookings: Optional[List[Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    exclude_driver_ids: tuple = (),
    exclude_booking_id: Optional[str] = None,
    end_time: Optional[datetime] = None,
) -> DriverCheckResult:
    """
    Evaluates driver eligibility according to SPEC.md Section 8.2 Step 4:
    - Status is not 'off'
    - Driver not in exclude_driver_ids
    - No overlapping slot-holding booking in [start, blocked_until)
    - Hours driven in driver's local day (Asia/Kolkata) + this trip <= driver_max_hours_per_day (9h)
    - Rest gap since last trip end >= driver_min_rest_minutes (45m)
    - Continuous driving below driver_max_continuous_hours (4h)
    """
    if config is None:
        config = get_app_config()

    buffer_min = int(config.get("buffer_minutes", 15))
    buffer_delta = timedelta(minutes=buffer_min)

    # Parse window
    if len(window) == 3:
        start_utc, trip_end_utc, blocked_until_utc = (
            _to_dt(window[0]),
            _to_dt(window[1]),
            _to_dt(window[2]),
        )
    elif len(window) == 2:
        start_utc = _to_dt(window[0])
        w1 = _to_dt(window[1])
        if end_time is not None:
            trip_end_utc = _to_dt(end_time)
            blocked_until_utc = w1
        else:
            # Check if w1 is blocked_until or end_time
            if w1 > start_utc + buffer_delta:
                # w1 is likely blocked_until
                blocked_until_utc = w1
                trip_end_utc = w1 - buffer_delta
            else:
                trip_end_utc = w1
                blocked_until_utc = w1 + buffer_delta
    else:
        return DriverCheckResult(False, "Invalid window specification")

    this_trip_hours = max(0.0, (trip_end_utc - start_utc).total_seconds() / 3600.0)

    # 1. Driver status check
    d_status = str(_get(driver, "status", "available")).lower()
    if d_status == "off":
        return DriverCheckResult(False, "Driver status is 'off'")

    # 2. Exclude driver IDs check
    d_id = str(_get(driver, "id", ""))
    if d_id in [str(x) for x in exclude_driver_ids]:
        return DriverCheckResult(False, f"Driver {d_id} is in excluded list")

    if bookings is None:
        bookings = []

    # Filter bookings for this driver
    driver_bookings = [
        b for b in bookings
        if str(_get(b, "driver_id", "")) == d_id
        and (not exclude_booking_id or str(_get(b, "id", "")) != str(exclude_booking_id))
    ]

    # 3. Overlap check in half-open interval [start, blocked_until)
    for b in driver_bookings:
        b_status = _get(b, "status", "")
        if b_status not in SLOT_HOLDING_STATUSES:
            continue
        b_start = _to_dt(_get(b, "start_time"))
        b_end = _to_dt(_get(b, "end_time"))
        b_blocked = _to_dt(_get(b, "blocked_until") or (b_end + buffer_delta))

        # Overlap in half-open interval: [start, blocked_until) overlaps [b_start, b_blocked) iff
        # b_start < blocked_until_utc AND start_utc < b_blocked
        if b_start < blocked_until_utc and start_utc < b_blocked:
            return DriverCheckResult(
                False,
                f"Driver has overlapping booking [{b_start.strftime('%H:%M')} - {b_blocked.strftime('%H:%M')})"
            )

    # 4. Daily hours cap in driver's local day (Asia/Kolkata)
    max_daily_hours = float(config.get("driver_max_hours_per_day", 9.0))
    start_kolkata = start_utc.astimezone(KOLKATA_TZ)
    local_day = start_kolkata.date()
    day_start_kolkata = datetime.combine(local_day, dtime.min, tzinfo=KOLKATA_TZ)
    day_end_kolkata = datetime.combine(local_day, dtime.max, tzinfo=KOLKATA_TZ)

    # Calculate hours already driven on local_day
    hours_driven_today = 0.0
    for b in driver_bookings:
        b_status = _get(b, "status", "")
        # Count completed, in-progress, or active confirmed bookings for daily workload
        if b_status not in ("COMPLETED", "IN_PROGRESS", "CONFIRMED", "APPROVED", "PENDING"):
            continue
        b_st_kol = _to_dt(_get(b, "start_time")).astimezone(KOLKATA_TZ)
        b_end_kol = _to_dt(_get(b, "end_time")).astimezone(KOLKATA_TZ)

        overlap_start = max(b_st_kol, day_start_kolkata)
        overlap_end = min(b_end_kol, day_end_kolkata)
        if overlap_end > overlap_start:
            hours_driven_today += (overlap_end - overlap_start).total_seconds() / 3600.0

    # Add this trip's duration in local_day
    req_overlap_start = max(start_kolkata, day_start_kolkata)
    req_overlap_end = min(trip_end_utc.astimezone(KOLKATA_TZ), day_end_kolkata)
    if req_overlap_end > req_overlap_start:
        this_trip_local_hours = (req_overlap_end - req_overlap_start).total_seconds() / 3600.0
    else:
        this_trip_local_hours = this_trip_hours

    if (hours_driven_today + this_trip_local_hours) > max_daily_hours:
        return DriverCheckResult(
            False,
            f"Daily hours limit exceeded ({hours_driven_today + this_trip_local_hours:.1f}h > {max_daily_hours:.1f}h in Asia/Kolkata)"
        )

    # 5. Rest gap since last completed trip end >= driver_min_rest_minutes (45m)
    min_rest_min = float(config.get("driver_min_rest_minutes", 45))

    # Check previous trips that ended before this trip starts
    last_ended_trip_end: Optional[datetime] = None
    for b in driver_bookings:
        b_status = _get(b, "status", "")
        if b_status not in ("COMPLETED", "IN_PROGRESS", "CONFIRMED", "APPROVED", "PENDING"):
            continue
        b_end = _to_dt(_get(b, "end_time"))
        if b_end <= start_utc:
            if last_ended_trip_end is None or b_end > last_ended_trip_end:
                last_ended_trip_end = b_end

    if last_ended_trip_end is not None:
        rest_gap_min = (start_utc - last_ended_trip_end).total_seconds() / 60.0
        if rest_gap_min < min_rest_min:
            return DriverCheckResult(
                False,
                f"Rest gap violation: only {rest_gap_min:.0f}m rest since last trip (minimum {min_rest_min:.0f}m required)"
            )

    # Also verify upcoming trips starting after this trip finishes
    for b in driver_bookings:
        b_status = _get(b, "status", "")
        if b_status not in ("COMPLETED", "IN_PROGRESS", "CONFIRMED", "APPROVED", "PENDING"):
            continue
        b_start = _to_dt(_get(b, "start_time"))
        if b_start >= trip_end_utc:
            gap_before_next_min = (b_start - trip_end_utc).total_seconds() / 60.0
            if gap_before_next_min < min_rest_min:
                return DriverCheckResult(
                    False,
                    f"Rest gap violation before next booking: only {gap_before_next_min:.0f}m gap (minimum {min_rest_min:.0f}m required)"
                )

    # 6. Continuous driving below driver_max_continuous_hours (4h)
    max_continuous_hours = float(config.get("driver_max_continuous_hours", 4.0))
    long_break_min = float(config.get("driver_long_break_minutes", 30))

    if this_trip_hours > max_continuous_hours:
        return DriverCheckResult(
            False,
            f"Trip duration {this_trip_hours:.1f}h exceeds max continuous driving limit of {max_continuous_hours:.1f}h"
        )

    # Accumulate continuous driving from consecutive trips with gaps < long_break_min
    prior_trips = []
    for b in driver_bookings:
        b_status = _get(b, "status", "")
        if b_status not in ("COMPLETED", "IN_PROGRESS", "CONFIRMED", "APPROVED", "PENDING"):
            continue
        b_st = _to_dt(_get(b, "start_time"))
        b_ed = _to_dt(_get(b, "end_time"))
        if b_ed <= start_utc:
            prior_trips.append((b_st, b_ed))

    prior_trips.sort(key=lambda x: x[1])  # Sort by end time ascending

    continuous_accumulated_hours = 0.0
    prev_end = None
    for trip_st, trip_ed in prior_trips:
        dur = (trip_ed - trip_st).total_seconds() / 3600.0
        if prev_end is not None:
            gap_m = (trip_st - prev_end).total_seconds() / 60.0
            if gap_m >= long_break_min:
                continuous_accumulated_hours = 0.0
        continuous_accumulated_hours += dur
        prev_end = trip_ed

    if prev_end is not None:
        gap_to_new_trip = (start_utc - prev_end).total_seconds() / 60.0
        if gap_to_new_trip < long_break_min:
            if (continuous_accumulated_hours + this_trip_hours) > max_continuous_hours:
                return DriverCheckResult(
                    False,
                    f"Continuous driving limit exceeded ({continuous_accumulated_hours + this_trip_hours:.1f}h > {max_continuous_hours:.1f}h)"
                )

    return DriverCheckResult(True, "")


def allocate(
    request: Any,
    exclude_driver_ids: tuple = (),
    exclude_booking_id: Optional[str] = None,
    vehicles: Optional[List[Any]] = None,
    drivers: Optional[List[Any]] = None,
    bookings: Optional[List[Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    db_conn=None,
) -> AllocationResult:
    """
    Main allocation engine entry point:
    allocate(request, exclude_driver_ids=(), exclude_booking_id=None) -> AllocationResult
    """
    from app.engine.alternatives import find_alternatives

    if config is None:
        config = get_app_config(conn=db_conn)

    buffer_min = int(config.get("buffer_minutes", 15))
    buffer_delta = timedelta(minutes=buffer_min)

    # 1. Normalize request
    start_utc = _to_dt(_get(request, "start") or _get(request, "start_time"))
    end_utc = _to_dt(_get(request, "end") or _get(request, "end_time"))
    passengers = int(_get(request, "passengers", 1))
    if passengers < 1 or passengers > 60:
        raise ValueError("Passenger count must be between 1 and 60")

    if end_utc <= start_utc:
        raise ValueError("Booking end_time must be strictly after start_time")

    blocked_until_utc = end_utc + buffer_delta
    window = (start_utc, end_utc, blocked_until_utc)

    # 2. Fetch fleet data if not passed explicitly
    if vehicles is None or drivers is None or bookings is None:
        db_veh = query_vehicles(conn=db_conn)
        db_drv = query_drivers(conn=db_conn)
        db_bkg = query_bookings(conn=db_conn, active_only=False)

        if vehicles is None:
            vehicles = db_veh if db_veh else get_default_vehicles()
        if drivers is None:
            drivers = db_drv if db_drv else get_default_drivers()
        if bookings is None:
            bookings = db_bkg

    skipped_candidates: List[str] = []

    # 3. Fleet Capacity Check: NO_VEHICLE_BIG_ENOUGH
    max_cap = max([int(_get(v, "capacity", 0)) for v in vehicles], default=0)
    if passengers > max_cap:
        alts = find_alternatives(
            request,
            vehicles=vehicles,
            drivers=drivers,
            bookings=bookings,
            config=config,
            exclude_driver_ids=exclude_driver_ids,
            exclude_booking_id=exclude_booking_id,
        )
        return AllocationResult(
            ok=False,
            options=[],
            failure_reason="NO_VEHICLE_BIG_ENOUGH",
            alternatives=alts,
        )

    # 4. Suitable Vehicles (capacity >= passengers and status != 'retired')
    capacity_matched_vehicles = [
        v for v in vehicles
        if int(_get(v, "capacity", 0)) >= passengers
        and _get(v, "status", "available") != "retired"
    ]

    # 5. Maintenance Check: VEHICLES_IN_MAINTENANCE
    in_maintenance_count = 0
    non_maintenance_vehicles = []
    for v in capacity_matched_vehicles:
        v_name = _get(v, "name", "Vehicle")
        v_status = _get(v, "status", "available")
        m_until = _get(v, "maintenance_until")

        is_maintenance = False
        if v_status == "maintenance":
            is_maintenance = True
        elif m_until is not None:
            m_dt = _to_dt(m_until)
            if m_dt > start_utc:
                is_maintenance = True

        if is_maintenance:
            in_maintenance_count += 1
            skipped_candidates.append(f"{v_name}: Under scheduled maintenance")
        else:
            non_maintenance_vehicles.append(v)

    if capacity_matched_vehicles and in_maintenance_count == len(capacity_matched_vehicles):
        alts = find_alternatives(
            request,
            vehicles=vehicles,
            drivers=drivers,
            bookings=bookings,
            config=config,
            exclude_driver_ids=exclude_driver_ids,
            exclude_booking_id=exclude_booking_id,
        )
        return AllocationResult(
            ok=False,
            options=[],
            failure_reason="VEHICLES_IN_MAINTENANCE",
            alternatives=alts,
        )

    # 6. Vehicle Conflict Filtering: ALL_VEHICLES_BUSY
    available_vehicles = []
    for v in non_maintenance_vehicles:
        v_id = str(_get(v, "id"))
        v_name = _get(v, "name", "Vehicle")
        v_busy = False

        for b in bookings:
            b_id = str(_get(b, "id", ""))
            if exclude_booking_id and b_id == str(exclude_booking_id):
                continue
            if str(_get(b, "vehicle_id", "")) != v_id:
                continue
            b_status = _get(b, "status", "")
            if b_status not in SLOT_HOLDING_STATUSES:
                continue
            b_st = _to_dt(_get(b, "start_time"))
            b_ed = _to_dt(_get(b, "end_time"))
            b_bl = _to_dt(_get(b, "blocked_until") or (b_ed + buffer_delta))

            # Overlap in [start, blocked_until)
            if b_st < blocked_until_utc and start_utc < b_bl:
                v_busy = True
                skipped_candidates.append(
                    f"{v_name}: Reserved for booking [{b_st.strftime('%H:%M')} - {b_bl.strftime('%H:%M')})"
                )
                break

        if not v_busy:
            available_vehicles.append(v)

    if not available_vehicles:
        alts = find_alternatives(
            request,
            vehicles=vehicles,
            drivers=drivers,
            bookings=bookings,
            config=config,
            exclude_driver_ids=exclude_driver_ids,
            exclude_booking_id=exclude_booking_id,
        )
        return AllocationResult(
            ok=False,
            options=[],
            failure_reason="ALL_VEHICLES_BUSY",
            alternatives=alts,
        )

    # 7. Driver Eligibility Filtering: driver_ok()
    start_kolkata = start_utc.astimezone(KOLKATA_TZ)
    local_day = start_kolkata.date()

    # Pre-calculate trips today for each driver in fleet
    driver_trip_counts = {}
    for d in drivers:
        d_id = str(_get(d, "id"))
        if hasattr(d, "trips_today") or (isinstance(d, dict) and "trips_today" in d):
            driver_trip_counts[d_id] = float(_get(d, "trips_today", 0))
        else:
            # Count completed/scheduled trips on local_day
            cnt = 0
            for b in bookings:
                if str(_get(b, "driver_id", "")) == d_id:
                    b_st_kol = _to_dt(_get(b, "start_time")).astimezone(KOLKATA_TZ)
                    if b_st_kol.date() == local_day and _get(b, "status") in (
                        "COMPLETED", "IN_PROGRESS", "CONFIRMED", "APPROVED", "PENDING"
                    ):
                        cnt += 1
            driver_trip_counts[d_id] = float(cnt)

    avg_trips_today = (
        sum(driver_trip_counts.values()) / len(driver_trip_counts)
        if driver_trip_counts
        else 0.0
    )

    eligible_drivers = []
    for d in drivers:
        d_id = str(_get(d, "id"))
        d_name = _get(d, "name", "Driver")
        # Attach trips_today
        d_trips = driver_trip_counts.get(d_id, 0.0)
        if isinstance(d, dict):
            d["trips_today"] = d_trips
        else:
            setattr(d, "trips_today", d_trips)

        ok, check_reason = driver_ok(
            d,
            window,
            bookings=bookings,
            config=config,
            exclude_driver_ids=exclude_driver_ids,
            exclude_booking_id=exclude_booking_id,
            end_time=end_utc,
        )
        if ok:
            eligible_drivers.append(d)
        else:
            skipped_candidates.append(f"Driver {d_name}: {check_reason}")

    if not eligible_drivers:
        alts = find_alternatives(
            request,
            vehicles=vehicles,
            drivers=drivers,
            bookings=bookings,
            config=config,
            exclude_driver_ids=exclude_driver_ids,
            exclude_booking_id=exclude_booking_id,
        )
        return AllocationResult(
            ok=False,
            options=[],
            failure_reason="NO_ELIGIBLE_DRIVER",
            alternatives=alts,
        )

    # 8. Score all viable (vehicle, driver) pairs
    scored_pairs = []
    for v in available_vehicles:
        for d in eligible_drivers:
            pair_score = score(v, d, passengers, avg_trips_today)
            scored_pairs.append((pair_score, v, d))

    # Sort descending by score; tie-breakers: smaller excess capacity, higher driver rating
    scored_pairs.sort(
        key=lambda item: (
            item[0],
            -max(0, int(_get(item[1], "capacity", 0)) - passengers),
            float(_get(item[2], "rating_avg", 0.0)),
        ),
        reverse=True,
    )

    # 9. Format top 3 options with explain() and skipped list
    top_pairs = scored_pairs[:3]
    options: List[AllocationOption] = []

    for rank, (s_val, v_chosen, d_chosen) in enumerate(top_pairs):
        v_id = str(_get(v_chosen, "id"))
        d_id = str(_get(d_chosen, "id"))
        v_name = str(_get(v_chosen, "name", "Vehicle"))
        d_name = str(_get(d_chosen, "name", "Driver"))

        reason_str = explain(v_chosen, d_chosen, passengers, avg_trips_today, score_val=s_val)

        # Build skipped list for this specific option
        option_skipped = list(skipped_candidates)
        for other_score, other_v, other_d in scored_pairs:
            other_v_id = str(_get(other_v, "id"))
            other_d_id = str(_get(other_d, "id"))
            if other_v_id != v_id or other_d_id != d_id:
                other_v_name = str(_get(other_v, "name", "Vehicle"))
                other_d_name = str(_get(other_d, "name", "Driver"))
                option_skipped.append(
                    f"{other_v_name} + Driver {other_d_name}: Scored {other_score:.2f} (vs {s_val:.2f})"
                )

        options.append(
            AllocationOption(
                vehicle_id=v_id,
                driver_id=d_id,
                score=round(s_val, 3),
                reason=reason_str,
                skipped=option_skipped,
                vehicle_name=v_name,
                driver_name=d_name,
            )
        )

    return AllocationResult(
        ok=True,
        options=options,
        failure_reason=None,
        alternatives=[],
    )
