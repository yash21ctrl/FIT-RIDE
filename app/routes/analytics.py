"""Analytics blueprint endpoints (Team KNIGHT | PS 40)."""
from flask import Blueprint, jsonify
from app.auth import require_role
from app.routes.manager import manager_analytics

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@analytics_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "analytics", "status": "pong"})


@analytics_bp.route("", methods=["GET"])
@require_role("manager")
def get_analytics():
    """Forward /api/analytics to manager_analytics."""
    return manager_analytics()
