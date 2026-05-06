"""REST API routes for gesture configuration.

Endpoints
---------
GET  /api/v1/settings/gestures       — Fetch gesture → action mappings
PUT  /api/v1/settings/gestures       — Replace / update gesture mappings
GET  /api/v1/settings/gesture-logs   — Query gesture event log for a stream
"""

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models.gesture import GestureMapping
from app.models.gesture_log import GestureLog

config_bp = Blueprint("config", __name__, url_prefix="/api/v1/settings")

# Default gesture mappings seeded on first GET if table is empty.
# Actions prefixed with "effect:" are entertainment effects rendered client-side.
DEFAULT_GESTURES = {
    "open_palm": "start_stream",
    "closed_fist": "stop_stream",
    "peace_sign": "mute_mic",
    "thumbs_up": "switch_camera",
    "thumbs_down": "end_stream",
    "heart_gesture": "effect:heart",
    "victory_sign": "effect:confetti",
}


def _seed_defaults(user_id="default"):
    """Seed the default gesture mappings for a user if none exist."""
    existing = GestureMapping.query.filter_by(user_id=user_id).count()
    if existing == 0:
        for gesture, action in DEFAULT_GESTURES.items():
            db.session.add(
                GestureMapping(user_id=user_id, gesture=gesture, action=action)
            )
        db.session.commit()


@config_bp.route("/gestures", methods=["GET"])
def get_gestures():
    """Fetch the user's gesture → action mappings.

    Query params:
        - user_id (str, default "default")

    Returns:
        200 with list of gesture mappings.
    """
    user_id = request.args.get("user_id", "default")

    # Seed defaults on first access
    _seed_defaults(user_id)

    mappings = GestureMapping.query.filter_by(user_id=user_id).all()
    return (
        jsonify(
            {
                "user_id": user_id,
                "gestures": {m.gesture: m.action for m in mappings},
                "mappings": [m.to_dict() for m in mappings],
            }
        ),
        200,
    )


@config_bp.route("/gestures", methods=["PUT"])
def update_gestures():
    """Update custom gesture → action mappings.

    Request JSON:
        {
            "user_id": "default",           // optional
            "gestures": {
                "open_palm": "mute_mic",    // update existing
                "wave": "say_hello"         // add new
            }
        }

    Returns:
        200 with the full updated mappings list.
    """
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id", "default")
    gestures = data.get("gestures")

    if not gestures or not isinstance(gestures, dict):
        return (
            jsonify(
                {
                    "error": "Request body must include 'gestures' as a dict of gesture → action pairs"
                }
            ),
            400,
        )

    for gesture, action in gestures.items():
        existing = GestureMapping.query.filter_by(
            user_id=user_id, gesture=gesture
        ).first()

        if existing:
            existing.action = action
        else:
            db.session.add(
                GestureMapping(user_id=user_id, gesture=gesture, action=action)
            )

    db.session.commit()

    # Return the full set of mappings
    all_mappings = GestureMapping.query.filter_by(user_id=user_id).all()
    return (
        jsonify(
            {
                "user_id": user_id,
                "gestures": {m.gesture: m.action for m in all_mappings},
                "mappings": [m.to_dict() for m in all_mappings],
            }
        ),
        200,
    )


@config_bp.route("/gesture-logs", methods=["GET"])
def get_gesture_logs():
    """Fetch recent gesture event logs for a stream.

    Query params:
        - stream_id (str, required)
        - limit (int, default 50, max 200)

    Returns:
        200 with list of gesture log entries, newest first.
        400 if stream_id is missing.
    """
    stream_id = request.args.get("stream_id")
    if not stream_id:
        return jsonify({"error": "'stream_id' query parameter is required"}), 400

    limit = min(int(request.args.get("limit", 50)), 200)

    logs = (
        GestureLog.query
        .filter_by(stream_id=stream_id)
        .order_by(GestureLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"stream_id": stream_id, "logs": [log.to_dict() for log in logs]}), 200
