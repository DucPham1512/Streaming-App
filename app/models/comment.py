"""Comment model — Member 4: Social Interaction."""

from datetime import datetime, timezone

from app.extensions import db


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stream_id = db.Column(
        db.String(36), db.ForeignKey("streams.id"), nullable=False, index=True
    )
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False, index=True
    )
    content = db.Column(db.String(500), nullable=False)
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
            "display_name": self.user.display_name if self.user else None,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }
