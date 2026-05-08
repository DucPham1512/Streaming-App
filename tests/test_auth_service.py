"""Unit tests for app.services.auth_service.

Covers:
    current_user: present/missing/malformed/invalid token paths
    @require_auth: 401 on missing token
    @require_owner: 403 on wrong owner, 200 on right owner, 404 on missing
    User.to_dict: api_key omitted by default
"""

import pytest

from app.models.user import User
from app.services.auth_service import (
    current_user,
    current_user_optional,
)
from app.services.exceptions import Unauthorized


@pytest.fixture(scope="function")
def authtest_client(app, db, auth_user, other_user):
    """Test client with auth_user / other_user pre-populated."""
    return app.test_client()


# --- current_user direct-call tests ----------------------------------------


class TestCurrentUser:
    def test_returns_user_with_valid_token(self, app, db, auth_user):
        with app.test_request_context(
            "/", headers={"Authorization": f"Bearer {auth_user.api_key}"}
        ):
            user = current_user()
            assert user.id == auth_user.id
            assert user.username == "alice"

    def test_raises_unauthorized_when_header_missing(self, app, db):
        with app.test_request_context("/"):
            with pytest.raises(Unauthorized):
                current_user()

    def test_raises_unauthorized_when_header_malformed(self, app, db):
        with app.test_request_context("/", headers={"Authorization": "Token xyz"}):
            with pytest.raises(Unauthorized):
                current_user()

    def test_raises_unauthorized_when_token_unknown(self, app, db):
        with app.test_request_context("/", headers={"Authorization": "Bearer not-a-real-key"}):
            with pytest.raises(Unauthorized):
                current_user()

    def test_optional_returns_none_when_unauthed(self, app, db):
        with app.test_request_context("/"):
            assert current_user_optional() is None

    def test_optional_returns_user_when_authed(self, app, db, auth_user):
        with app.test_request_context(
            "/", headers={"Authorization": f"Bearer {auth_user.api_key}"}
        ):
            assert current_user_optional() is not None


# --- @require_auth via test routes -----------------------------------------


class TestRequireAuth:
    def test_401_without_header(self, authtest_client):
        resp = authtest_client.get("/_authtest/whoami")
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["code"] == "UNAUTHORIZED"

    def test_200_with_valid_header(self, authtest_client, auth_headers):
        resp = authtest_client.get("/_authtest/whoami", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["username"] == "alice"


# --- @require_owner via test routes ----------------------------------------


class TestRequireOwner:
    def test_404_when_object_not_found(self, authtest_client, auth_headers):
        resp = authtest_client.delete("/_authtest/owned/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.get_json()["code"] == "NOT_FOUND"

    def test_403_when_not_owner(self, authtest_client, auth_headers, other_user):
        # auth_headers belongs to alice; bob owns the resource.
        resp = authtest_client.delete(
            f"/_authtest/owned/owned-by-{other_user.username}",
            headers=auth_headers,
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "FORBIDDEN"

    def test_200_when_owner(self, authtest_client, auth_headers, auth_user):
        resp = authtest_client.delete(
            f"/_authtest/owned/owned-by-{auth_user.username}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"deleted": f"owned-by-{auth_user.username}"}


# --- User model serialization ----------------------------------------------


class TestUserSerialization:
    def test_to_dict_omits_api_key_by_default(self, db, auth_user):
        data = auth_user.to_dict()
        assert "api_key" not in data
        assert data["username"] == "alice"
        assert data["email"] == "alice@example.test"

    def test_to_dict_includes_api_key_when_requested(self, db, auth_user):
        data = auth_user.to_dict(include_api_key=True)
        assert data["api_key"] == auth_user.api_key

    def test_api_key_auto_generated(self, db):
        u = User(username="autogen")
        from app.extensions import db as _db
        _db.session.add(u)
        _db.session.commit()
        assert u.api_key
        assert len(u.api_key) == 64  # 32 bytes hex

    def test_username_uniqueness(self, db, auth_user):
        from app.extensions import db as _db
        from sqlalchemy.exc import IntegrityError
        dup = User(username="alice")
        _db.session.add(dup)
        with pytest.raises(IntegrityError):
            _db.session.commit()
