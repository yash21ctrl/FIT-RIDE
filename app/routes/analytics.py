from flask import Blueprint, jsonify

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")

@analytics_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "analytics", "status": "pong"})
