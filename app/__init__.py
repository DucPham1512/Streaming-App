"""Application Factory.

Creates and configures the Flask application with all extensions,
blueprints, and WebSocket event handlers registered.
"""

import os
import logging

from flask import Flask

from app.config import config_by_name
from app.extensions import db, socketio, cors


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
    application.config.from_object(config_by_name[config_name])

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if application.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Initialize extensions
    db.init_app(application)
    cors.init_app(application, origins=application.config.get("CORS_ORIGINS", "*"))
    socketio.init_app(application, cors_allowed_origins="*", async_mode="eventlet")

    # Register REST API blueprints
    from app.api.stream_routes import stream_bp
    from app.api.config_routes import config_bp

    application.register_blueprint(stream_bp)
    application.register_blueprint(config_bp)

    # Import socket event handlers so they are registered with socketio
    import app.sockets.connection_events  # noqa: F401
    import app.sockets.media_events  # noqa: F401

    # Create database tables
    with application.app_context():
        from app.models import Stream, GestureMapping  # noqa: F401
        db.create_all()

    # Health check route
    @application.route("/")
    def health():
        return {"status": "ok", "service": "streaming-app-backend"}

    return application
