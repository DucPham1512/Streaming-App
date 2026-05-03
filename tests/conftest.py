"""Pytest fixtures for the streaming app test suite."""

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    """Create the Flask application configured for testing."""
    app = create_app("testing")
    yield app


@pytest.fixture(scope="function")
def db(app):
    """Provide a clean database for each test function."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(scope="function")
def client(app, db):
    """Flask test client for REST API testing."""
    return app.test_client()


@pytest.fixture(scope="function")
def socketio_test_client(app, db):
    """Flask-SocketIO test client for WebSocket event testing."""
    from app.extensions import socketio

    return socketio.test_client(app)
