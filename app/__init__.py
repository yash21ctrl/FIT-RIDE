"""Flask app factory and global configuration (Team KNIGHT | PS 40)."""
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from dotenv import load_dotenv

from app.db import ExclusionViolationError

load_dotenv()


def create_app():
    app = Flask(__name__)

    # CORS configuration for frontend origins
    CORS(
        app,
        resources={r"/api/*": {"origins": "*"}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    # Health check route
    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "app": "FleetRide API"}), 200

    # Test route to simulate PostgreSQL exclusion violation (23P01)
    @app.route("/api/test/simulate-23p01", methods=["GET", "POST"])
    def simulate_exclusion():
        raise ExclusionViolationError(
            message="conflicting key value violates exclusion constraint 'no_vehicle_overlap'",
            pgcode="23P01",
        )

    # Global Error Handlers matching SPEC.md Section 9
    @app.errorhandler(ExclusionViolationError)
    def handle_exclusion_violation(err):
        alternatives = getattr(err, "alternatives", [])
        return jsonify({
            "error": {
                "code": "VEHICLE_TAKEN",
                "message": "That vehicle was just taken.",
                "alternatives": alternatives,
            }
        }), 409

    @app.errorhandler(400)
    def handle_400(err):
        desc = getattr(err, "description", "Bad Request")
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": desc,
                "alternatives": [],
            }
        }), 400

    @app.errorhandler(401)
    def handle_401(err):
        desc = getattr(err, "description", "Unauthorized")
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": desc,
                "alternatives": [],
            }
        }), 401

    @app.errorhandler(403)
    def handle_403(err):
        desc = getattr(err, "description", "Forbidden")
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": desc,
                "alternatives": [],
            }
        }), 403

    @app.errorhandler(404)
    def handle_404(err):
        desc = getattr(err, "description", "Not Found")
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": desc,
                "alternatives": [],
            }
        }), 404

    @app.errorhandler(405)
    def handle_405(err):
        desc = getattr(err, "description", "Method Not Allowed")
        return jsonify({
            "error": {
                "code": "METHOD_NOT_ALLOWED",
                "message": desc,
                "alternatives": [],
            }
        }), 405

    @app.errorhandler(Exception)
    def handle_generic_exception(err):
        # Catch PostgreSQL GiST exclusion violations (code 23P01)
        pgcode = getattr(err, "pgcode", None) or getattr(getattr(err, "orig", None), "pgcode", None)
        err_str = str(err).lower()
        if pgcode == "23P01" or "23p01" in err_str or "exclusion_violation" in err_str:
            alternatives = getattr(err, "alternatives", [])
            return jsonify({
                "error": {
                    "code": "VEHICLE_TAKEN",
                    "message": "That vehicle was just taken.",
                    "alternatives": alternatives,
                }
            }), 409

        if isinstance(err, HTTPException):
            code_map = {
                400: "BAD_REQUEST",
                401: "UNAUTHORIZED",
                403: "FORBIDDEN",
                404: "NOT_FOUND",
                405: "METHOD_NOT_ALLOWED",
                409: "CONFLICT",
                422: "UNPROCESSABLE_ENTITY",
                500: "INTERNAL_SERVER_ERROR",
            }
            code_str = code_map.get(err.code, getattr(err, "name", "ERROR").upper().replace(" ", "_"))
            return jsonify({
                "error": {
                    "code": code_str,
                    "message": err.description or str(err),
                    "alternatives": [],
                }
            }), err.code

        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred",
                "alternatives": [],
            }
        }), 500

    # State machine error handlers
    from app.services.transitions import IllegalTransitionError, ForbiddenTransitionError

    @app.errorhandler(IllegalTransitionError)
    def handle_illegal_transition(err):
        return jsonify({
            "error": {
                "code": "ILLEGAL_TRANSITION",
                "message": str(err),
                "alternatives": [],
            }
        }), 400

    @app.errorhandler(ForbiddenTransitionError)
    def handle_forbidden_transition(err):
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": str(err),
                "alternatives": [],
            }
        }), 403

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.bookings import bookings_bp
    from app.routes.vehicles import vehicles_bp
    from app.routes.drivers import drivers_bp, driver_bp
    from app.routes.trips import trips_bp
    from app.routes.manager import manager_bp
    from app.routes.analytics import analytics_bp
    from app.routes.ratings import ratings_bp
    from app.routes.notifications import notifications_bp
    from app.routes.admin import admin_bp
    from app.routes.employees import employees_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(driver_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(ratings_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(employees_bp)

    # Static file routes for frontend portals (Phase 5: Employee Portal)
    from flask import send_from_directory, redirect

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    frontend_dir = os.path.join(base_dir, "frontend")
    shared_dir = os.path.join(frontend_dir, "shared")
    employee_dir = os.path.join(frontend_dir, "employee")

    driver_dir = os.path.join(frontend_dir, "driver")
    manager_dir = os.path.join(frontend_dir, "manager")

    @app.route("/", methods=["GET"])
    def root_redirect():
        return redirect("/employee", code=302)

    @app.route("/employee", methods=["GET"])
    @app.route("/employee/", methods=["GET"])
    def employee_index():
        return send_from_directory(employee_dir, "index.html")

    @app.route("/employee/<path:filename>", methods=["GET"])
    def employee_static(filename):
        return send_from_directory(employee_dir, filename)

    @app.route("/driver", methods=["GET"])
    @app.route("/driver/", methods=["GET"])
    def driver_index():
        return send_from_directory(driver_dir, "index.html")

    @app.route("/driver/<path:filename>", methods=["GET"])
    def driver_static(filename):
        return send_from_directory(driver_dir, filename)

    @app.route("/manager", methods=["GET"])
    @app.route("/manager/", methods=["GET"])
    def manager_index():
        return send_from_directory(manager_dir, "index.html")

    @app.route("/manager/<path:filename>", methods=["GET"])
    def manager_static(filename):
        return send_from_directory(manager_dir, filename)

    @app.route("/shared/<path:filename>", methods=["GET"])
    def shared_static(filename):
        return send_from_directory(shared_dir, filename)

    @app.route("/frontend/<path:filename>", methods=["GET"])
    def frontend_static(filename):
        return send_from_directory(frontend_dir, filename)

    # Initialize background timeout monitor daemon safely (guarded against test/debug duplications)
    from app.services.timeouts import init_timeout_scheduler
    init_timeout_scheduler(app)

    return app

