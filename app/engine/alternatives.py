"""Free-slot search, shifted windows, and alternative suggestions for allocation engine."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import zoneinfo

from app.config import get_app_config

KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")
SLOT_HOLDING_STATUSES = ("PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED", "IN_PROGRESS")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get attribute or dict key."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_dt(dt_val: Any) -> datetime:
    """Normalize timestamp value to timezone-aware UTC datetime."""
    if isinstance(dt_val, str):
        # Support ISO formats with or without Z
        clean = dt_val.replace("Z", "+00:00")
        dt_val = datetime.fromisoformat(clean)
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=timezone.utc)
    return dt_val.astimezone(timezone.utc)


def find_alternatives(
    request: Any,
    vehicles: Optional[List[Any]] = None,
    drivers: Optional[List[Any]] = None,
    bookings: Optional[List[Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    exclude_driver_ids: tuple = (),
    exclude_booking_id: Optional[str] = None,
    exclude_vehicle_ids: tuple = (),
) -> List[Dict[str, Any]]:
    """
    Generate alternative booking slots when direct allocation fails:
    1. Shifted windows (+/- 30, 60, 90, 120 minutes)
    2. Shorter duration options if trip > 45 minutes
    3. Next free slot per suitable vehicle within the next 7 days
    4. Group split recommendation if passengers exceed fleet max capacity
    """
    if config is None:
        config = get_app_config()

    buffer_min = int(config.get("buffer_minutes", 15))
    buffer_delta = timedelta(minutes=buffer_min)

    req_start = _to_dt(_get(request, "start") or _get(request, "start_time"))
    req_end = _to_dt(_get(request, "end") or _get(request, "end_time"))
    passengers = int(_get(request, "passengers", 1))
    duration = req_end - req_start

    if duration.total_seconds() <= 0:
        duration = timedelta(hours=1)
        req_end = req_start + duration

    alternatives: List[Dict[str, Any]] = []

    # Get seed/default data if not passed
    from app.engine.allocate import get_default_vehicles, get_default_drivers, driver_ok

    if vehicles is None:
        vehicles = get_default_vehicles()
    if drivers is None:
        drivers = get_default_drivers()
    if bookings is None:
        bookings = []

    # 1. Capacity check: If passengers exceed max vehicle in fleet
    active_vehicles = [v for v in vehicles if _get(v, "status", "available") != "retired"]
    max_fleet_cap = max([int(_get(v, "capacity", 0)) for v in active_vehicles], default=0)
    if passengers > max_fleet_cap:
        alternatives.append({
            "type": "split_recommendation",
            "passengers": passengers,
            "max_vehicle_capacity": max_fleet_cap,
            "description": f"No vehicle has {passengers} seats (fleet maximum is {max_fleet_cap}). Recommend splitting into 2 separate bookings.",
        })
        alternatives.append({
            "type": "waitlist_recommendation",
            "passengers": passengers,
            "description": "Join the waitlist to be automatically promoted if fleet capacity is adjusted or larger vehicles become available.",
        })
        return alternatives

    exclude_veh_set = {str(x) for x in exclude_vehicle_ids}
    suitable_vehicles = [
        v for v in active_vehicles
        if int(_get(v, "capacity", 0)) >= passengers and str(_get(v, "id")) not in exclude_veh_set
    ]

    # Helper: Check if vehicle is free in [start, blocked_until)
    def vehicle_free(veh: Any, slot_start: datetime, slot_blocked: datetime) -> bool:
        v_status = _get(veh, "status", "available")
        if v_status == "retired":
            return False
        m_until = _get(veh, "maintenance_until")
        if v_status == "maintenance":
            if m_until is None:
                return False
            m_dt = _to_dt(m_until)
            if slot_start < m_dt:
                return False
        elif m_until is not None:
            m_dt = _to_dt(m_until)
            if slot_start < m_dt:
                return False

        v_id = str(_get(veh, "id"))
        for b in bookings:
            b_id = str(_get(b, "id", ""))
            if exclude_booking_id and b_id == str(exclude_booking_id):
                continue
            if str(_get(b, "vehicle_id", "")) != v_id:
                continue
            b_stat = _get(b, "status", "")
            if b_stat not in SLOT_HOLDING_STATUSES:
                continue
            b_st = _to_dt(_get(b, "start_time"))
            b_bl = _to_dt(_get(b, "blocked_until") or (_get(b, "end_time") + buffer_delta))
            # Half open [start, blocked_until)
            if b_st < slot_blocked and slot_start < b_bl:
                return False
        return True

    # Helper: Find at least one eligible driver for slot
    def find_eligible_driver(slot_start: datetime, slot_end: datetime, slot_blocked: datetime) -> Optional[Any]:
        excluded_set = {str(x) for x in exclude_driver_ids}
        for d in drivers:
            d_id = str(_get(d, "id"))
            if d_id in excluded_set:
                continue
            ok, _ = driver_ok(
                d,
                (slot_start, slot_end, slot_blocked),
                bookings=bookings,
                config=config,
                exclude_driver_ids=exclude_driver_ids,
                exclude_booking_id=exclude_booking_id,
            )
            if ok:
                return d
        return None

    # 2. Shifted Windows: +/- 30, 60, 90, 120 minutes
    shift_offsets = [-30, 30, -60, 60, -90, 90, -120, 120]
    seen_shifted = set()
    for offset in shift_offsets:
        new_start = req_start + timedelta(minutes=offset)
        new_end = req_end + timedelta(minutes=offset)
        new_blocked = new_end + buffer_delta

        for v in suitable_vehicles:
            v_id = str(_get(v, "id"))
            if not vehicle_free(v, new_start, new_blocked):
                continue
            d = find_eligible_driver(new_start, new_end, new_blocked)
            if d is not None:
                d_id = str(_get(d, "id"))
                d_name = _get(d, "name", "Assigned Driver")
                v_name = _get(v, "name", "Fleet Vehicle")
                shift_key = (new_start.isoformat(), v_id)
                if shift_key not in seen_shifted:
                    seen_shifted.add(shift_key)
                    direction = "earlier" if offset < 0 else "later"
                    start_kolkata = new_start.astimezone(KOLKATA_TZ).strftime("%H:%M")
                    end_kolkata = new_end.astimezone(KOLKATA_TZ).strftime("%H:%M")
                    alternatives.append({
                        "type": "shifted_window",
                        "offset_minutes": offset,
                        "start": new_start.isoformat(),
                        "end": new_end.isoformat(),
                        "vehicle_id": v_id,
                        "vehicle_name": v_name,
                        "driver_id": d_id,
                        "driver_name": d_name,
                        "description": (
                            f"Shift by {abs(offset)} min {direction} "
                            f"({start_kolkata} - {end_kolkata} IST) with {v_name}"
                        ),
                    })
                    break  # Found one candidate for this offset

    # 3. Shorter duration option (e.g. 75% or 50% or -30 min if > 45 min)
    duration_minutes = int(duration.total_seconds() / 60)
    if duration_minutes > 45:
        shorter_options = [duration_minutes - 30, duration_minutes // 2]
        for s_min in shorter_options:
            if s_min < 20:
                continue
            shorter_end = req_start + timedelta(minutes=s_min)
            shorter_blocked = shorter_end + buffer_delta
            for v in suitable_vehicles:
                v_id = str(_get(v, "id"))
                if not vehicle_free(v, req_start, shorter_blocked):
                    continue
                d = find_eligible_driver(req_start, shorter_end, shorter_blocked)
                if d is not None:
                    v_name = _get(v, "name", "Fleet Vehicle")
                    st_kol = req_start.astimezone(KOLKATA_TZ).strftime("%H:%M")
                    end_kol = shorter_end.astimezone(KOLKATA_TZ).strftime("%H:%M")
                    alternatives.append({
                        "type": "shorter_duration",
                        "duration_minutes": s_min,
                        "start": req_start.isoformat(),
                        "end": shorter_end.isoformat(),
                        "vehicle_id": v_id,
                        "vehicle_name": v_name,
                        "driver_id": str(_get(d, "id")),
                        "description": (
                            f"Shorten duration to {s_min} mins "
                            f"({st_kol} - {end_kol} IST) with {v_name}"
                        ),
                    })
                    break

    # 4. Free-slot search for suitable vehicles within next 7 days
    # Search each suitable vehicle forward in 30-min steps up to 7 days
    max_search_days = 7
    step = timedelta(minutes=30)
    for v in suitable_vehicles:
        v_id = str(_get(v, "id"))
        v_name = _get(v, "name", "Fleet Vehicle")
        curr_start = req_start + timedelta(minutes=30)
        end_search = req_start + timedelta(days=max_search_days)

        found_slot = False
        while curr_start < end_search:
            curr_end = curr_start + duration
            curr_blocked = curr_end + buffer_delta

            if vehicle_free(v, curr_start, curr_blocked):
                d = find_eligible_driver(curr_start, curr_end, curr_blocked)
                if d is not None:
                    st_kol = curr_start.astimezone(KOLKATA_TZ).strftime("%a %d %b, %H:%M")
                    end_kol = curr_end.astimezone(KOLKATA_TZ).strftime("%H:%M")
                    alternatives.append({
                        "type": "next_available_slot",
                        "vehicle_id": v_id,
                        "vehicle_name": v_name,
                        "driver_id": str(_get(d, "id")),
                        "driver_name": _get(d, "name", "Driver"),
                        "start": curr_start.isoformat(),
                        "end": curr_end.isoformat(),
                        "description": f"Next free slot for {v_name}: {st_kol} - {end_kol} IST",
                    })
                    found_slot = True
                    break
            curr_start += step
        if found_slot and len([a for a in alternatives if a["type"] == "next_available_slot"]) >= 3:
            break

    return alternatives
