from flask import Blueprint, jsonify

ratings_bp = Blueprint("ratings", __name__, url_prefix="/api/ratings")

@ratings_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"blueprint": "ratings", "status": "pong"})
