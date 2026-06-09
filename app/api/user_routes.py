"""Public user profile endpoints.

Routes
------
GET /api/v1/users/<user_id>  — Public profile (username, display_name, avatar_url)
"""

from flask import Blueprint, jsonify

from app.models.user import User

user_bp = Blueprint("users", __name__, url_prefix="/api/v1/users")


@user_bp.get("/<user_id>")
def get_user(user_id):
    """Return a user's public profile."""
    user = User.query.get(user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar_url": f"/api/v1/media/{user.avatar_media_id}/stream" if user.avatar_media_id else None,
        }
    }), 200
