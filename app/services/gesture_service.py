"""Gesture resolution service.

Looks up a gesture string in the GestureMapping table and returns the
mapped action. Also provides helpers to classify action types.
"""

from app.models.gesture import GestureMapping


def resolve_gesture(gesture: str, user_id: str = "default") -> str | None:
    """Return the action mapped to `gesture` for `user_id`, or None if unmapped."""
    mapping = GestureMapping.query.filter_by(user_id=user_id, gesture=gesture).first()
    return mapping.action if mapping else None


def is_effect(action: str) -> bool:
    """Return True if the action is an entertainment effect (prefixed with 'effect:')."""
    return action.startswith("effect:")


def get_effect_name(action: str) -> str:
    """Strip the 'effect:' prefix and return the bare effect name."""
    return action.removeprefix("effect:")
