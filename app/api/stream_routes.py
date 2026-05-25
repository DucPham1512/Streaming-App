"""REST API routes for livestream session management.

Endpoints
---------
POST   /api/v1/streams                       — Create a new stream
PATCH  /api/v1/streams/<stream_id>           — Update stream metadata
POST   /api/v1/streams/<stream_id>/end       — End (terminate) a stream
POST   /api/v1/streams/<stream_id>/viewer-token — Mint a subscriber-only token
GET    /api/v1/streams/<stream_id>           — Get stream details
GET    /api/v1/streams                       — List active streams
POST   /api/v1/streams/<stream_id>/like      — Increment like count
"""

from flask import Blueprint, request, jsonify

from app.models.stream import Stream
from app.services import livekit_service
from app.services.stream_manager import stream_manager

stream_bp = Blueprint("streams", __name__, url_prefix="/api/v1/streams")


@stream_bp.route("", methods=["POST"])
def create_stream():
    """Initialize a new livestream session and mint a publisher token."""
    data = request.get_json(silent=True) or {}

    title = data.get("title", "Untitled Stream")
    description = data.get("description", "")
    privacy = data.get("privacy", "public")
    owner_identity = data.get("owner_identity")
    owner_display_name = data.get("owner_display_name")

    if privacy not in ("public", "private", "unlisted"):
        return jsonify({"error": "privacy must be public, private, or unlisted"}), 400

    try:
        stream, publisher_token, livekit_url = stream_manager.create_stream(
            title=title,
            description=description,
            privacy=privacy,
            owner_identity=owner_identity,
            owner_display_name=owner_display_name,
        )
    except livekit_service.LiveKitServiceError as e:
        return jsonify({"error": "Failed to provision stream", "detail": str(e)}), 502

    # publisher_token is sensitive: returned exactly once, to the creator.
    return jsonify({
        "stream": stream.to_dict(),
        "publisher_token": publisher_token,
        "livekit_url": livekit_url,
    }), 201


@stream_bp.route("/<stream_id>", methods=["PATCH"])
def update_stream(stream_id):
    """Update stream metadata (title, description, privacy)."""
    data = request.get_json(silent=True) or {}

    allowed_fields = {}
    if "title" in data:
        allowed_fields["title"] = data["title"]
    if "description" in data:
        allowed_fields["description"] = data["description"]
    if "privacy" in data:
        if data["privacy"] not in ("public", "private", "unlisted"):
            return (
                jsonify({"error": "privacy must be public, private, or unlisted"}),
                400,
            )
        allowed_fields["privacy"] = data["privacy"]

    if not allowed_fields:
        return jsonify({"error": "No valid fields provided to update"}), 400

    stream = stream_manager.update_stream(stream_id, **allowed_fields)
    if stream is None:
        return jsonify({"error": "Stream not found or already ended"}), 404

    return jsonify({"stream": stream.to_dict()}), 200


@stream_bp.route("/<stream_id>/end", methods=["POST"])
def end_stream(stream_id):
    """Terminate the stream and mark it as ended."""
    stream = stream_manager.end_stream(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found or already ended"}), 404

    return jsonify({"stream": stream.to_dict(), "message": "Stream ended"}), 200


@stream_bp.route("/<stream_id>/viewer-token", methods=["POST"])
def mint_viewer_token(stream_id):
    """Issue a LiveKit subscriber-only token for an authenticated viewer.

    Body (optional):
      identity: stable participant identifier (defaults to a derived id)
      display_name: shown to other participants

    No auth gate yet (matches existing route style); add when the broader
    auth story lands.
    """
    stream = stream_manager.get_stream(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found"}), 404
    if stream.status == "ended":
        return jsonify({"error": "Stream has ended"}), 410

    data = request.get_json(silent=True) or {}
    identity = data.get("identity") or f"viewer-{stream_id[:8]}-{request.remote_addr or 'anon'}"
    display_name = data.get("display_name")

    token = livekit_service.mint_access_token(
        room_name=stream.id,
        identity=identity,
        can_publish=False,
        can_subscribe=True,
        display_name=display_name,
    )
    return jsonify({
        "viewer_token": token,
        "livekit_url": stream.to_dict()["livekit_url"],
        "room_name": stream.id,
    }), 200


@stream_bp.route("/<stream_id>", methods=["GET"])
def get_stream(stream_id):
    """Get details for a specific stream."""
    stream = stream_manager.get_stream(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found"}), 404

    return jsonify({"stream": stream.to_dict()}), 200


@stream_bp.route("", methods=["GET"])
def list_streams():
    """List currently broadcasting streams (status = active)."""
    streams = (
        Stream.query.filter_by(status="active")
        .order_by(Stream.started_at.desc())
        .all()
    )
    return jsonify({
        "streams": [s.to_dict() for s in streams],
        "count": len(streams),
    }), 200


@stream_bp.route("/<stream_id>/like", methods=["POST"])
def like_stream(stream_id):
    """Increment a stream's like count.

    No auth in v1: any client can like, no per-user dedup.
    """
    from app.extensions import db
    stream = stream_manager.get_stream(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found"}), 404

    stream.like_count += 1
    db.session.commit()
    return jsonify({"like_count": stream.like_count}), 200
