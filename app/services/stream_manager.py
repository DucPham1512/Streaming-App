"""Stream lifecycle and state management service."""

import threading
from datetime import datetime, timezone
from typing import Optional

from app.extensions import db
from app.models.stream import Stream
from app.services import livekit_service


class StreamManager:
    def __init__(self):
        self._active_streams: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_stream(
        self,
        title: str = "Untitled Stream",
        description: str = "",
        privacy: str = "public",
        *,
        owner_identity: Optional[str] = None,
        owner_display_name: Optional[str] = None,
    ) -> tuple[Stream, str, str]:
        """Create a Stream row + provision the matching LiveKit room.

        Returns a tuple of (stream, publisher_token, livekit_url). The
        publisher_token is sensitive — return it only to the broadcaster
        that just initiated the stream.

        Raises livekit_service.LiveKitServiceError if the LiveKit API call fails.
        """
        # Insert the Stream row first so its UUID can name the LiveKit room.
        stream = Stream(
            title=title,
            description=description,
            privacy=privacy,
            status="idle",
        )
        db.session.add(stream)
        db.session.flush()  # populate stream.id without committing yet

        # If no identity was supplied (anonymous create), derive a stable one
        # from the stream id so reconnects land on the same participant slot.
        identity = owner_identity or f"publisher-{stream.id[:8]}"

        try:
            created = livekit_service.create_stream_room(
                stream_id=stream.id,
                owner_identity=identity,
                owner_display_name=owner_display_name,
            )
        except livekit_service.LiveKitServiceError:
            db.session.rollback()
            raise

        db.session.commit()
        return stream, created.publisher_token, created.livekit_url

    def update_stream(self, stream_id, **kwargs):
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None

        allowed = {"title", "description", "privacy"}
        for key, value in kwargs.items():
            if key in allowed:
                setattr(stream, key, value)

        db.session.commit()
        return stream

    def end_stream(self, stream_id: str):
        """Terminate a stream — deletes the LiveKit room + marks DB record ended."""
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None

        # Disconnect all participants by deleting the room (idempotent).
        try:
            livekit_service.delete_stream_room(stream.id)
        except livekit_service.LiveKitServiceError:
            # Log-and-continue: the DB state must reflect 'ended' even if
            # LiveKit cleanup fails; webhook reconciliation will catch up.
            pass

        stream.status = "ended"
        stream.ended_at = datetime.now(timezone.utc)
        db.session.commit()

        with self._lock:
            self._active_streams.pop(stream_id, None)

        return stream

    # ---- Webhook-driven state transitions ----
    #
    # These accept the local Stream.id (= LiveKit room name) — the webhook
    # handler resolves the LiveKit event's `room.name` to that before calling.

    def mark_connected(self, stream_id: str):
        """Publisher joined the room but hasn't published a track yet."""
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None
        # Only transition idle → connected; don't downgrade from active.
        if stream.status == "idle":
            stream.status = "connected"
            db.session.commit()
        return stream

    def mark_active(self, stream_id: str):
        """Publisher published a video track — stream is now watchable."""
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None

        stream.status = "active"
        if stream.started_at is None:
            stream.started_at = datetime.now(timezone.utc)
        db.session.commit()

        with self._lock:
            self._active_streams.setdefault(stream.id, {
                "connected_clients": set(),
                "created_at": stream.created_at,
            })
        return stream

    def mark_disconnected(self, stream_id: str):
        """Publisher participant left — transient; the room may still be reused."""
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None
        stream.status = "disconnected"
        db.session.commit()
        return stream

    def mark_ended(self, stream_id: str):
        """Room was finished (LiveKit `room_finished` event)."""
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None
        stream.status = "ended"
        stream.ended_at = datetime.now(timezone.utc)
        db.session.commit()

        with self._lock:
            self._active_streams.pop(stream.id, None)
        return stream

    # ---- In-memory active-clients registry (unchanged) ----

    def get_stream(self, stream_id):
        return db.session.get(Stream, stream_id)

    def is_active(self, stream_id):
        with self._lock:
            return stream_id in self._active_streams

    def add_client(self, stream_id, sid):
        with self._lock:
            if stream_id in self._active_streams:
                self._active_streams[stream_id]["connected_clients"].add(sid)
                return True
        return False

    def remove_client(self, stream_id, sid):
        with self._lock:
            if stream_id in self._active_streams:
                self._active_streams[stream_id]["connected_clients"].discard(sid)

    def get_active_stream_ids(self):
        with self._lock:
            return list(self._active_streams.keys())


stream_manager = StreamManager()
