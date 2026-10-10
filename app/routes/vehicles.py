from flask import Blueprint, jsonify

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/api/vehicles")

@vehicles_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "vehicles", "status": "pong"})
