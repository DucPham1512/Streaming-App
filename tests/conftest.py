"""Pytest fixtures for the streaming app test suite."""

import os

import boto3
import pytest
from moto import mock_aws

from app import create_app
from app.extensions import db as _db
from app.models.user import User


@pytest.fixture(scope="session", autouse=True)
def _aws_credentials():
    """Set fake AWS env vars so boto3 doesn't try to read ~/.aws/."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="session", autouse=True)
def _livekit_credentials():
    """Set fake LiveKit creds so token minting works in tests without a server.

    Token minting is fully local (JWT signing) — no LiveKit server is contacted.
    Room admin (`create_stream_room`, `delete_stream_room`) IS network-bound;
    tests that exercise those paths should monkeypatch livekit_service.
    """
    os.environ.setdefault("LIVEKIT_API_KEY", "devkey")
    os.environ.setdefault("LIVEKIT_API_SECRET", "test-secret-at-least-32-chars-long-padding")
    os.environ.setdefault("LIVEKIT_URL", "ws://localhost:7880")


@pytest.fixture(scope="session")
def _moto():
    """Session-wide moto mock so storage_service can be configured once.

    moto patches boto3 at the network layer; the patch must be active
    when storage_service.init_app builds its boto3 client.
    """
    with mock_aws():
        yield


@pytest.fixture(scope="session")
def app(_moto):
    """Create the Flask application configured for testing.

    Registers the throwaway ``_authtest`` blueprint used by
    test_auth_service.py before any request is served (Flask 3 forbids
    late blueprint registration).
    """
    app = create_app("testing")

    from tests._authtest_blueprint import make_authtest_blueprint

    app.register_blueprint(make_authtest_blueprint())

    # Pre-create the test buckets so storage operations have somewhere to go.
    from app.services.storage_service import storage_service

    with app.app_context():
        s3 = storage_service.client
        for bucket in (app.config["MEDIA_PUBLIC_BUCKET"], app.config["MEDIA_PRIVATE_BUCKET"]):
            try:
                s3.create_bucket(Bucket=bucket)
            except Exception:
                pass

    yield app


@pytest.fixture(scope="function")
def db(app):
    """Provide a clean database for each test function."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(autouse=True)
def _stub_livekit_room_admin(monkeypatch):
    """Stub LiveKit room admin operations so tests don't hit the network.

    Token minting is left real (it's just local JWT signing). Only the
    network-bound room.create_room / room.delete_room calls are stubbed.
    """
    from app.services import livekit_service

    def _fake_create_room(stream_id, owner_identity, *, owner_display_name=None,
                          empty_timeout_seconds=300):
        token = livekit_service.mint_access_token(
            room_name=stream_id,
            identity=owner_identity,
            can_publish=True,
            display_name=owner_display_name,
        )
        return livekit_service.CreatedRoom(
            room_name=stream_id,
            publisher_token=token,
            livekit_url=os.environ["LIVEKIT_URL"],
        )

    def _fake_delete_room(stream_id):
        return None

    monkeypatch.setattr(livekit_service, "create_stream_room", _fake_create_room)
    monkeypatch.setattr(livekit_service, "delete_stream_room", _fake_delete_room)


@pytest.fixture(scope="function")
def client(app, db):
    """Flask test client for REST API testing."""
    return app.test_client()


@pytest.fixture(scope="function")
def socketio_test_client(app, db):
    """Flask-SocketIO test client for WebSocket event testing."""
    from app.extensions import socketio

    return socketio.test_client(app)


# --- Auth fixtures (Story A) -----------------------------------------------


@pytest.fixture(scope="function")
def auth_user(db):
    """A persisted User with a known api_key, ready to authenticate as."""
    user = User(username="alice", display_name="Alice", email="alice@example.test")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope="function")
def other_user(db):
    """A second persisted user for cross-ownership tests."""
    user = User(username="bob", display_name="Bob", email="bob@example.test")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture(scope="function")
def auth_headers(auth_user):
    """Authorization headers for the primary auth_user."""
    return {"Authorization": f"Bearer {auth_user.api_key}"}


@pytest.fixture(scope="function")
def other_headers(other_user):
    """Authorization headers for the second user."""
    return {"Authorization": f"Bearer {other_user.api_key}"}


# --- Story B fixtures: storage + media -------------------------------------


@pytest.fixture(scope="function")
def s3_client(app):
    """Direct boto3 S3 client backed by moto, for pre/post test inspection."""
    from app.services.storage_service import storage_service

    return storage_service.client


@pytest.fixture(scope="function")
def fresh_buckets(app, s3_client):
    """Reset the test buckets to empty before each test that uses storage."""
    pub = app.config["MEDIA_PUBLIC_BUCKET"]
    priv = app.config["MEDIA_PRIVATE_BUCKET"]
    for bucket in (pub, priv):
        try:
            objs = s3_client.list_objects_v2(Bucket=bucket).get("Contents", []) or []
            for o in objs:
                s3_client.delete_object(Bucket=bucket, Key=o["Key"])
        except Exception:
            try:
                s3_client.create_bucket(Bucket=bucket)
            except Exception:
                pass
    return pub, priv
