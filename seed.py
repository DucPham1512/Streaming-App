"""Seed the development database with mock data.

All data is entirely fictional and carries no risk of real data leakage.
Run with:  .venv/bin/python seed.py
"""

import uuid
from datetime import datetime, timezone, timedelta

from app import create_app
from app.extensions import db
from app.models.stream import Stream
from app.models.gesture import GestureMapping

app = create_app("development")

MOCK_USERS = ["user-alpha", "user-beta", "user-gamma"]

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
    for user in MOCK_USERS
    for gesture, action in GESTURE_DEFINITIONS
]


def seed() -> None:
    with app.app_context():
        GestureMapping.query.delete()
        Stream.query.delete()
        db.session.commit()

        for data in MOCK_STREAMS:
            db.session.add(Stream(**data))

        for data in MOCK_GESTURE_MAPPINGS:
            db.session.add(GestureMapping(**data))

        db.session.commit()

        stream_count = Stream.query.count()
        gesture_count = GestureMapping.query.count()
        print(f"Seeded {stream_count} streams and {gesture_count} gesture mappings.")


if __name__ == "__main__":
    seed()
