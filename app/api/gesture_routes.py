"""REST API routes for gesture mappings + custom templates.

Endpoints
---------
Built-in gestures (rule-based detector in broadcaster/detector.py):
    GET    /api/v1/gestures               — list user's per-gesture action overrides
    POST   /api/v1/gestures               — upsert an action override
    DELETE /api/v1/gestures/<mapping_id>  — remove an override
    GET    /api/v1/gestures/defaults      — raw built-in defaults (no auth)
    GET    /api/v1/gestures/builtins      — built-ins merged with user's overrides
                                            (returns one row per built-in gesture
                                            with the EFFECTIVE action)

Custom user-recorded templates (k-NN — see decision-004):
    GET    /api/v1/gestures/templates             — list user's templates
    POST   /api/v1/gestures/templates             — create a template (after recording)
    PATCH  /api/v1/gestures/templates/<id>        — rename / re-map action
    DELETE /api/v1/gestures/templates/<id>        — delete

Shared:
    GET    /api/v1/gestures/actions       — curated action picker list for the FE
"""

from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models.gesture import GestureMapping
from app.models.gesture_template import GestureTemplate, HANDEDNESS_VALUES
from app.services.auth_service import require_auth

gesture_bp = Blueprint("gestures", __name__)

# The recognised gesture names (must match detector.py GESTURE_COMMANDS keys)
_VALID_GESTURES = frozenset([
    "open_palm", "fist", "thumbs_up", "peace", "finger_heart", "ily",
])

# The recognised action/command names (must match _COMMAND_EFFECTS in media_events.py).
# Templates accept the same set plus "unmapped" as a sentinel for freshly-recorded
# templates the streamer hasn't assigned an action to yet.
_VALID_ACTIONS = frozenset([
    "mute_toggle", "end_stream", "like_stream",
    "entertainment_confetti", "entertainment_heart", "entertainment_fireworks",
])
_VALID_TEMPLATE_ACTIONS = _VALID_ACTIONS | frozenset({"unmapped"})

# Curated picker list shown in the FE Gesture Library screen. The order
# here is also the order the picker presents to users — frequently-used
# entertainment effects first, destructive actions last.
ACTION_PICKER = [
    {"key": "entertainment_heart",      "label": "Heart burst",  "category": "effect"},
    {"key": "entertainment_confetti",   "label": "Confetti",     "category": "effect"},
    {"key": "entertainment_fireworks",  "label": "Fireworks",    "category": "effect"},
    {"key": "like_stream",              "label": "Like",         "category": "effect"},
    {"key": "mute_toggle",              "label": "Toggle mute",  "category": "control"},
    {"key": "end_stream",               "label": "End stream",   "category": "control"},
]

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


# ---------------------------------------------------------------------------
# Built-ins merged with user overrides (the read-side companion to the
# /api/v1/gestures upsert). One row per known built-in gesture; "action"
# is the effective action (override if present, default otherwise).
# ---------------------------------------------------------------------------

@gesture_bp.route("/api/v1/gestures/builtins", methods=["GET"])
@require_auth
def list_builtins_effective():
    overrides = {
        m.gesture: m.action
        for m in GestureMapping.query.filter_by(user_id=g.current_user.id).all()
    }
    rows = []
    for m in _DEFAULT_MAPPINGS:
        gesture = m["gesture"]
        default_action = m["action"]
        effective = overrides.get(gesture, default_action)
        rows.append({
            "gesture": gesture,
            "default_action": default_action,
            "action": effective,
            "is_overridden": gesture in overrides,
        })
    return jsonify({"builtins": rows}), 200


# ---------------------------------------------------------------------------
# Curated action picker — keeps the FE in sync with what the backend accepts.
# ---------------------------------------------------------------------------

@gesture_bp.route("/api/v1/gestures/actions", methods=["GET"])
def list_actions():
    return jsonify({"actions": ACTION_PICKER}), 200


# ---------------------------------------------------------------------------
# Custom user-recorded templates (k-NN)
# ---------------------------------------------------------------------------

_MAX_SAMPLES_PER_TEMPLATE = 50          # safety cap; usual recording is ~10
_LANDMARK_FLOATS_PER_SAMPLE = 63        # 21 landmarks × 3 coords


def _validate_landmarks(value):
    """Return (ok, error_message). Accepts list[list[float]] of correct shape."""
    if not isinstance(value, list) or not value:
        return False, "landmarks must be a non-empty list of frames"
    if len(value) > _MAX_SAMPLES_PER_TEMPLATE:
        return False, f"too many samples (max {_MAX_SAMPLES_PER_TEMPLATE})"
    for i, sample in enumerate(value):
        if not isinstance(sample, list) or len(sample) != _LANDMARK_FLOATS_PER_SAMPLE:
            return False, f"sample {i}: each frame must be a list of {_LANDMARK_FLOATS_PER_SAMPLE} floats"
        for x in sample:
            if not isinstance(x, (int, float)):
                return False, f"sample {i}: non-numeric value in landmarks"
    return True, ""


@gesture_bp.route("/api/v1/gestures/templates", methods=["GET"])
@require_auth
def list_templates():
    """List the authenticated user's custom gesture templates."""
    items = (
        GestureTemplate.query
        .filter_by(user_id=g.current_user.id)
        .order_by(GestureTemplate.created_at.desc())
        .all()
    )
    return jsonify({"templates": [t.to_dict() for t in items]}), 200


@gesture_bp.route("/api/v1/gestures/templates", methods=["POST"])
@require_auth
def create_template():
    """Save a freshly-recorded template.

    Body: {
        "name": "peace_double",
        "action": "entertainment_fireworks" | "unmapped",
        "handedness": "Left" | "Right" | "Any",
        "landmarks": [[63 floats], ...]
    }
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    action = (data.get("action") or "unmapped").strip().lower()
    handedness = (data.get("handedness") or "Any").strip()
    landmarks = data.get("landmarks")

    if not name:
        return jsonify({"error": "'name' is required"}), 400
    if len(name) > 80:
        return jsonify({"error": "'name' must be 80 chars or fewer"}), 400
    if action not in _VALID_TEMPLATE_ACTIONS:
        return jsonify(
            {"error": f"Unknown action '{action}'", "valid": sorted(_VALID_TEMPLATE_ACTIONS)}
        ), 400
    if handedness not in HANDEDNESS_VALUES:
        return jsonify(
            {"error": f"Unknown handedness '{handedness}'", "valid": sorted(HANDEDNESS_VALUES)}
        ), 400

    ok, msg = _validate_landmarks(landmarks)
    if not ok:
        return jsonify({"error": msg}), 400

    # Uniqueness: (user_id, name). 409 on conflict so the FE can prompt.
    existing = GestureTemplate.query.filter_by(
        user_id=g.current_user.id, name=name
    ).first()
    if existing is not None:
        return jsonify({
            "error": f"A template named '{name}' already exists",
            "template_id": existing.id,
        }), 409

    template = GestureTemplate(
        user_id=g.current_user.id,
        name=name,
        action=action,
        handedness=handedness,
        landmarks=landmarks,
    )
    db.session.add(template)
    db.session.commit()
    return jsonify({"template": template.to_dict()}), 201


@gesture_bp.route("/api/v1/gestures/templates/<int:template_id>", methods=["PATCH"])
@require_auth
def update_template(template_id):
    """Rename a template or re-map its action. Landmarks are immutable here;
    re-record instead if you want different sample data."""
    template = GestureTemplate.query.get(template_id)
    if template is None:
        return jsonify({"error": "Template not found"}), 404
    if template.user_id != g.current_user.id:
        return jsonify({"error": "You do not own this template"}), 403

    data = request.get_json(silent=True) or {}
    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            return jsonify({"error": "'name' cannot be empty"}), 400
        if len(new_name) > 80:
            return jsonify({"error": "'name' must be 80 chars or fewer"}), 400
        # Name collision with another template of the same user.
        clash = GestureTemplate.query.filter(
            GestureTemplate.user_id == g.current_user.id,
            GestureTemplate.name == new_name,
            GestureTemplate.id != template.id,
        ).first()
        if clash is not None:
            return jsonify({"error": f"A template named '{new_name}' already exists"}), 409
        template.name = new_name
    if "action" in data:
        action = (data["action"] or "").strip().lower()
        if action not in _VALID_TEMPLATE_ACTIONS:
            return jsonify(
                {"error": f"Unknown action '{action}'", "valid": sorted(_VALID_TEMPLATE_ACTIONS)}
            ), 400
        template.action = action
    if "handedness" in data:
        handedness = (data["handedness"] or "").strip()
        if handedness not in HANDEDNESS_VALUES:
            return jsonify(
                {"error": f"Unknown handedness '{handedness}'", "valid": sorted(HANDEDNESS_VALUES)}
            ), 400
        template.handedness = handedness

    db.session.commit()
    return jsonify({"template": template.to_dict()}), 200


@gesture_bp.route("/api/v1/gestures/templates/<int:template_id>", methods=["DELETE"])
@require_auth
def delete_template(template_id):
    template = GestureTemplate.query.get(template_id)
    if template is None:
        return jsonify({"error": "Template not found"}), 404
    if template.user_id != g.current_user.id:
        return jsonify({"error": "You do not own this template"}), 403
    db.session.delete(template)
    db.session.commit()
    return jsonify({"message": "Template deleted"}), 200
