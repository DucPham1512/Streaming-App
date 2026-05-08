"""User database model.

Foundation primitive: owned by the whole app, not Feature 5.

Designed rich (display_name, email, avatar, bio, dob) so that the upcoming
Profile feature does not require another migration. Auth credential is a
single API key; real login/registration ships in a follow-up.
"""

import secrets
import uuid
from datetime import datetime, timezone

from app.extensions import db


def _generate_api_key() -> str:
    """Generate a random 32-byte hex API key."""
    return secrets.token_hex(32)


class User(db.Model):
    """A registered user of the streaming app."""

    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(128), nullable=True)
    email = db.Column(db.String(254), unique=True, nullable=True, index=True)
    avatar_media_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "media_items.id",
            name="fk_users_avatar_media_id",
            use_alter=True,
        ),
        nullable=True,
    )
    bio = db.Column(db.Text, nullable=True)
    dob = db.Column(db.Date, nullable=True)
    api_key = db.Column(
        db.String(64),
        unique=True,
        nullable=False,
        index=True,
        default=_generate_api_key,
    )
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

    def to_dict(self, *, include_api_key: bool = False) -> dict:
        """Serialize the user to a dictionary.

        api_key is excluded by default — only the user themselves should ever
        see their own key (e.g. on creation or rotation).
        """
        data = {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "avatar_media_id": self.avatar_media_id,
            "bio": self.bio,
            "dob": self.dob.isoformat() if self.dob else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_api_key:
            data["api_key"] = self.api_key
        return data
