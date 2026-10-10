"""Notification routes (Team KNIGHT | PS 40).

Endpoints:
- GET  /api/notifications: Fetch notifications for the authenticated user.
- POST /api/notifications/<id>/read: Mark a notification as read.
- POST /api/notifications/read-all: Mark all notifications as read for current user.
"""
from flask import Blueprint, jsonify, g
from app.auth import require_auth
from app.db import get_notifications, mark_notification_as_read, mark_all_notifications_as_read

notifications_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@notifications_bp.route("", methods=["GET"])
@require_auth
def list_notifications():
    """Fetch notifications for the authenticated user."""
    user = g.current_user
    user_id = user["id"]
    notifs = get_notifications(user_id=user_id)
    return jsonify({
        "notifications": notifs,
        "unread_count": sum(1 for n in notifs if not n.get("read", False)),
    }), 200


@notifications_bp.route("/<notification_id>/read", methods=["POST"])
@require_auth
def mark_read(notification_id: str):
    """Mark a notification as read."""
    user = g.current_user
    user_id = user["id"]
    success = mark_notification_as_read(notification_id, user_id=user_id)
    return jsonify({
        "status": "ok" if success else "not_found",
        "id": notification_id,
        "read": True,
    }), 200


@notifications_bp.route("/read-all", methods=["POST"])
@require_auth
def mark_read_all():
    """Mark all notifications for the current user as read."""
    user = g.current_user
    user_id = user["id"]
    count = mark_all_notifications_as_read(user_id=user_id)
    return jsonify({
        "status": "ok",
        "count": count,
    }), 200
