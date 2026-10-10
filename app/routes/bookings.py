from flask import Blueprint, jsonify

bookings_bp = Blueprint("bookings", __name__, url_prefix="/api/bookings")

@bookings_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "bookings", "status": "pong"})
