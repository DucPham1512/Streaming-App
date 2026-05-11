"""Application Factory.

Creates and configures the Flask application with all extensions,
blueprints, and WebSocket event handlers registered.
"""

from email.mime import application
import os
import logging

from flask import Flask, jsonify

from app.config import config_by_name
from app.extensions import db, socketio, cors, limiter, migrate
from app.services.exceptions import ServiceError
from app.services.storage_service import storage_service


def create_app(config_name=None):
    """Create and configure the Flask application.

    Parameters
    ----------
    config_name : str, optional
        One of "development", "testing", "production".
        Defaults to the FLASK_ENV environment variable or "development".
    """
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    application = Flask(__name__)
    config_cls = config_by_name[config_name]
    application.config.from_object(config_cls() if config_name == "production" else config_cls)

    logging.basicConfig(
        level=logging.DEBUG if application.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db.init_app(application)
    migrate.init_app(application, db)
    cors.init_app(application, origins=application.config.get("CORS_ORIGINS", "*"))
    # Use the threading async_mode in tests to keep the SocketIO event loop
    # synchronous; production keeps eventlet.
    async_mode = "threading" if application.config.get("TESTING") else "eventlet"
    socketio.init_app(application, cors_allowed_origins="*", async_mode=async_mode)
    limiter.init_app(application)
    storage_service.init_app(application)

    from app.api.auth_routes import auth_bp
    from app.api.stream_routes import stream_bp
    from app.api.config_routes import config_bp
    from app.api.media_routes import media_bp
    from app.api.comment_routes import comment_bp
    from app.api.follow_routes import follow_bp

    application.register_blueprint(auth_bp)
    application.register_blueprint(stream_bp)
    application.register_blueprint(config_bp)
    application.register_blueprint(media_bp)
    application.register_blueprint(comment_bp)
    application.register_blueprint(follow_bp)

    from app.api.webhook_routes import webhook_bp
    application.register_blueprint(webhook_bp)

    # Import socket event handlers so they are registered with socketio
    import app.sockets.connection_events  # noqa: F401
    import app.sockets.media_events  # noqa: F401
    import app.sockets.social_events  # noqa: F401

    _register_error_handlers(application)
    _register_cli(application)

    @application.route("/")
    def health():
        return {"status": "ok", "service": "streaming-app-backend"}

    return application


def _register_error_handlers(application):
    """Map ServiceError subclasses to the canonical error envelope."""

    @application.errorhandler(ServiceError)
    def handle_service_error(exc: ServiceError):
        return jsonify(exc.to_dict()), exc.status_code

    @application.errorhandler(404)
    def handle_404(_exc):
        return jsonify({"error": "Resource not found", "code": "NOT_FOUND"}), 404

    @application.errorhandler(405)
    def handle_405(_exc):
        return jsonify({"error": "Method not allowed", "code": "METHOD_NOT_ALLOWED"}), 405

    @application.errorhandler(413)
    def handle_413(_exc):
        cfg = application.config
        return (
            jsonify(
                {
                    "error": f"Upload exceeds {cfg.get('MEDIA_MAX_SIZE_MB', '?')} MB",
                    "code": "FILE_TOO_LARGE",
                    "max_size_mb": cfg.get("MEDIA_MAX_SIZE_MB"),
                }
            ),
            413,
        )

    @application.errorhandler(429)
    def handle_429(exc):
        return (
            jsonify(
                {
                    "error": str(exc.description) if hasattr(exc, "description") else "Rate limited",
                    "code": "RATE_LIMITED",
                }
            ),
            429,
        )

    @application.errorhandler(Exception)
    def handle_unexpected_exception(exc):
        logging.getLogger(__name__).exception("Unhandled exception in request")
        return jsonify({"error": "Internal server error", "code": "INTERNAL_ERROR"}), 500


def _register_cli(application):
    """Wire up `flask <command>` CLI commands."""
    from app.cli import register_commands

    register_commands(application)
