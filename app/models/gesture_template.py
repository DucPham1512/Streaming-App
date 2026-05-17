"""User-recorded gesture template (k-NN landmark snapshot).

Companion to the simpler GestureMapping (per-user overrides of built-in
gestures). A GestureTemplate represents a NEW custom gesture the streamer
recorded, not a remapping of an existing one.

See docs/decisions/004-knn-gesture-templates.md for the rationale: a
small handful of frames (default 10) of normalized hand landmarks is
matched at runtime via nearest-neighbor distance to identify the
gesture. The classifier itself lives in the broadcaster process, not
here — this table is just storage.
"""

from datetime import datetime, timezone

from app.extensions import db


# Allowed values for `handedness`. "Any" means the template matches
# either hand (the classifier mirrors the X coordinate for the opposite
# hand at match time).
HANDEDNESS_VALUES = frozenset({"Left", "Right", "Any"})


class GestureTemplate(db.Model):
    """A recorded custom gesture, owned by a single user."""

    __tablename__ = "gesture_templates"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    # Human-readable label the streamer types in when recording. Unique
    # per user so the FE can show stable rows and the broadcaster can
    # name an effect by template name later.
    name = db.Column(db.String(80), nullable=False)

    # Effect / command the gesture should fire. Must be in the curated
    # action list (see app/api/gesture_routes.py _VALID_ACTIONS). May be
    # the literal "unmapped" sentinel right after recording, before the
    # streamer assigns one via the FE.
    action = db.Column(db.String(50), nullable=False, default="unmapped")

    # "Left" / "Right" / "Any". See HANDEDNESS_VALUES.
    handedness = db.Column(db.String(8), nullable=False, default="Any")

    # JSON array of recorded sample frames. Each sample is a flat list
    # of 63 floats (21 landmarks × {x, y, z}), normalized wrist-centered
    # palm-scale-invariant by the broadcaster before saving. ~10 samples
    # per template is the recommended capture size.
    landmarks = db.Column(db.JSON, nullable=False)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_user_template_name"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "action": self.action,
            "handedness": self.handedness,
            # Caller decides whether to include landmarks (large). Default
            # to including so the broadcaster can use this directly.
            "landmarks": self.landmarks,
            "sample_count": len(self.landmarks or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
