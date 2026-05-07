"""Seed the development database with mock data.

All data is entirely fictional and carries no risk of real data leakage.
Run with:  .venv/bin/python seed.py

Story A: deterministic API keys for the seeded users so curl commands
remain stable across re-seeds (DEV ONLY — never used in production).
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta

from app import create_app
from app.extensions import db
from app.models.gesture import GestureMapping
from app.models.media import MediaItem
from app.models.stream import Stream
from app.models.user import User

app = create_app("development")
logger = logging.getLogger(__name__)

# --- Users ------------------------------------------------------------------

# Deterministic API keys: hash of "dev-{username}". DEV ONLY.
def _dev_key(username: str) -> str:
    return f"dev-{hashlib.sha256(f'dev-{username}'.encode()).hexdigest()[:32]}"


MOCK_USERS = [
    {
        "id": "00000000-0000-0000-0000-00000000aaaa",
        "username": "alpha",
        "display_name": "Alpha User",
        "email": "alpha@example.test",
        "bio": "Lo-fi streamer.",
        "api_key": _dev_key("alpha"),
    },
    {
        "id": "00000000-0000-0000-0000-00000000bbbb",
        "username": "beta",
        "display_name": "Beta Tester",
        "email": "beta@example.test",
        "bio": "Beta-testing the new content library.",
        "api_key": _dev_key("beta"),
    },
    {
        "id": "00000000-0000-0000-0000-00000000cccc",
        "username": "gamma",
        "display_name": "Gamma Vlogger",
        "email": "gamma@example.test",
        "bio": "Posts daily — Sao đen thui zậy.",
        "api_key": _dev_key("gamma"),
    },
]

# Existing gesture user_ids ("user-alpha", etc.) are unchanged because
# GestureMapping.user_id is currently a free-form string column.
MOCK_GESTURE_USER_IDS = ["user-alpha", "user-beta", "user-gamma"]

MOCK_STREAMS = [
    {
        "id": str(uuid.uuid4()),
        "title": "Lo-fi Coding Session",
        "description": "Late-night coding with ambient beats.",
        "privacy": "public",
        "status": "active",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "ended_at": None,
    },
    {
        "id": str(uuid.uuid4()),
        "title": "React Tutorial: Hooks Deep Dive",
        "description": "A comprehensive walkthrough of React hooks.",
        "privacy": "public",
        "status": "active",
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=30),
        "ended_at": None,
    },
    {
        "id": str(uuid.uuid4()),
        "title": "Private Dev Stream",
        "description": "Internal team planning session.",
        "privacy": "private",
        "status": "active",
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=15),
        "ended_at": None,
    },
    {
        "id": str(uuid.uuid4()),
        "title": "Game Jam: Day 1",
        "description": "Building a side-scroller in 48 hours.",
        "privacy": "public",
        "status": "ended",
        "created_at": datetime.now(timezone.utc) - timedelta(days=2),
        "ended_at": datetime.now(timezone.utc) - timedelta(days=1, hours=4),
    },
    {
        "id": str(uuid.uuid4()),
        "title": "Unlisted Q&A with Subscribers",
        "description": "Monthly subscriber Q&A, unlisted for link-only access.",
        "privacy": "unlisted",
        "status": "ended",
        "created_at": datetime.now(timezone.utc) - timedelta(days=5),
        "ended_at": datetime.now(timezone.utc) - timedelta(days=4, hours=22),
    },
]

GESTURE_DEFINITIONS = [
    ("open_palm", "start_stream"),
    ("closed_fist", "stop_stream"),
    ("peace_sign", "mute_mic"),
    ("thumbs_up", "switch_camera"),
    ("pointing_up", "increase_volume"),
    ("pointing_down", "decrease_volume"),
]

MOCK_GESTURE_MAPPINGS = [
    {"user_id": user, "gesture": gesture, "action": action}
    for user in MOCK_GESTURE_USER_IDS
    for gesture, action in GESTURE_DEFINITIONS
]


def seed() -> None:
    with app.app_context():
        GestureMapping.query.delete()
        MediaItem.query.delete()
        Stream.query.delete()
        User.query.delete()
        db.session.commit()

        for data in MOCK_USERS:
            db.session.add(User(**data))

        for data in MOCK_STREAMS:
            db.session.add(Stream(**data))

        for data in MOCK_GESTURE_MAPPINGS:
            db.session.add(GestureMapping(**data))

        db.session.commit()

        user_count = User.query.count()
        stream_count = Stream.query.count()
        gesture_count = GestureMapping.query.count()
        logger.info(
            f"Seeded {user_count} users, {stream_count} streams, "
            f"{gesture_count} gesture mappings."
        )
        logger.info("Dev API keys (use as 'Authorization: Bearer <key>'):")
        for u in User.query.order_by(User.username).all():
            logger.info("  %s  %s", f"{u.username:<8}", u.api_key)


if __name__ == "__main__":
    seed()
