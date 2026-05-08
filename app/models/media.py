"""MediaItem database model.

Feature 5 model. Owns metadata for objects stored in MinIO.

Key invariants:
    - storage_key is generated, never derived from user input
    - deleted_at is the source of truth for liveness (NULL = active)
      (chosen over a `status` column to avoid colliding with Stream.status)
    - mimetype is the SNIFFED value, not the request Content-Type
    - owner_id is a non-null FK to users.id
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


VISIBILITY_VALUES = ("public", "private", "unlisted")


class MediaItem(db.Model):
    """A piece of user-uploaded media stored in MinIO."""

    __tablename__ = "media_items"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    original_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)

    storage_bucket = db.Column(db.String(128), nullable=False)
    storage_key = db.Column(db.String(512), nullable=False)

    title = db.Column(db.String(255), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    visibility = db.Column(db.String(20), nullable=False, default="private")

    # Phase 2 metadata (gated by MEDIA_EXTRACT_METADATA config flag).
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    thumbnail_key = db.Column(db.String(512), nullable=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    __table_args__ = (
        db.Index(
            "ix_media_items_owner_deleted_created",
            "owner_id",
            "deleted_at",
            "created_at",
        ),
    )

    def to_dict(self) -> dict:
        """Serialize to the canonical API shape (matches D8 + Step 5)."""
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "original_filename": self.original_filename,
            "mimetype": self.mimetype,
            "file_size": self.file_size,
            "title": self.title,
            "description": self.description,
            "visibility": self.visibility,
            "storage_bucket": self.storage_bucket,
            "storage_key": self.storage_key,
            "width": self.width,
            "height": self.height,
            "thumbnail_key": self.thumbnail_key,
            "stream_url": f"/api/v1/media/{self.id}/stream",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
