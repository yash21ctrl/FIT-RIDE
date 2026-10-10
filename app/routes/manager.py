from flask import Blueprint, jsonify

manager_bp = Blueprint("manager", __name__, url_prefix="/api/manager")

@manager_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "manager", "status": "pong"})
