"""Throwaway blueprint used by tests/test_auth_service.py.

Registered once on the session-scoped Flask app (see tests/conftest.py)
because Flask 3 forbids late blueprint registration after the first
request is served.

This blueprint is NOT registered in production app creation — it lives
in the tests/ tree and is only mounted by the test conftest.
"""

from flask import Blueprint, jsonify

from app.models.user import User
from app.services.auth_service import current_user, require_auth, require_owner


def _getter(obj_id):
    """Owner-getter mock for require_owner tests.

    ``obj_id`` of form "owned-by-<username>" returns an object whose
    ``owner_id`` is that user's id. Any other value returns None.
    """
    if not obj_id.startswith("owned-by-"):
        return None
    username = obj_id[len("owned-by-") :]
    u = User.query.filter_by(username=username).first()
    if u is None:
        return None
    return type("Obj", (), {"owner_id": u.id})()


def make_authtest_blueprint():
    bp = Blueprint("_authtest", __name__, url_prefix="/_authtest")

    @bp.route("/whoami")
    @require_auth
    def whoami():
        u = current_user()
        return jsonify({"id": u.id, "username": u.username})

    @bp.route("/owned/<obj_id>", methods=["DELETE"])
    @require_auth
    @require_owner(_getter)
    def delete_owned(obj_id):
        return jsonify({"deleted": obj_id})

    return bp
