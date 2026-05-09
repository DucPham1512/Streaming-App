"""Follow model — Member 4: Social Interaction."""

from datetime import datetime, timezone

from app.extensions import db


class Follow(db.Model):
    __tablename__ = "follows"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    follower_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False, index=True
    )
    followed_id = db.Column(
        db.String(36), db.ForeignKey("users.id"), nullable=False, index=True
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint("follower_id", "followed_id", name="uq_follows_pair"),
    )

    follower = db.relationship("User", foreign_keys=[follower_id], lazy="joined")
    followed = db.relationship("User", foreign_keys=[followed_id], lazy="joined")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "follower_id": self.follower_id,
            "followed_id": self.followed_id,
            "created_at": self.created_at.isoformat(),
        }
