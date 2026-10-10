from flask import Blueprint, jsonify

drivers_bp = Blueprint("drivers", __name__, url_prefix="/api/drivers")

@drivers_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "drivers", "status": "pong"})
