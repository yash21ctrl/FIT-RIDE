"""Supabase and Postgres client helpers with in-memory fallback for testing."""
import os
import uuid
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


def reset_seed_data() -> None:
    """Reset in-memory data store to original seed data."""
    global _in_memory_profiles, _in_memory_vehicles, _in_memory_drivers
    _in_memory_profiles = {k: dict(v) for k, v in SEED_PROFILES.items()}
    _in_memory_vehicles = {k: dict(v) for k, v in SEED_VEHICLES.items()}
    _in_memory_drivers = {k: dict(v) for k, v in SEED_DRIVERS.items()}


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

def query_bookings(conn=None, active_only: bool = True) -> List[Dict[str, Any]]:
    """Fetch bookings from database."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        if conn is not None:
            close_conn = True

    if conn is None:
        return []

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if active_only:
                cur.execute("""
                    SELECT id, employee_id, vehicle_id, driver_id, start_time, end_time,
                           blocked_until, destination, passengers, reason, type, priority,
                           status, was_bumped, created_at
                    FROM bookings
                    WHERE status IN ('PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED')
                    ORDER BY start_time ASC;
                """)
            else:
                cur.execute("""
                    SELECT id, employee_id, vehicle_id, driver_id, start_time, end_time,
                           blocked_until, destination, passengers, reason, type, priority,
                           status, was_bumped, created_at
                    FROM bookings
                    ORDER BY start_time ASC;
                """)
            return list(cur.fetchall())
    finally:
        if close_conn and conn:
            conn.close()


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
