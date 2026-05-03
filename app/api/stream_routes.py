"""REST API routes for livestream session management.

Endpoints
---------
POST   /api/v1/streams              — Create a new stream
PATCH  /api/v1/streams/<stream_id>  — Update stream metadata
POST   /api/v1/streams/<stream_id>/end — End (terminate) a stream
GET    /api/v1/streams/<stream_id>  — Get stream details (convenience)
GET    /api/v1/streams              — List active streams (convenience)
"""

from flask import Blueprint, request, jsonify

from app.services.stream_manager import stream_manager

stream_bp = Blueprint("streams", __name__, url_prefix="/api/v1/streams")


@stream_bp.route("", methods=["POST"])
def create_stream():
    """Initialize a new livestream session.

    Request JSON (all optional):
        - title (str)
        - description (str)
        - privacy (str): "public" | "private" | "unlisted"

    Returns:
        201 with stream data + a ws_token placeholder.
    """
    data = request.get_json(silent=True) or {}

    title = data.get("title", "Untitled Stream")
    description = data.get("description", "")
    privacy = data.get("privacy", "public")

    if privacy not in ("public", "private", "unlisted"):
        return jsonify({"error": "privacy must be public, private, or unlisted"}), 400

    stream = stream_manager.create_stream(
        title=title, description=description, privacy=privacy
    )

    return (
        jsonify(
            {
                "stream": stream.to_dict(),
                "ws_token": f"ws-token-{stream.id[:8]}",  # placeholder token
            }
        ),
        201,
    )


@stream_bp.route("/<stream_id>", methods=["PATCH"])
def update_stream(stream_id):
    """Update stream metadata (title, description, privacy).

    Returns:
        200 with updated stream data, or 404.
    """
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
    """Terminate the stream and mark it as ended.

    Returns:
        200 with ended stream data, or 404.
    """
    stream = stream_manager.end_stream(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found or already ended"}), 404

    return jsonify({"stream": stream.to_dict(), "message": "Stream ended"}), 200


@stream_bp.route("/<stream_id>", methods=["GET"])
def get_stream(stream_id):
    """Get details for a specific stream."""
    stream = stream_manager.get_stream(stream_id)
    if stream is None:
        return jsonify({"error": "Stream not found"}), 404

    return jsonify({"stream": stream.to_dict()}), 200


@stream_bp.route("", methods=["GET"])
def list_streams():
    """List all active stream IDs with their metadata."""
    active_ids = stream_manager.get_active_stream_ids()
    streams = []
    for sid in active_ids:
        stream = stream_manager.get_stream(sid)
        if stream:
            streams.append(stream.to_dict())

    return jsonify({"streams": streams, "count": len(streams)}), 200
