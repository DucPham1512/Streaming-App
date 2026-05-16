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

    # Status now mirrors Mux lifecycle states:
    #   idle         — created, never broadcast
    #   active       — currently broadcasting
    #   disconnected — temporarily lost (don't end yet, may reconnect)
    #   ended        — terminated, will not resume
    status = db.Column(db.String(20), nullable=False, default="idle")

    # ---- Mux integration fields (DEPRECATED — dropped in Commit 5) ----
    # No longer written or read. Kept temporarily so the schema doesn't change
    # mid-PR. Removed by an Alembic migration once Commits 3 and 4 land.
    mux_stream_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    mux_playback_id = db.Column(db.String(64), nullable=True)
    mux_stream_key = db.Column(db.String(128), nullable=True)
    like_count = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    started_at = db.Column(db.DateTime, nullable=True)  # set when Mux fires 'active'
    ended_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self, include_secrets: bool = False):
        """Serialize the stream for API responses.

        :param include_secrets: kept for source compatibility; no per-stream
                                secrets live on the model anymore. Publisher
                                tokens are minted per-request by the route
                                layer (see app/services/livekit_service.py).
        """
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
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }