"""In-app, push, and Telegram notification helpers (Team KNIGHT | PS 40)."""
from typing import Any, Dict, List, Optional
from app.db import create_notification, get_notifications


def send_notification(
    user_id: str,
    message: str,
    booking_id: Optional[str] = None,
    channel: str = "in_app",
    conn=None,
) -> Dict[str, Any]:
    """
    Send an in-app notification to a user and save it in the database.
    Channels: in_app, telegram, push.
    """
    return create_notification(
        user_id=user_id,
        message=message,
        booking_id=booking_id,
        channel=channel,
        conn=conn,
    )


def get_user_notifications(user_id: str, conn=None) -> List[Dict[str, Any]]:
    """Fetch notifications for a specific user."""
    return get_notifications(user_id=user_id, conn=conn)
