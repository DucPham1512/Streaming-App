"""Stream database model."""

import os
import uuid
from datetime import datetime, timezone

from app.extensions import db


class Stream(db.Model):
    """Represents a livestream session backed by LiveKit.

    Stream.id doubles as the LiveKit room name (a UUID) — see
    docs/decisions/001-livekit-over-mux.md.
    """

    __tablename__ = "streams"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255), nullable=False, default="Untitled Stream")
    description = db.Column(db.Text, nullable=True, default="")
    privacy = db.Column(
        db.String(20), nullable=False, default="public"
    )  # public / private / unlisted

    # Lifecycle states:
    #   idle         — created, never broadcast
    #   active       — currently broadcasting
    #   disconnected — temporarily lost (don't end yet, may reconnect)
    #   ended        — terminated, will not resume
    status = db.Column(db.String(20), nullable=False, default="idle")

    like_count = db.Column(db.Integer, nullable=False, default=0)

    # Optional owner info set at stream creation time.
    # owner_identity is the LiveKit participant identity (often a username).
    # owner_display_name is the human-readable name shown in the viewer UI.
    owner_identity = db.Column(db.String(255), nullable=True)
    owner_display_name = db.Column(db.String(128), nullable=True)

    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "privacy": self.privacy,
            "status": self.status,
            # Stream.id doubles as the LiveKit room name.
            "room_name": self.id,
            "livekit_url": os.environ.get("LIVEKIT_URL", ""),
            "like_count": self.like_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "owner_identity": self.owner_identity,
            "owner_display_name": self.owner_display_name,
        }