"""Supabase and Postgres client helpers."""
import os
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY


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


def query_vehicles(conn=None) -> List[Dict[str, Any]]:
    """Fetch active fleet vehicles from database."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    if conn is None:
        return []

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, type, capacity, status, maintenance_until, odometer_km
                FROM vehicles
                WHERE status != 'retired'
                ORDER BY capacity ASC, name ASC;
            """)
            return list(cur.fetchall())
    finally:
        if close_conn and conn:
            conn.close()


def query_drivers(conn=None) -> List[Dict[str, Any]]:
    """Fetch active drivers from database."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    if conn is None:
        return []

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id, d.profile_id, d.status, d.license_no, d.rating_avg, p.name
                FROM drivers d
                JOIN profiles p ON d.profile_id = p.id
                WHERE d.status != 'off'
                ORDER BY d.rating_avg DESC;
            """)
            return list(cur.fetchall())
    finally:
        if close_conn and conn:
            conn.close()


def query_bookings(conn=None, active_only: bool = True) -> List[Dict[str, Any]]:
    """Fetch bookings from database."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
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
    def __init__(self, message: str = "Conflicting booking exists for the requested slot", pgcode: str = "23P01"):
        super().__init__(message)
        self.pgcode = pgcode
        self.message = message


def format_exclusion_error(alternatives: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Standardized error payload matching SPEC.md Section 4.7 when race condition occurs."""
    return {
        "error": {
            "code": "VEHICLE_TAKEN",
            "message": "That vehicle was just reserved. Here are the best alternatives:",
            "alternatives": alternatives or [],
        }
    }

