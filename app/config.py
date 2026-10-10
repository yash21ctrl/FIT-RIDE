"""Configuration loader for environment variables and app_config values."""
import os
import time
from typing import Any, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Fallback defaults matching SPEC.md Section 7
DEFAULT_APP_CONFIG: Dict[str, Any] = {
    "buffer_minutes": 15,
    "driver_max_hours_per_day": 9.0,
    "driver_min_rest_minutes": 45,
    "driver_max_continuous_hours": 4.0,
    "driver_long_break_minutes": 30,
    "respond_window_scheduled_min": 30,
    "respond_window_emergency_min": 2,
    "auto_approve_max_hours": 4.0,
    "working_hours": "08:00-20:00",
    "merge_radius_km": 10.0,
    "timezone": "Asia/Kolkata",
}

INT_KEYS = {
    "buffer_minutes",
    "driver_min_rest_minutes",
    "driver_long_break_minutes",
    "respond_window_scheduled_min",
    "respond_window_emergency_min",
}

FLOAT_KEYS = {
    "driver_max_hours_per_day",
    "driver_max_continuous_hours",
    "auto_approve_max_hours",
    "merge_radius_km",
}

_config_cache: Dict[str, Any] = {}
_cache_timestamp: float = 0.0
_config_override: Dict[str, Any] = {}
CACHE_TTL: float = 60.0  # Cache for 60 seconds


def _parse_config_value(key: str, raw_val: Any) -> Any:
    """Parse raw database string configuration values into appropriate Python types."""
    if raw_val is None:
        return DEFAULT_APP_CONFIG.get(key)
    if isinstance(raw_val, (int, float)):
        return raw_val
    val_str = str(raw_val).strip()
    if key in INT_KEYS:
        try:
            return int(val_str)
        except ValueError:
            return DEFAULT_APP_CONFIG.get(key, 0)
    if key in FLOAT_KEYS:
        try:
            return float(val_str)
        except ValueError:
            return DEFAULT_APP_CONFIG.get(key, 0.0)
    return val_str


def get_app_config(conn=None, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Retrieve application config values with 60-second caching.
    Falls back to DEFAULT_APP_CONFIG if database query fails or is unconfigured.
    """
    global _config_cache, _cache_timestamp

    now = time.time()
    if not force_refresh and _config_cache and (now - _cache_timestamp < CACHE_TTL):
        result = dict(_config_cache)
        if _config_override:
            result.update(_config_override)
        return result

    loaded_config = dict(DEFAULT_APP_CONFIG)

    # Attempt to query database if connection or DATABASE_URL is available
    db_conn = conn
    close_conn = False
    try:
        if db_conn is None and DATABASE_URL:
            import psycopg2
            db_conn = psycopg2.connect(DATABASE_URL)
            close_conn = True

        if db_conn is not None:
            cursor = db_conn.cursor()
            cursor.execute("SELECT key, value FROM app_config;")
            rows = cursor.fetchall()
            for row in rows:
                k, v = row[0], row[1]
                loaded_config[k] = _parse_config_value(k, v)
            cursor.close()
    except Exception:
        # Fall back gracefully to DEFAULT_APP_CONFIG
        pass
    finally:
        if close_conn and db_conn is not None:
            try:
                db_conn.close()
            except Exception:
                pass

    _config_cache = loaded_config
    _cache_timestamp = now

    result = dict(_config_cache)
    if _config_override:
        result.update(_config_override)
    return result


def get_config_value(key: str, default: Any = None, conn=None) -> Any:
    """Get a single config value with caching."""
    cfg = get_app_config(conn=conn)
    if key in _config_override:
        return _config_override[key]
    return cfg.get(key, default)


def set_config_override(key: str, value: Any) -> None:
    """Set a runtime override for testing or manual tweaking."""
    _config_override[key] = value


def clear_config_cache() -> None:
    """Clear cached config and overrides."""
    global _config_cache, _cache_timestamp, _config_override
    _config_cache = {}
    _cache_timestamp = 0.0
    _config_override = {}
