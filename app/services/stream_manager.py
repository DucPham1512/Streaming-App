"""Stream lifecycle and state management service.

Keeps an in-memory registry of active streams alongside the persistent
database records.  This lets WebSocket handlers check stream liveness
without hitting the DB on every frame.
"""

import threading
from datetime import datetime, timezone

from app.extensions import db
from app.models.stream import Stream


class StreamManager:
    """Manages the lifecycle of livestream sessions."""

    def __init__(self):
        # thread-safe set of currently active stream IDs
        self._active_streams: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_stream(self, title="Untitled Stream", description="", privacy="public"):
        """Create a new stream and persist it to the database.

        Returns the created Stream model instance.
        """
        stream = Stream(title=title, description=description, privacy=privacy)
        db.session.add(stream)
        db.session.commit()

        with self._lock:
            self._active_streams[stream.id] = {
                "connected_clients": set(),
                "created_at": stream.created_at,
            }

        return stream

    def update_stream(self, stream_id, **kwargs):
        """Update mutable metadata on a stream.

        Allowed fields: title, description, privacy.
        Returns the updated Stream or None if not found.
        """
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None

        allowed = {"title", "description", "privacy"}
        for key, value in kwargs.items():
            if key in allowed:
                setattr(stream, key, value)

        db.session.commit()
        return stream

    def end_stream(self, stream_id):
        """Terminate a stream — marks it as ended in the DB and removes
        it from the in-memory active registry.

        Returns the ended Stream or None if not found / already ended.
        """
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None

        stream.status = "ended"
        stream.ended_at = datetime.now(timezone.utc)
        db.session.commit()

        with self._lock:
            self._active_streams.pop(stream_id, None)

        return stream

    def get_stream(self, stream_id):
        """Retrieve a stream by ID."""
        return db.session.get(Stream, stream_id)

    def is_active(self, stream_id):
        """Check whether a stream is currently active (in-memory)."""
        with self._lock:
            return stream_id in self._active_streams

    def add_client(self, stream_id, sid):
        """Register a WebSocket client in a stream room."""
        with self._lock:
            if stream_id in self._active_streams:
                self._active_streams[stream_id]["connected_clients"].add(sid)
                return True
        return False

    def remove_client(self, stream_id, sid):
        """Unregister a WebSocket client from a stream room."""
        with self._lock:
            if stream_id in self._active_streams:
                self._active_streams[stream_id]["connected_clients"].discard(sid)

    def get_active_stream_ids(self):
        """Return a list of currently active stream IDs."""
        with self._lock:
            return list(self._active_streams.keys())


# Module-level singleton — imported by route / socket handlers
stream_manager = StreamManager()
