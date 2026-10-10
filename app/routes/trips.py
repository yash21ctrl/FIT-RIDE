from flask import Blueprint, jsonify

trips_bp = Blueprint("trips", __name__, url_prefix="/api/trips")

@trips_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "trips", "status": "pong"})
