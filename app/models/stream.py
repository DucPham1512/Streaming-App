"""Stream database model."""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class Stream(db.Model):
    """Represents a livestream session."""

    __tablename__ = "streams"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255), nullable=False, default="Untitled Stream")
    description = db.Column(db.Text, nullable=True, default="")
    privacy = db.Column(
        db.String(20), nullable=False, default="public"
    )  # public / private / unlisted
    status = db.Column(
        db.String(20), nullable=False, default="active"
    )  # active / ended
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    ended_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        """Serialize the stream to a dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "privacy": self.privacy,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }
