import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY


# Canonical seed profiles matching migrations/003_seed.sql
SEED_PROFILES: Dict[str, Dict[str, Any]] = {
    # Managers
    "00000000-0000-0000-0002-000000000001": {
        "id": "00000000-0000-0000-0002-000000000001",
        "name": "Yashwanth M",
        "role": "manager",
        "phone": "+919876543210",
        "telegram_chat_id": "demo_mgr_1",
        "email": "manager1@fleetride.local",
    },
    "00000000-0000-0000-0002-000000000002": {
        "id": "00000000-0000-0000-0002-000000000002",
        "name": "Kavana",
        "role": "manager",
        "phone": "+919876543211",
        "telegram_chat_id": "demo_mgr_2",
        "email": "manager2@fleetride.local",
    },
    # Employees
    "00000000-0000-0000-0003-000000000001": {
        "id": "00000000-0000-0000-0003-000000000001",
        "name": "Ananya Roy",
        "role": "employee",
        "phone": "+919876543220",
        "telegram_chat_id": "demo_emp_1",
        "email": "emp1@fleetride.local",
    },
    "00000000-0000-0000-0003-000000000002": {
        "id": "00000000-0000-0000-0003-000000000002",
        "name": "Vikram Das",
        "role": "employee",
        "phone": "+919876543221",
        "telegram_chat_id": "demo_emp_2",
        "email": "emp2@fleetride.local",
    },
    "00000000-0000-0000-0003-000000000003": {
        "id": "00000000-0000-0000-0003-000000000003",
        "name": "Neha Nair",
        "role": "employee",
        "phone": "+919876543222",
        "telegram_chat_id": "demo_emp_3",
        "email": "emp3@fleetride.local",
    },
    "00000000-0000-0000-0003-000000000004": {
        "id": "00000000-0000-0000-0003-000000000004",
        "name": "Rahul Mehra",
        "role": "employee",
        "phone": "+919876543223",
        "telegram_chat_id": "demo_emp_4",
        "email": "emp4@fleetride.local",
    },
    "00000000-0000-0000-0003-000000000005": {
        "id": "00000000-0000-0000-0003-000000000005",
        "name": "Sneha Patel",
        "role": "employee",
        "phone": "+919876543224",
        "telegram_chat_id": "demo_emp_5",
        "email": "emp5@fleetride.local",
    },
    # Drivers
    "00000000-0000-0000-0004-000000000001": {
        "id": "00000000-0000-0000-0004-000000000001",
        "name": "Ravi Kumar",
        "role": "driver",
        "phone": "+919876543230",
        "telegram_chat_id": "demo_drv_1",
        "email": "driver1@fleetride.local",
    },
    "00000000-0000-0000-0004-000000000002": {
        "id": "00000000-0000-0000-0004-000000000002",
        "name": "Suresh Patil",
        "role": "driver",
        "phone": "+919876543231",
        "telegram_chat_id": "demo_drv_2",
        "email": "driver2@fleetride.local",
    },
    "00000000-0000-0000-0004-000000000003": {
        "id": "00000000-0000-0000-0004-000000000003",
        "name": "Amit Singh",
        "role": "driver",
        "phone": "+919876543232",
        "telegram_chat_id": "demo_drv_3",
        "email": "driver3@fleetride.local",
    },
    "00000000-0000-0000-0004-000000000004": {
        "id": "00000000-0000-0000-0004-000000000004",
        "name": "Priya Sharma",
        "role": "driver",
        "phone": "+919876543233",
        "telegram_chat_id": "demo_drv_4",
        "email": "driver4@fleetride.local",
    },
    "00000000-0000-0000-0004-000000000005": {
        "id": "00000000-0000-0000-0004-000000000005",
        "name": "Rajesh Verma",
        "role": "driver",
        "phone": "+919876543234",
        "telegram_chat_id": "demo_drv_5",
        "email": "driver5@fleetride.local",
    },
}

# Canonical seed vehicles matching migrations/003_seed.sql
SEED_VEHICLES: Dict[str, Dict[str, Any]] = {
    "00000000-0000-0000-0001-000000000001": {
        "id": "00000000-0000-0000-0001-000000000001",
        "name": "Maruti Swift",
        "type": "car",
        "capacity": 4,
        "status": "available",
        "maintenance_until": None,
        "odometer_km": 12500,
    },
    "00000000-0000-0000-0001-000000000002": {
        "id": "00000000-0000-0000-0001-000000000002",
        "name": "Honda City",
        "type": "car",
        "capacity": 4,
        "status": "available",
        "maintenance_until": None,
        "odometer_km": 28400,
    },
    "00000000-0000-0000-0001-000000000003": {
        "id": "00000000-0000-0000-0001-000000000003",
        "name": "Maruti Ertiga",
        "type": "van",
        "capacity": 7,
        "status": "available",
        "maintenance_until": None,
        "odometer_km": 45200,
    },
    "00000000-0000-0000-0001-000000000004": {
        "id": "00000000-0000-0000-0001-000000000004",
        "name": "Toyota Innova Crysta",
        "type": "van",
        "capacity": 7,
        "status": "available",
        "maintenance_until": None,
        "odometer_km": 61000,
    },
    "00000000-0000-0000-0001-000000000005": {
        "id": "00000000-0000-0000-0001-000000000005",
        "name": "Mahindra Bolero",
        "type": "van",
        "capacity": 7,
        "status": "available",
        "maintenance_until": None,
        "odometer_km": 78300,
    },
    "00000000-0000-0000-0001-000000000006": {
        "id": "00000000-0000-0000-0001-000000000006",
        "name": "Force Tempo Traveller",
        "type": "minibus",
        "capacity": 12,
        "status": "available",
        "maintenance_until": None,
        "odometer_km": 94000,
    },
}

# Canonical seed drivers matching migrations/003_seed.sql
SEED_DRIVERS: Dict[str, Dict[str, Any]] = {
    "00000000-0000-0000-0005-000000000001": {
        "id": "00000000-0000-0000-0005-000000000001",
        "profile_id": "00000000-0000-0000-0004-000000000001",
        "status": "available",
        "license_no": "DL-KA-01-2019-001",
        "rating_avg": 4.8,
    },
    "00000000-0000-0000-0005-000000000002": {
        "id": "00000000-0000-0000-0005-000000000002",
        "profile_id": "00000000-0000-0000-0004-000000000002",
        "status": "available",
        "license_no": "DL-KA-01-2020-002",
        "rating_avg": 4.9,
    },
    "00000000-0000-0000-0005-000000000003": {
        "id": "00000000-0000-0000-0005-000000000003",
        "profile_id": "00000000-0000-0000-0004-000000000003",
        "status": "available",
        "license_no": "DL-KA-01-2021-003",
        "rating_avg": 4.7,
    },
    "00000000-0000-0000-0005-000000000004": {
        "id": "00000000-0000-0000-0005-000000000004",
        "profile_id": "00000000-0000-0000-0004-000000000004",
        "status": "available",
        "license_no": "DL-KA-01-2022-004",
        "rating_avg": 4.6,
    },
    "00000000-0000-0000-0005-000000000005": {
        "id": "00000000-0000-0000-0005-000000000005",
        "profile_id": "00000000-0000-0000-0004-000000000005",
        "status": "available",
        "license_no": "DL-KA-01-2023-005",
        "rating_avg": 4.9,
    },
}

# In-memory working copies for fallback/testing
_in_memory_profiles: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in SEED_PROFILES.items()}
_in_memory_vehicles: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in SEED_VEHICLES.items()}
_in_memory_drivers: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in SEED_DRIVERS.items()}
_in_memory_bookings: Dict[str, Dict[str, Any]] = {}
_in_memory_decision_log: List[Dict[str, Any]] = []
_in_memory_driver_responses: List[Dict[str, Any]] = []
_in_memory_trips: Dict[str, Dict[str, Any]] = {}
_in_memory_notifications: List[Dict[str, Any]] = []


def reset_seed_data() -> None:
    """Reset in-memory data store to original seed data."""
    global _in_memory_profiles, _in_memory_vehicles, _in_memory_drivers
    global _in_memory_bookings, _in_memory_decision_log, _in_memory_driver_responses
    global _in_memory_trips, _in_memory_notifications
    _in_memory_profiles = {k: dict(v) for k, v in SEED_PROFILES.items()}
    _in_memory_vehicles = {k: dict(v) for k, v in SEED_VEHICLES.items()}
    _in_memory_drivers = {k: dict(v) for k, v in SEED_DRIVERS.items()}
    _in_memory_bookings = {}
    _in_memory_decision_log = []
    _in_memory_driver_responses = []
    _in_memory_trips = {}
    _in_memory_notifications = []


def register_test_profile(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """Register or update an in-memory profile for testing."""
    pid = str(profile_data.get("id") or uuid.uuid4())
    record = dict(profile_data)
    record["id"] = pid
    _in_memory_profiles[pid] = record
    return record


def get_db_connection():
    """Returns a psycopg2 database connection or None if unconfigured."""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception:
        return None


def get_supabase_client():
    """Returns Supabase client instance if configured, else None."""
    if not SUPABASE_URL:
        return None
    try:
        from supabase import create_client
        key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
        if not key:
            return None
        return create_client(SUPABASE_URL, key)
    except Exception:
        return None


# ---------------------------------------------------------
# Profile Repository Functions
# ---------------------------------------------------------

def get_profile_by_id(profile_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch user profile by ID, querying PostgreSQL first or in-memory fallback."""
    if not profile_id:
        return None
    
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, name, role, phone, telegram_chat_id
                    FROM profiles
                    WHERE id = %s;
                """, (profile_id,))
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    # In-memory fallback
    prof = _in_memory_profiles.get(str(profile_id))
    return dict(prof) if prof else None


def get_profile_by_email(email: str, conn=None) -> Optional[Dict[str, Any]]:
    """Lookup profile by email."""
    if not email:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT p.id, p.name, p.role, p.phone, p.telegram_chat_id, u.email
                    FROM profiles p
                    JOIN auth.users u ON p.id = u.id
                    WHERE lower(u.email) = lower(%s);
                """, (email.strip(),))
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    for prof in _in_memory_profiles.values():
        if prof.get("email", "").lower() == email.strip().lower():
            return dict(prof)
    return None


# ---------------------------------------------------------
# Vehicle Repository Functions
# ---------------------------------------------------------

def query_vehicles(conn=None) -> List[Dict[str, Any]]:
    """Fetch active fleet vehicles from database (or in-memory store)."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is None:
        return [
            dict(v) for v in _in_memory_vehicles.values()
            if v.get("status") != "retired"
        ]

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, type, capacity, status, maintenance_until, odometer_km
                FROM vehicles
                WHERE status != 'retired'
                ORDER BY capacity ASC, name ASC;
            """)
            rows = cur.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["id"] = str(item["id"])
                if item.get("odometer_km") is not None:
                    item["odometer_km"] = float(item["odometer_km"])
                result.append(item)
            return result
    finally:
        if close_conn and conn:
            conn.close()


def get_all_vehicles(conn=None) -> List[Dict[str, Any]]:
    """Fetch all vehicles (including retired/maintenance) for manager operations."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is None:
        res = [dict(v) for v in _in_memory_vehicles.values()]
        res.sort(key=lambda x: (x.get("capacity", 0), x.get("name", "")))
        return res

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, type, capacity, status, maintenance_until, odometer_km
                FROM vehicles
                ORDER BY capacity ASC, name ASC;
            """)
            rows = cur.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["id"] = str(item["id"])
                if item.get("odometer_km") is not None:
                    item["odometer_km"] = float(item["odometer_km"])
                result.append(item)
            return result
    finally:
        if close_conn and conn:
            conn.close()


def get_vehicle_by_id(vehicle_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch a single vehicle by ID."""
    if not vehicle_id:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, name, type, capacity, status, maintenance_until, odometer_km
                    FROM vehicles
                    WHERE id = %s;
                """, (vehicle_id,))
                row = cur.fetchone()
                if row:
                    item = dict(row)
                    item["id"] = str(item["id"])
                    if item.get("odometer_km") is not None:
                        item["odometer_km"] = float(item["odometer_km"])
                    return item
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    veh = _in_memory_vehicles.get(str(vehicle_id))
    return dict(veh) if veh else None


def create_vehicle(data: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """Insert a new vehicle."""
    new_id = str(data.get("id") or uuid.uuid4())
    record = {
        "id": new_id,
        "name": str(data["name"]).strip(),
        "type": str(data["type"]).strip(),
        "capacity": int(data["capacity"]),
        "status": data.get("status", "available"),
        "maintenance_until": data.get("maintenance_until"),
        "odometer_km": float(data.get("odometer_km", 0)),
    }

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO vehicles (id, name, type, capacity, status, maintenance_until, odometer_km)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, name, type, capacity, status, maintenance_until, odometer_km;
                """, (
                    record["id"],
                    record["name"],
                    record["type"],
                    record["capacity"],
                    record["status"],
                    record["maintenance_until"],
                    record["odometer_km"],
                ))
                conn.commit()
                row = cur.fetchone()
                if row:
                    saved = dict(row)
                    saved["id"] = str(saved["id"])
                    if saved.get("odometer_km") is not None:
                        saved["odometer_km"] = float(saved["odometer_km"])
                    return saved
        except Exception:
            conn.rollback()
            raise
        finally:
            if close_conn:
                conn.close()

    _in_memory_vehicles[new_id] = dict(record)
    return dict(record)


def update_vehicle(vehicle_id: str, updates: Dict[str, Any], conn=None) -> Optional[Dict[str, Any]]:
    """Update vehicle fields."""
    vid = str(vehicle_id)
    existing = get_vehicle_by_id(vid, conn=conn)
    if not existing:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            set_clauses = []
            vals = []
            for col in ("name", "type", "capacity", "status", "maintenance_until", "odometer_km"):
                if col in updates:
                    set_clauses.append(f"{col} = %s")
                    vals.append(updates[col])
            if set_clauses:
                vals.append(vid)
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    query = f"UPDATE vehicles SET {', '.join(set_clauses)} WHERE id = %s RETURNING id, name, type, capacity, status, maintenance_until, odometer_km;"
                    cur.execute(query, tuple(vals))
                    conn.commit()
                    row = cur.fetchone()
                    if row:
                        res = dict(row)
                        res["id"] = str(res["id"])
                        if res.get("odometer_km") is not None:
                            res["odometer_km"] = float(res["odometer_km"])
                        return res
            else:
                return existing
        except Exception:
            conn.rollback()
            raise
        finally:
            if close_conn:
                conn.close()

    # In-memory update
    if vid in _in_memory_vehicles:
        for k, v in updates.items():
            if k in ("name", "type", "capacity", "status", "maintenance_until", "odometer_km"):
                _in_memory_vehicles[vid][k] = v
        return dict(_in_memory_vehicles[vid])
    return None


# ---------------------------------------------------------
# Driver Repository Functions
# ---------------------------------------------------------

def query_drivers(conn=None) -> List[Dict[str, Any]]:
    """Fetch active drivers from database (or in-memory store)."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is None:
        res = []
        for d in _in_memory_drivers.values():
            if d.get("status") != "off":
                prof = _in_memory_profiles.get(d["profile_id"], {})
                item = dict(d)
                item["name"] = prof.get("name", "")
                item["phone"] = prof.get("phone", "")
                res.append(item)
        res.sort(key=lambda x: x.get("rating_avg", 0), reverse=True)
        return res

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id, d.profile_id, d.status, d.license_no, d.rating_avg, p.name, p.phone
                FROM drivers d
                JOIN profiles p ON d.profile_id = p.id
                WHERE d.status != 'off'
                ORDER BY d.rating_avg DESC;
            """)
            rows = cur.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["id"] = str(item["id"])
                item["profile_id"] = str(item["profile_id"])
                if item.get("rating_avg") is not None:
                    item["rating_avg"] = float(item["rating_avg"])
                result.append(item)
            return result
    finally:
        if close_conn and conn:
            conn.close()


def get_all_drivers(conn=None) -> List[Dict[str, Any]]:
    """Fetch all drivers (including off-duty) with profile details."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is None:
        res = []
        for d in _in_memory_drivers.values():
            prof = _in_memory_profiles.get(d["profile_id"], {})
            item = dict(d)
            item["name"] = prof.get("name", "")
            item["phone"] = prof.get("phone", "")
            item["role"] = prof.get("role", "driver")
            res.append(item)
        res.sort(key=lambda x: x.get("rating_avg", 0), reverse=True)
        return res

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id, d.profile_id, d.status, d.license_no, d.rating_avg, p.name, p.phone, p.role
                FROM drivers d
                JOIN profiles p ON d.profile_id = p.id
                ORDER BY d.rating_avg DESC;
            """)
            rows = cur.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["id"] = str(item["id"])
                item["profile_id"] = str(item["profile_id"])
                if item.get("rating_avg") is not None:
                    item["rating_avg"] = float(item["rating_avg"])
                result.append(item)
            return result
    finally:
        if close_conn and conn:
            conn.close()


def get_driver_by_id(driver_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch a driver by driver ID."""
    if not driver_id:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT d.id, d.profile_id, d.status, d.license_no, d.rating_avg, p.name, p.phone, p.role
                    FROM drivers d
                    JOIN profiles p ON d.profile_id = p.id
                    WHERE d.id = %s;
                """, (driver_id,))
                row = cur.fetchone()
                if row:
                    item = dict(row)
                    item["id"] = str(item["id"])
                    item["profile_id"] = str(item["profile_id"])
                    if item.get("rating_avg") is not None:
                        item["rating_avg"] = float(item["rating_avg"])
                    return item
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    d = _in_memory_drivers.get(str(driver_id))
    if not d:
        return None
    prof = _in_memory_profiles.get(d["profile_id"], {})
    item = dict(d)
    item["name"] = prof.get("name", "")
    item["phone"] = prof.get("phone", "")
    item["role"] = prof.get("role", "driver")
    return item


def get_driver_by_profile_id(profile_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch driver record linked to a given profile ID."""
    if not profile_id:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT d.id, d.profile_id, d.status, d.license_no, d.rating_avg
                    FROM drivers d
                    WHERE d.profile_id = %s;
                """, (profile_id,))
                row = cur.fetchone()
                if row:
                    item = dict(row)
                    item["id"] = str(item["id"])
                    item["profile_id"] = str(item["profile_id"])
                    if item.get("rating_avg") is not None:
                        item["rating_avg"] = float(item["rating_avg"])
                    return item
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    pid = str(profile_id)
    for d in _in_memory_drivers.values():
        if d.get("profile_id") == pid:
            return dict(d)
    return None


def create_driver(data: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """Register a driver linked to a profile."""
    new_id = str(data.get("id") or uuid.uuid4())
    profile_id = str(data["profile_id"])
    record = {
        "id": new_id,
        "profile_id": profile_id,
        "status": data.get("status", "available"),
        "license_no": data.get("license_no", ""),
        "rating_avg": float(data.get("rating_avg", 5.0)),
    }

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO drivers (id, profile_id, status, license_no, rating_avg)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, profile_id, status, license_no, rating_avg;
                """, (
                    record["id"],
                    record["profile_id"],
                    record["status"],
                    record["license_no"],
                    record["rating_avg"],
                ))
                # Sync profile role to 'driver'
                cur.execute("UPDATE profiles SET role = 'driver' WHERE id = %s;", (record["profile_id"],))
                conn.commit()
                row = cur.fetchone()
                if row:
                    saved = dict(row)
                    saved["id"] = str(saved["id"])
                    saved["profile_id"] = str(saved["profile_id"])
                    if saved.get("rating_avg") is not None:
                        saved["rating_avg"] = float(saved["rating_avg"])
                    prof = get_profile_by_id(profile_id, conn=conn)
                    if prof:
                        saved["name"] = prof.get("name", "")
                        saved["phone"] = prof.get("phone", "")
                        saved["role"] = "driver"
                    return saved
        except Exception:
            conn.rollback()
            raise
        finally:
            if close_conn:
                conn.close()

    _in_memory_drivers[new_id] = dict(record)
    if profile_id in _in_memory_profiles:
        _in_memory_profiles[profile_id]["role"] = "driver"
    prof = _in_memory_profiles.get(profile_id, {})
    result = dict(record)
    result["name"] = prof.get("name", "")
    result["phone"] = prof.get("phone", "")
    result["role"] = "driver"
    return result


def update_driver(driver_id: str, updates: Dict[str, Any], conn=None) -> Optional[Dict[str, Any]]:
    """Update driver status or license."""
    did = str(driver_id)
    existing = get_driver_by_id(did, conn=conn)
    if not existing:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            set_clauses = []
            vals = []
            for col in ("status", "license_no", "rating_avg"):
                if col in updates:
                    set_clauses.append(f"{col} = %s")
                    vals.append(updates[col])
            if set_clauses:
                vals.append(did)
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    query = f"UPDATE drivers SET {', '.join(set_clauses)} WHERE id = %s RETURNING id, profile_id, status, license_no, rating_avg;"
                    cur.execute(query, tuple(vals))
                    conn.commit()
                    row = cur.fetchone()
                    if row:
                        res = dict(row)
                        res["id"] = str(res["id"])
                        res["profile_id"] = str(res["profile_id"])
                        if res.get("rating_avg") is not None:
                            res["rating_avg"] = float(res["rating_avg"])
                        prof = get_profile_by_id(res["profile_id"], conn=conn)
                        if prof:
                            res["name"] = prof.get("name", "")
                            res["phone"] = prof.get("phone", "")
                            res["role"] = prof.get("role", "driver")
                        return res
            else:
                return existing
        except Exception:
            conn.rollback()
            raise
        finally:
            if close_conn:
                conn.close()

    if did in _in_memory_drivers:
        for k, v in updates.items():
            if k in ("status", "license_no", "rating_avg"):
                _in_memory_drivers[did][k] = v
        prof = _in_memory_profiles.get(_in_memory_drivers[did]["profile_id"], {})
        res = dict(_in_memory_drivers[did])
        res["name"] = prof.get("name", "")
        res["phone"] = prof.get("phone", "")
        return res
    return None


# ---------------------------------------------------------
# Bookings & Exclusion Violations
# ---------------------------------------------------------

SLOT_HOLDING_STATUSES = ("PENDING", "APPROVED", "DRIVER_PENDING", "CONFIRMED", "IN_PROGRESS")


def _to_utc_dt(val: Any) -> Optional[datetime]:
    """Normalize datetime or ISO string to UTC timezone-aware datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        v = val.strip()
        if v.endswith("Z") or v.endswith("z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _format_dt(val: Any) -> Optional[str]:
    """Format datetime to ISO string."""
    dt = _to_utc_dt(val)
    if dt is None:
        return None
    return dt.isoformat()


def serialize_booking(b: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Format booking record for JSON API responses with ISO datetimes."""
    if not b:
        return None
    res = dict(b)
    for dt_col in ("start_time", "end_time", "blocked_until", "respond_by", "created_at"):
        if res.get(dt_col) is not None:
            res[dt_col] = _format_dt(res[dt_col])
    if res.get("passengers") is not None:
        res["passengers"] = int(res["passengers"])
    return res


def _check_in_memory_exclusions(booking_data: Dict[str, Any], exclude_booking_id: Optional[str] = None) -> None:
    """Enforce GiST exclusion constraints in-memory when PostgreSQL is offline."""
    status = booking_data.get("status", "PENDING")
    if status not in SLOT_HOLDING_STATUSES:
        return

    veh_id = str(booking_data.get("vehicle_id")) if booking_data.get("vehicle_id") else None
    drv_id = str(booking_data.get("driver_id")) if booking_data.get("driver_id") else None
    if not veh_id and not drv_id:
        return

    st = _to_utc_dt(booking_data["start_time"])
    bu = _to_utc_dt(booking_data.get("blocked_until") or booking_data["end_time"])
    if not st or not bu:
        return

    for b_id, b in _in_memory_bookings.items():
        if exclude_booking_id and b_id == str(exclude_booking_id):
            continue
        if b.get("status") not in SLOT_HOLDING_STATUSES:
            continue

        b_st = _to_utc_dt(b["start_time"])
        b_bu = _to_utc_dt(b.get("blocked_until") or b["end_time"])
        if not b_st or not b_bu:
            continue

        # Half-open interval overlap [st, bu) with [b_st, b_bu)
        if b_st < bu and st < b_bu:
            b_veh = str(b.get("vehicle_id")) if b.get("vehicle_id") else None
            b_drv = str(b.get("driver_id")) if b.get("driver_id") else None

            if veh_id and b_veh and veh_id == b_veh:
                raise ExclusionViolationError(
                    message='conflicting key value violates exclusion constraint "no_vehicle_overlap"',
                    pgcode="23P01",
                )
            if drv_id and b_drv and drv_id == b_drv:
                raise ExclusionViolationError(
                    message='conflicting key value violates exclusion constraint "no_driver_overlap"',
                    pgcode="23P01",
                )


def create_booking(booking_data: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """Create a new booking, enforcing PostgreSQL GiST exclusion constraints or in-memory checks."""
    new_id = str(booking_data.get("id") or uuid.uuid4())
    record = dict(booking_data)
    record["id"] = new_id
    record["created_at"] = _to_utc_dt(record.get("created_at") or datetime.now(timezone.utc))
    record["start_time"] = _to_utc_dt(record["start_time"])
    record["end_time"] = _to_utc_dt(record["end_time"])
    record["blocked_until"] = _to_utc_dt(record.get("blocked_until") or record["end_time"])
    if record.get("respond_by"):
        record["respond_by"] = _to_utc_dt(record["respond_by"])
    record.setdefault("status", "PENDING")
    record.setdefault("type", "scheduled")
    record.setdefault("priority", "normal")
    record.setdefault("was_bumped", False)
    record["passengers"] = int(record["passengers"])

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO bookings (
                        id, employee_id, vehicle_id, driver_id, start_time, end_time,
                        blocked_until, destination, dest_lat, dest_lng, passengers,
                        reason, type, priority, status, decision_reason, failure_reason,
                        respond_by, was_bumped, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING *;
                """, (
                    record["id"],
                    record["employee_id"],
                    record.get("vehicle_id"),
                    record.get("driver_id"),
                    record["start_time"],
                    record["end_time"],
                    record["blocked_until"],
                    record["destination"],
                    record.get("dest_lat"),
                    record.get("dest_lng"),
                    record["passengers"],
                    record["reason"],
                    record["type"],
                    record["priority"],
                    record["status"],
                    record.get("decision_reason"),
                    record.get("failure_reason"),
                    record.get("respond_by"),
                    record["was_bumped"],
                    record["created_at"],
                ))
                conn.commit()
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception as exc:
            conn.rollback()
            pgcode = getattr(exc, "pgcode", "") or getattr(getattr(exc, "orig", None), "pgcode", "")
            err_str = str(exc).lower()
            if pgcode == "23P01" or "23p01" in err_str or "exclusion_violation" in err_str:
                raise ExclusionViolationError(
                    message='conflicting key value violates exclusion constraint "no_vehicle_overlap"',
                    pgcode="23P01",
                )
            raise
        finally:
            if close_conn:
                conn.close()

    # In-memory execution
    _check_in_memory_exclusions(record)
    _in_memory_bookings[new_id] = dict(record)
    return dict(record)


def get_booking_by_id(booking_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch booking by ID."""
    if not booking_id:
        return None
    bid = str(booking_id)

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM bookings WHERE id = %s;", (bid,))
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    if bid in _in_memory_bookings:
        return dict(_in_memory_bookings[bid])
    return None


def update_booking(booking_id: str, updates: Dict[str, Any], conn=None) -> Optional[Dict[str, Any]]:
    """Update booking record with exclusion checking."""
    bid = str(booking_id)
    existing = get_booking_by_id(bid, conn=conn)
    if not existing:
        return None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    # Normalize dates in updates
    clean_updates = dict(updates)
    for dt_col in ("start_time", "end_time", "blocked_until", "respond_by"):
        if dt_col in clean_updates and clean_updates[dt_col] is not None:
            clean_updates[dt_col] = _to_utc_dt(clean_updates[dt_col])

    if conn is not None:
        try:
            set_clauses = []
            vals = []
            allowed_cols = (
                "vehicle_id", "driver_id", "start_time", "end_time", "blocked_until",
                "destination", "dest_lat", "dest_lng", "passengers", "reason",
                "type", "priority", "status", "decision_reason", "failure_reason",
                "respond_by", "was_bumped"
            )
            for col in allowed_cols:
                if col in clean_updates:
                    set_clauses.append(f"{col} = %s")
                    vals.append(clean_updates[col])

            if set_clauses:
                vals.append(bid)
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    query = f"UPDATE bookings SET {', '.join(set_clauses)} WHERE id = %s RETURNING *;"
                    cur.execute(query, tuple(vals))
                    conn.commit()
                    row = cur.fetchone()
                    if row:
                        res = dict(row)
                        res["id"] = str(res["id"])
                        return res
            return existing
        except Exception as exc:
            conn.rollback()
            pgcode = getattr(exc, "pgcode", "") or getattr(getattr(exc, "orig", None), "pgcode", "")
            err_str = str(exc).lower()
            if pgcode == "23P01" or "23p01" in err_str or "exclusion_violation" in err_str:
                raise ExclusionViolationError(
                    message='conflicting key value violates exclusion constraint "no_vehicle_overlap"',
                    pgcode="23P01",
                )
            raise
        finally:
            if close_conn:
                conn.close()

    # In-memory execution
    if bid in _in_memory_bookings:
        candidate = dict(_in_memory_bookings[bid])
        candidate.update(clean_updates)
        _check_in_memory_exclusions(candidate, exclude_booking_id=bid)
        _in_memory_bookings[bid].update(clean_updates)
        return dict(_in_memory_bookings[bid])
    return None


def query_bookings(
    conn=None,
    active_only: bool = True,
    employee_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch bookings from database or in-memory store."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            where_clauses = []
            params = []
            if active_only:
                where_clauses.append("status IN ('PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED')")
            if employee_id:
                where_clauses.append("employee_id = %s")
                params.append(str(employee_id))
            if driver_id:
                where_clauses.append("driver_id = %s")
                params.append(str(driver_id))
            if status:
                where_clauses.append("status = %s")
                params.append(str(status))

            where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            query = f"SELECT * FROM bookings {where_str} ORDER BY start_time ASC;"
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                res = []
                for r in rows:
                    item = dict(r)
                    item["id"] = str(item["id"])
                    if item.get("employee_id"):
                        item["employee_id"] = str(item["employee_id"])
                    if item.get("vehicle_id"):
                        item["vehicle_id"] = str(item["vehicle_id"])
                    if item.get("driver_id"):
                        item["driver_id"] = str(item["driver_id"])
                    res.append(item)
                return res
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    # In-memory filtering
    res = []
    for b in _in_memory_bookings.values():
        if active_only and b.get("status") not in ('PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED'):
            continue
        if employee_id and str(b.get("employee_id")) != str(employee_id):
            continue
        if driver_id and str(b.get("driver_id")) != str(driver_id):
            continue
        if status and b.get("status") != status:
            continue
        res.append(dict(b))
    res.sort(key=lambda x: _to_utc_dt(x.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc))
    return res


def get_recent_pending_booking(employee_id: str, within_seconds: int = 30, conn=None) -> Optional[Dict[str, Any]]:
    """Idempotency guard: find any recent active booking request by employee created within window."""
    if not employee_id:
        return None
    eid = str(employee_id)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM bookings
                    WHERE employee_id = %s
                      AND status IN ('PENDING', 'APPROVED', 'DRIVER_PENDING')
                      AND created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, (eid, cutoff))
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    # In-memory check
    for b in _in_memory_bookings.values():
        if str(b.get("employee_id")) == eid and b.get("status") in ("PENDING", "APPROVED", "DRIVER_PENDING"):
            created = _to_utc_dt(b.get("created_at"))
            if created and created >= cutoff:
                return dict(b)
    return None


# ---------------------------------------------------------
# Decision Log Repository
# ---------------------------------------------------------

def add_decision_log(booking_id: str, actor_id: Optional[str], action: str, note: Optional[str] = None, conn=None) -> Dict[str, Any]:
    """Record an audit trail event in decision_log."""
    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    record = {
        "id": log_id,
        "booking_id": str(booking_id) if booking_id else None,
        "actor_id": str(actor_id) if actor_id else None,
        "action": str(action),
        "note": note,
        "created_at": now,
    }

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO decision_log (id, booking_id, actor_id, action, note, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *;
                """, (record["id"], record["booking_id"], record["actor_id"], record["action"], record["note"], record["created_at"]))
                conn.commit()
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            conn.rollback()
        finally:
            if close_conn:
                conn.close()

    _in_memory_decision_log.append(dict(record))
    return dict(record)


def get_decision_logs(booking_id: Optional[str] = None, conn=None) -> List[Dict[str, Any]]:
    """Retrieve decision logs optionally filtered by booking ID."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if booking_id:
                    cur.execute("SELECT * FROM decision_log WHERE booking_id = %s ORDER BY created_at ASC;", (str(booking_id),))
                else:
                    cur.execute("SELECT * FROM decision_log ORDER BY created_at ASC;")
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    res = []
    for l in _in_memory_decision_log:
        if not booking_id or str(l.get("booking_id")) == str(booking_id):
            res.append(dict(l))
    return res


# ---------------------------------------------------------
# Driver Responses Repository
# ---------------------------------------------------------

def add_driver_response(
    booking_id: str,
    driver_id: str,
    response: str,
    reject_reason: Optional[str] = None,
    conn=None,
) -> Dict[str, Any]:
    """Record driver acceptance, rejection, or timeout in driver_responses."""
    resp_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    record = {
        "id": resp_id,
        "booking_id": str(booking_id),
        "driver_id": str(driver_id),
        "response": str(response),
        "reject_reason": reject_reason,
        "responded_at": now,
    }

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO driver_responses (id, booking_id, driver_id, response, reject_reason, responded_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *;
                """, (record["id"], record["booking_id"], record["driver_id"], record["response"], record["reject_reason"], record["responded_at"]))
                conn.commit()
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            conn.rollback()
        finally:
            if close_conn:
                conn.close()

    _in_memory_driver_responses.append(dict(record))
    return dict(record)


def get_driver_responses(booking_id: Optional[str] = None, driver_id: Optional[str] = None, conn=None) -> List[Dict[str, Any]]:
    """Retrieve driver responses."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                clauses = []
                params = []
                if booking_id:
                    clauses.append("booking_id = %s")
                    params.append(str(booking_id))
                if driver_id:
                    clauses.append("driver_id = %s")
                    params.append(str(driver_id))
                w = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                cur.execute(f"SELECT * FROM driver_responses {w} ORDER BY responded_at ASC;", tuple(params))
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    res = []
    for r in _in_memory_driver_responses:
        if booking_id and str(r.get("booking_id")) != str(booking_id):
            continue
        if driver_id and str(r.get("driver_id")) != str(driver_id):
            continue
        res.append(dict(r))
    return res


# ---------------------------------------------------------
# Trips Repository
# ---------------------------------------------------------

def create_or_update_trip(booking_id: str, trip_data: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """Create or update trip record for a booking."""
    bid = str(booking_id)
    clean = dict(trip_data)
    for dt_col in ("actual_start", "actual_end"):
        if dt_col in clean and clean[dt_col] is not None:
            clean[dt_col] = _to_utc_dt(clean[dt_col])

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM trips WHERE booking_id = %s;", (bid,))
                existing = cur.fetchone()
                if existing:
                    set_clauses = []
                    vals = []
                    for k in ("start_odometer", "end_odometer", "fuel_added", "checklist", "actual_start", "actual_end"):
                        if k in clean:
                            set_clauses.append(f"{k} = %s")
                            vals.append(clean[k])
                    if set_clauses:
                        vals.append(bid)
                        cur.execute(f"UPDATE trips SET {', '.join(set_clauses)} WHERE booking_id = %s RETURNING *;", tuple(vals))
                else:
                    trip_id = str(clean.get("id") or uuid.uuid4())
                    cur.execute("""
                        INSERT INTO trips (id, booking_id, start_odometer, end_odometer, fuel_added, checklist, actual_start, actual_end)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *;
                    """, (
                        trip_id,
                        bid,
                        clean.get("start_odometer"),
                        clean.get("end_odometer"),
                        clean.get("fuel_added"),
                        clean.get("checklist"),
                        clean.get("actual_start"),
                        clean.get("actual_end"),
                    ))
                conn.commit()
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    res["booking_id"] = str(res["booking_id"])
                    return res
        except Exception:
            conn.rollback()
        finally:
            if close_conn:
                conn.close()

    # In-memory execution
    if bid in _in_memory_trips:
        _in_memory_trips[bid].update(clean)
    else:
        new_record = {
            "id": str(clean.get("id") or uuid.uuid4()),
            "booking_id": bid,
            "start_odometer": clean.get("start_odometer"),
            "end_odometer": clean.get("end_odometer"),
            "fuel_added": clean.get("fuel_added"),
            "checklist": clean.get("checklist"),
            "actual_start": clean.get("actual_start"),
            "actual_end": clean.get("actual_end"),
        }
        _in_memory_trips[bid] = new_record
    return dict(_in_memory_trips[bid])


def get_trip_by_booking_id(booking_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieve trip record by booking ID."""
    if not booking_id:
        return None
    bid = str(booking_id)

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM trips WHERE booking_id = %s;", (bid,))
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    res["booking_id"] = str(res["booking_id"])
                    return res
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    if bid in _in_memory_trips:
        return dict(_in_memory_trips[bid])
    return None


# ---------------------------------------------------------
# Notifications Repository
# ---------------------------------------------------------

def create_notification(
    user_id: str,
    message: str,
    booking_id: Optional[str] = None,
    channel: str = "in_app",
    conn=None,
) -> Dict[str, Any]:
    """Create in-app or dispatch notification."""
    notif_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    record = {
        "id": notif_id,
        "user_id": str(user_id),
        "message": str(message),
        "booking_id": str(booking_id) if booking_id else None,
        "channel": str(channel),
        "read": False,
        "created_at": now,
    }

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO notifications (id, user_id, message, booking_id, channel, read, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *;
                """, (record["id"], record["user_id"], record["message"], record["booking_id"], record["channel"], record["read"], record["created_at"]))
                conn.commit()
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["id"] = str(res["id"])
                    return res
        except Exception:
            conn.rollback()
        finally:
            if close_conn:
                conn.close()

    _in_memory_notifications.append(dict(record))
    return dict(record)


def get_notifications(user_id: Optional[str] = None, conn=None) -> List[Dict[str, Any]]:
    """Retrieve notifications."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is not None:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user_id:
                    cur.execute("SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC;", (str(user_id),))
                else:
                    cur.execute("SELECT * FROM notifications ORDER BY created_at DESC;")
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    res = []
    for n in _in_memory_notifications:
        if not user_id or str(n.get("user_id")) == str(user_id):
            res.append(dict(n))
    res.sort(key=lambda x: _to_utc_dt(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return res


class ExclusionViolationError(Exception):
    """Exception representing PostgreSQL GiST exclusion constraint violation (code 23P01)."""
    def __init__(self, message: str = "Conflicting booking exists for the requested slot", pgcode: str = "23P01", alternatives: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.pgcode = pgcode
        self.message = message
        self.alternatives = alternatives or []


def format_exclusion_error(alternatives: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Standardized error payload matching SPEC.md Section 4.7 when race condition occurs."""
    return {
        "error": {
            "code": "VEHICLE_TAKEN",
            "message": "That vehicle was just reserved. Here are the best alternatives:",
            "alternatives": alternatives or [],
        }
    }

