"""Gesture event log database model."""

from datetime import datetime, timezone

from app.extensions import db


class GestureLog(db.Model):
    """Records every gesture event received during a stream."""

    __tablename__ = "gesture_logs"

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.String(36), nullable=False)
    user_id = db.Column(db.String(36), nullable=False, default="default")
    gesture = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "user_id": self.user_id,
            "gesture": self.gesture,
            "action": self.action,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
