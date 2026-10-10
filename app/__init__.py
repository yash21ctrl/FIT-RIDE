import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__)
    CORS(app)

    # Health check route
    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "app": "FleetRide API"}), 200

    # Register blueprints
    from app.routes.bookings import bookings_bp
    from app.routes.vehicles import vehicles_bp
    from app.routes.drivers import drivers_bp
    from app.routes.trips import trips_bp
    from app.routes.manager import manager_bp
    from app.routes.analytics import analytics_bp
    from app.routes.ratings import ratings_bp

    app.register_blueprint(bookings_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(ratings_bp)

    return app
