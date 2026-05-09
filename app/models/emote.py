"""Emote model — Member 4: Social Interaction."""

from datetime import datetime, timezone

from app.extensions import db

VALID_EMOTE_TYPES = {"heart", "fire", "clap", "laugh", "wow", "sad"}


class Emote(db.Model):
    __tablename__ = "emotes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stream_id = db.Column(
        db.String(36), db.ForeignKey("streams.id"), nullable=False, index=True
    )
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False, index=True
    )
    emote_type = db.Column(db.String(32), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    user = db.relationship("User", lazy="joined", foreign_keys=[user_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "user_id": self.user_id,
            "username": self.user.username if self.user else None,
            "emote_type": self.emote_type,
            "created_at": self.created_at.isoformat(),
        }
