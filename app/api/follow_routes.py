"""REST API routes for follows — Member 4: Social Interaction.

Endpoints
---------
POST   /api/v1/follows/<user_id>              — Follow a user
DELETE /api/v1/follows/<user_id>              — Unfollow a user
GET    /api/v1/users/<user_id>/followers      — List a user's followers
GET    /api/v1/users/<user_id>/following      — List users a user is following
"""

from flask import Blueprint, jsonify, g

from app.extensions import db
from app.models.follow import Follow
from app.models.user import User
from app.services.auth_service import require_auth

follow_bp = Blueprint("follows", __name__)


def _get_user_or_404(user_id: str):
    user = User.query.get(user_id)
    if user is None:
        return None, jsonify({"error": "User not found"}), 404
    return user, None, None


@follow_bp.route("/api/v1/follows/<user_id>", methods=["POST"])
@require_auth
def follow_user(user_id):
    """Follow a user. Cannot follow yourself."""
    if user_id == g.current_user.id:
        return jsonify({"error": "You cannot follow yourself"}), 400

    target, err, code = _get_user_or_404(user_id)
    if err:
        return err, code

    existing = Follow.query.filter_by(
        follower_id=g.current_user.id, followed_id=user_id
    ).first()
    if existing:
        return jsonify({"error": "Already following this user"}), 409

    follow = Follow(follower_id=g.current_user.id, followed_id=user_id)
    db.session.add(follow)
    db.session.commit()

    return jsonify({"follow": follow.to_dict()}), 201


@follow_bp.route("/api/v1/follows/<user_id>", methods=["DELETE"])
@require_auth
def unfollow_user(user_id):
    """Unfollow a user."""
    follow = Follow.query.filter_by(
        follower_id=g.current_user.id, followed_id=user_id
    ).first()
    if follow is None:
        return jsonify({"error": "You are not following this user"}), 404

    db.session.delete(follow)
    db.session.commit()
    return jsonify({"message": "Unfollowed successfully"}), 200


@follow_bp.route("/api/v1/users/<user_id>/followers", methods=["GET"])
def list_followers(user_id):
    """List all users who follow the given user."""
    target, err, code = _get_user_or_404(user_id)
    if err:
        return err, code

    follows = Follow.query.filter_by(followed_id=user_id).order_by(Follow.created_at.desc()).all()
    return jsonify({
        "followers": [
            {
                "user_id": f.follower_id,
                "username": f.follower.username,
                "display_name": f.follower.display_name,
                "followed_at": f.created_at.isoformat(),
            }
            for f in follows
        ],
        "count": len(follows),
    }), 200


@follow_bp.route("/api/v1/users/<user_id>/following", methods=["GET"])
def list_following(user_id):
    """List all users that the given user follows."""
    target, err, code = _get_user_or_404(user_id)
    if err:
        return err, code

    follows = Follow.query.filter_by(follower_id=user_id).order_by(Follow.created_at.desc()).all()
    return jsonify({
        "following": [
            {
                "user_id": f.followed_id,
                "username": f.followed.username,
                "display_name": f.followed.display_name,
                "followed_at": f.created_at.isoformat(),
            }
            for f in follows
        ],
        "count": len(follows),
    }), 200
