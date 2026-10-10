"""Ratings blueprint endpoints (Team KNIGHT | PS 40)."""
from flask import Blueprint, jsonify, request, g
from app.auth import require_role
from app.db import get_booking_by_id, create_rating, get_rating_by_booking_id

ratings_bp = Blueprint("ratings", __name__, url_prefix="/api/ratings")


@ratings_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "ratings", "status": "pong"})


@ratings_bp.route("", methods=["POST"])
@require_role("employee", "manager")
def submit_rating():
    """Submit a rating for a completed booking."""
    data = request.get_json(silent=True) or {}
    bid = data.get("booking_id") or data.get("trip_id")
    if not bid:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "booking_id is required",
                "alternatives": [],
            }
        }), 400

    b = get_booking_by_id(bid)
    if not b:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking not found with ID {bid}",
                "alternatives": [],
            }
        }), 404

    if b.get("status") != "COMPLETED":
        return jsonify({
            "error": {
                "code": "INVALID_STATUS",
                "message": f"Cannot rate booking in status '{b.get('status')}'; must be COMPLETED",
                "alternatives": [],
            }
        }), 400

    d_rate = data.get("driver_rating") or data.get("rating")
    v_rate = data.get("vehicle_rating") or d_rate or 5

    if d_rate is None:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "driver_rating is required",
                "alternatives": [],
            }
        }), 400

    try:
        d_rate = int(d_rate)
        v_rate = int(v_rate)
        if not (1 <= d_rate <= 5) or not (1 <= v_rate <= 5):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Ratings must be integers between 1 and 5",
                "alternatives": [],
            }
        }), 400

    rated_by = g.current_user["id"]
    comment = data.get("comment") or data.get("comments") or ""
    tags = data.get("tags") or []

    saved = create_rating(
        booking_id=bid,
        rated_by=rated_by,
        driver_rating=d_rate,
        vehicle_rating=v_rate,
        comment=comment,
        tags=tags,
    )
    return jsonify({"rating": saved, "message": "Rating submitted successfully"}), 201


@ratings_bp.route("/<booking_id>", methods=["GET"])
@require_role("employee", "manager", "driver")
def get_single_rating(booking_id: str):
    """Retrieve rating for booking."""
    r = get_rating_by_booking_id(booking_id)
    return jsonify({"rating": r}), 200
