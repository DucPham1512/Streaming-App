"""Gesture mapping database model."""

from app.extensions import db


class GestureMapping(db.Model):
    """Maps a hand gesture name to a stream action."""

    __tablename__ = "gesture_mappings"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.String(36), nullable=False, default="default"
    )  # Placeholder until auth is implemented
    gesture = db.Column(
        db.String(50), nullable=False
    )  # e.g. "open_palm", "peace_sign", "thumbs_up"
    action = db.Column(
        db.String(50), nullable=False
    )  # e.g. "start_stream", "mute_mic", "switch_camera"

    # Ensure each user can only have one mapping per gesture
    __table_args__ = (
        db.UniqueConstraint("user_id", "gesture", name="uq_user_gesture"),
    )

    def to_dict(self):
        """Serialize the gesture mapping to a dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "gesture": self.gesture,
            "action": self.action,
        }
