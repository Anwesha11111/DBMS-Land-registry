# backend/app/__init__.py
import os
import logging
from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("LandExchange")

def create_app(test_config=None) -> Flask:
    """Application factory for Land Exchange backend."""
    app = Flask(
        __name__,
        static_folder="../../frontend",
        static_url_path="/static"
    )

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_jwt_secret_key_change_in_production_rvce_land_exchange_2026")
    if test_config:
        app.config.update(test_config)

    # Initialize Database Connections
    from backend.db.connection import init_db_pools, check_health
    init_db_pools(app)

    # Register Blueprints
    from backend.routes.auth import auth_bp
    from backend.routes.plots import plots_bp
    from backend.routes.registry import registry_bp
    from backend.routes.injunctions import injunctions_bp
    from backend.routes.orders import orders_bp
    from backend.routes.reports import reports_bp
    from backend.routes.search import search_bp
    from backend.routes.public import public_bp
    from backend.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(plots_bp)
    app.register_blueprint(registry_bp)
    app.register_blueprint(injunctions_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    # /health Endpoint
    @app.route("/health", methods=["GET"])
    def health():
        health_status = check_health()
        http_code = 200 if health_status.get("status") == "healthy" else 207
        return jsonify(health_status), http_code

    # Static UI routes
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

    @app.route("/", methods=["GET"])
    def serve_index():
        return send_from_directory(frontend_dir, "index.html")

    @app.route("/public-portal", methods=["GET"])
    def serve_public_portal():
        return send_from_directory(os.path.join(frontend_dir, "public"), "index.html")

    @app.route("/<path:path>", methods=["GET"])
    def serve_frontend_files(path):
        if os.path.exists(os.path.join(frontend_dir, path)):
            return send_from_directory(frontend_dir, path)
        return jsonify({"error": "Resource not found", "path": path}), 404

    # Global JSON error handlers
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request", "details": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        logger.error(f"Internal server error: {e}")
        return jsonify({"error": "Internal server error"}), 500

    # Startup Ledger Genesis, In-Doubt Recovery and Auto-Seed
    with app.app_context():
        try:
            from backend.services.ledger import ensure_genesis
            from backend.services.settlement import recover_in_doubt_transactions
            from backend.db.connection import is_mock_mode
            from backend.db.mock_store import mock_db
            ensure_genesis()
            recover_in_doubt_transactions()

            # If mock DB is active and empty (and not in testing mode), automatically seed baseline plots
            is_testing = app.config.get("TESTING", False) or os.getenv("FLASK_ENV") == "testing"
            if is_mock_mode() and len(mock_db.plots) == 0 and not is_testing:
                logger.info("Initializing baseline seed plots into in-memory mock database...")
                from scripts.seed import seed_database
                seed_database()
        except Exception as startup_err:
            logger.warning(f"Startup task notice: {startup_err}")

    return app

__all__ = ["create_app"]
