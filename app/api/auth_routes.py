"""Authentication endpoints.

Routes
------
POST /api/v1/auth/register  — Create a new account
POST /api/v1/auth/login     — Authenticate and obtain an API key
POST /api/v1/auth/logout    — Invalidate the current API key
GET  /api/v1/auth/me        — Return the authenticated user's profile
"""

import re

from flask import Blueprint, g, jsonify, request

from app.extensions import db, limiter
from app.models.user import User
from app.services.auth_service import current_user, require_auth
from app.services.exceptions import InvalidField, InvalidRequest, Unauthorized

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_bp.post("/register")
@limiter.limit("10 per hour")
def register():
    """Create a new user account.

    Request JSON
    ------------
    username     : str  — 3–64 chars, letters/digits/underscore/hyphen
    email        : str  — valid email address
    password     : str  — at least 8 characters
    display_name : str  — optional, max 128 chars

    Returns 201 with ``{user, api_key}`` on success.
    """
    data = request.get_json(silent=True) or {}

    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None

    if not username:
        raise InvalidField("username is required", field="username")
    if not _USERNAME_RE.match(username):
        raise InvalidField(
            "username must be 3–64 characters: letters, digits, _ or -",
            field="username",
        )
    if not email:
        raise InvalidField("email is required", field="email")
    if not _EMAIL_RE.match(email):
        raise InvalidField("email must be a valid address", field="email")
    if len(password) < 8:
        raise InvalidField("password must be at least 8 characters", field="password")
    if len(password) > 128:
        raise InvalidField("password must be at most 128 characters", field="password")

    if User.query.filter_by(username=username).first():
        raise InvalidField("username is already taken", field="username")
    if User.query.filter_by(email=email).first():
        raise InvalidField("email is already registered", field="email")

    user = User(
        username=username,
        email=email,
        display_name=display_name or username,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({"user": user.to_dict(), "api_key": user.api_key}), 201


@auth_bp.post("/login")
@limiter.limit("10 per minute")
def login():
    """Authenticate with username/email and password.

    Request JSON
    ------------
    login    : str — username or email address
    password : str

    Returns 200 with ``{user, api_key}`` on success.
    """
    data = request.get_json(silent=True) or {}

    login_id = (data.get("login") or "").strip()
    password = data.get("password") or ""

    if not login_id or not password:
        raise InvalidRequest("login and password are required")

    user = User.query.filter_by(username=login_id).first()
    if user is None and "@" in login_id:
        user = User.query.filter_by(email=login_id.lower()).first()

    if user is None or not user.check_password(password):
        raise Unauthorized("Invalid credentials")

    return jsonify({"user": user.to_dict(), "api_key": user.api_key}), 200


@auth_bp.post("/logout")
@require_auth
def logout():
    """Rotate (invalidate) the current API key.

    The client must discard its stored key after calling this endpoint.
    Returns 200 ``{message}`` on success.
    """
    user = g.current_user
    user.rotate_api_key()
    db.session.commit()
    return jsonify({"message": "Logged out"}), 200


@auth_bp.get("/me")
@require_auth
def me():
    """Return the authenticated user's profile.

    Returns 200 ``{user}`` on success.
    """
    return jsonify({"user": g.current_user.to_dict()}), 200
