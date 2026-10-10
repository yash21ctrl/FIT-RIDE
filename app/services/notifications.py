"""In-app and dispatch notification service (Team KNIGHT | PS 40)."""
from typing import Any, Dict, List, Optional, Sequence
from app.db import create_notification, get_notifications


def notify(
    user_id: str,
    message: str,
    booking_id: Optional[str] = None,
    channels: Sequence[str] = ("in_app",),
    conn=None,
) -> Dict[str, Any]:
    """
    Primary notification dispatch function matching SPEC.md Section 8 & 13.
    Always inserts in-app notification row (poller & Realtime deliver it).
    """
    last_res = None
    for ch in channels:
        last_res = create_notification(
            user_id=user_id,
            message=message,
            booking_id=booking_id,
            channel=ch,
            conn=conn,
        )
    return last_res or {
        "user_id": user_id,
        "message": message,
        "booking_id": booking_id,
        "channel": "in_app",
    }


def send_notification(
    user_id: str,
    message: str,
    booking_id: Optional[str] = None,
    channel: str = "in_app",
    conn=None,
) -> Dict[str, Any]:
    """Compatibility alias for notify()."""
    return notify(user_id=user_id, message=message, booking_id=booking_id, channels=(channel,), conn=conn)


def get_user_notifications(user_id: str, conn=None) -> List[Dict[str, Any]]:
    """Fetch notifications for a specific user."""
    return get_notifications(user_id=user_id, conn=conn)
