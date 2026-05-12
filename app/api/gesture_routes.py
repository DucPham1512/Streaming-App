"""REST API routes for gesture mappings — Member 3: VSR / Gesture.

Endpoints
---------
GET    /api/v1/gestures               — List the current user's gesture mappings
POST   /api/v1/gestures               — Create or update a gesture mapping
DELETE /api/v1/gestures/<mapping_id>  — Remove a gesture mapping
GET    /api/v1/gestures/defaults      — List the built-in default gesture→command mappings
"""

from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models.gesture import GestureMapping
from app.services.auth_service import require_auth

gesture_bp = Blueprint("gestures", __name__)

# The recognised gesture names (must match detector.py GESTURE_COMMANDS keys)
_VALID_GESTURES = frozenset([
    "open_palm", "fist", "thumbs_up", "peace", "finger_heart", "ily",
])

# The recognised action/command names (must match _COMMAND_EFFECTS in media_events.py)
_VALID_ACTIONS = frozenset([
    "mute_toggle", "end_stream", "like_stream",
    "entertainment_confetti", "entertainment_heart", "entertainment_fireworks",
])

_DEFAULT_MAPPINGS = [
    {"gesture": "open_palm",    "action": "mute_toggle"},
    {"gesture": "fist",         "action": "end_stream"},
    {"gesture": "thumbs_up",    "action": "like_stream"},
    {"gesture": "peace",        "action": "entertainment_confetti"},
    {"gesture": "finger_heart", "action": "entertainment_heart"},
    {"gesture": "ily",          "action": "entertainment_fireworks"},
]


@gesture_bp.route("/api/v1/gestures/defaults", methods=["GET"])
def list_defaults():
    """Return the built-in default gesture→action mappings. No auth required."""
    return jsonify({"mappings": _DEFAULT_MAPPINGS}), 200


@gesture_bp.route("/api/v1/gestures", methods=["GET"])
@require_auth
def list_mappings():
    """List all gesture mappings for the authenticated user."""
    mappings = GestureMapping.query.filter_by(user_id=g.current_user.id).all()
    return jsonify({"mappings": [m.to_dict() for m in mappings]}), 200


@gesture_bp.route("/api/v1/gestures", methods=["POST"])
@require_auth
def upsert_mapping():
    """Create or update a gesture→action mapping for the authenticated user.

    Body: {"gesture": "peace", "action": "entertainment_confetti"}

    If a mapping for this gesture already exists it is updated (upsert).
    """
    data = request.get_json(silent=True) or {}
    gesture = data.get("gesture", "").strip().lower()
    action = data.get("action", "").strip().lower()

    if not gesture:
        return jsonify({"error": "'gesture' is required"}), 400
    if gesture not in _VALID_GESTURES:
        return jsonify({"error": f"Unknown gesture '{gesture}'",
                        "valid": sorted(_VALID_GESTURES)}), 400
    if not action:
        return jsonify({"error": "'action' is required"}), 400
    if action not in _VALID_ACTIONS:
        return jsonify({"error": f"Unknown action '{action}'",
                        "valid": sorted(_VALID_ACTIONS)}), 400

    mapping = GestureMapping.query.filter_by(
        user_id=g.current_user.id, gesture=gesture
    ).first()

    if mapping:
        mapping.action = action
    else:
        mapping = GestureMapping(
            user_id=g.current_user.id,
            gesture=gesture,
            action=action,
        )
        db.session.add(mapping)

    db.session.commit()
    return jsonify({"mapping": mapping.to_dict()}), 200


@gesture_bp.route("/api/v1/gestures/<int:mapping_id>", methods=["DELETE"])
@require_auth
def delete_mapping(mapping_id):
    """Delete a gesture mapping. Only the owner can delete it."""
    mapping = GestureMapping.query.get(mapping_id)
    if mapping is None:
        return jsonify({"error": "Gesture mapping not found"}), 404
    if mapping.user_id != g.current_user.id:
        return jsonify({"error": "You do not own this mapping"}), 403

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Gesture mapping deleted"}), 200
