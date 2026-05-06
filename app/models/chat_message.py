"""Chat messages associated with a stream."""

from datetime import datetime, timezone
from app.extensions import db


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stream_id = db.Column(
        db.String(36), db.ForeignKey("streams.id"), nullable=False, index=True
    )
    # When User model lands, change to ForeignKey("users.id") + relationship
    sender_name = db.Column(db.String(64), nullable=False, default="anonymous")
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )

    def to_dict(self):
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }