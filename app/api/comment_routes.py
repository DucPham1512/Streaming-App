"""REST API routes for comments — Member 4: Social Interaction.

Endpoints
---------
POST   /api/v1/streams/<stream_id>/comments          — Post a comment to a stream
GET    /api/v1/streams/<stream_id>/comments          — List comments for a stream
DELETE /api/v1/comments/<comment_id>                 — Delete own comment
"""

from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models.comment import Comment
from app.models.stream import Stream
from app.services.auth_service import require_auth, current_user

comment_bp = Blueprint("comments", __name__)


@comment_bp.route("/api/v1/streams/<stream_id>/comments", methods=["POST"])
@require_auth
def post_comment(stream_id):
    """Post a comment to a stream. Requires auth."""
    stream = Stream.query.get(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found"}), 404

    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400
    if len(content) > 500:
        return jsonify({"error": "content must be 500 characters or fewer"}), 400

    comment = Comment(
        stream_id=stream_id,
        user_id=g.current_user.id,
        content=content,
    )
    db.session.add(comment)
    db.session.commit()

    return jsonify({"comment": comment.to_dict()}), 201


@comment_bp.route("/api/v1/streams/<stream_id>/comments", methods=["GET"])
def list_comments(stream_id):
    """List comments for a stream, ordered oldest-first. Supports ?limit= and ?before_id=."""
    stream = Stream.query.get(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found"}), 404

    limit = min(int(request.args.get("limit", 50)), 100)
    before_id = request.args.get("before_id", type=int)

    query = Comment.query.filter_by(stream_id=stream_id)
    if before_id is not None:
        query = query.filter(Comment.id < before_id)

    comments = query.order_by(Comment.created_at.asc()).limit(limit).all()

    return jsonify({
        "comments": [c.to_dict() for c in comments],
        "count": len(comments),
    }), 200


@comment_bp.route("/api/v1/comments/<int:comment_id>", methods=["DELETE"])
@require_auth
def delete_comment(comment_id):
    """Delete a comment. Only the comment author can delete it."""
    comment = Comment.query.get(comment_id)
    if comment is None:
        return jsonify({"error": "Comment not found"}), 404
    if comment.user_id != g.current_user.id:
        return jsonify({"error": "You do not own this comment"}), 403

    db.session.delete(comment)
    db.session.commit()
    return jsonify({"message": "Comment deleted"}), 200
