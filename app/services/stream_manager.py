"""Stream lifecycle and state management service."""

import threading
from datetime import datetime, timezone

from app.extensions import db
from app.models.stream import Stream
from app.services import mux_service


class StreamManager:
    def __init__(self):
        self._active_streams: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_stream(self, title="Untitled Stream", description="", privacy="public", user=None):
        """Create a livestream session.

        Each user gets one persistent Mux live stream. The first call provisions
        it and stores stream_key + mux_stream_id on the user. Subsequent calls
        reuse the same Mux resource so the broadcaster's RTMP credentials never
        change and prior sessions have no playback.

        Raises mux_service.MuxServiceError if a Mux API call is required and fails.
        """
        if user is not None and user.mux_stream_id:
            # Reuse the user's existing Mux live stream — no new API call needed.
            mux_stream_id = user.mux_stream_id
            mux_stream_key = user.stream_key
            # Retrieve the playback ID from the first stream record that has one.
            original = (
                Stream.query
                .filter(
                    Stream.mux_stream_id == mux_stream_id,
                    Stream.mux_playback_id.isnot(None),
                )
                .first()
            )
            mux_playback_id = original.mux_playback_id if original else None
        else:
            mux_stream = mux_service.create_live_stream()
            mux_stream_id = mux_stream.mux_stream_id
            mux_stream_key = mux_stream.stream_key
            mux_playback_id = mux_stream.playback_id

            if user is not None:
                user.stream_key = mux_stream_key
                user.mux_stream_id = mux_stream_id

        stream = Stream(
            title=title,
            description=description,
            privacy=privacy,
            status="idle",
            mux_stream_id=mux_stream_id,
            mux_playback_id=mux_playback_id,
            mux_stream_key=mux_stream_key,
        )
        db.session.add(stream)
        db.session.commit()
        return stream

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

    def end_stream(self, stream_id):
        """Terminate a stream — signals Mux + marks DB record ended."""
        stream = db.session.get(Stream, stream_id)
        if stream is None or stream.status == "ended":
            return None

        # Tell Mux to disconnect the broadcaster (idempotent)
        if stream.mux_stream_id:
            try:
                mux_service.end_live_stream(stream.mux_stream_id)
            except mux_service.MuxServiceError:
                # Log but don't block the local end — Mux state will reconcile via webhook
                pass

        stream.status = "ended"
        stream.ended_at = datetime.now(timezone.utc)
        db.session.commit()

        with self._lock:
            self._active_streams.pop(stream_id, None)

        return stream

    # ---- Webhook-driven state transitions ----

    def mark_active(self, mux_stream_id: str):
        """Called by webhook handler on 'video.live_stream.active'."""
        stream = (
            Stream.query
            .filter(Stream.mux_stream_id == mux_stream_id, Stream.status != "ended")
            .order_by(Stream.created_at.desc())
            .first()
        )
        if stream is None:
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

    def mark_disconnected(self, mux_stream_id: str):
        """Called on 'video.live_stream.disconnected' — temporary state, do NOT end."""
        stream = (
            Stream.query
            .filter(
                Stream.mux_stream_id == mux_stream_id,
                Stream.status.in_(["active", "connected"]),
            )
            .order_by(Stream.created_at.desc())
            .first()
        )
        if stream is None:
            return None
        stream.status = "disconnected"
        db.session.commit()
        return stream

    def mark_idle(self, mux_stream_id: str):
        """Called on 'video.live_stream.idle' — Mux's reconnect window expired.

        Only end streams that actually started (active/connected/disconnected).
        A freshly-created stream sitting in 'idle' status was never connected,
        so an idle webhook from a prior session must not kill it.
        """
        stream = (
            Stream.query
            .filter(
                Stream.mux_stream_id == mux_stream_id,
                Stream.status.in_(["active", "connected", "disconnected"]),
            )
            .order_by(Stream.created_at.desc())
            .first()
        )
        if stream is None:
            return None
        stream.status = "ended"
        stream.ended_at = datetime.now(timezone.utc)
        db.session.commit()

        with self._lock:
            self._active_streams.pop(stream.id, None)
        return stream

    # ---- Existing in-memory registry methods (unchanged) ----

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
        
    def mark_connected(self, mux_stream_id: str):
        """Called on 'video.live_stream.connected' — broadcaster connected but not yet active."""
        stream = (
            Stream.query
            .filter(Stream.mux_stream_id == mux_stream_id, Stream.status != "ended")
            .order_by(Stream.created_at.desc())
            .first()
        )
        if stream is None:
            return None
        # Only transition idle → connected; don't downgrade from active
        if stream.status == "idle":
            stream.status = "connected"
            db.session.commit()
        return stream

stream_manager = StreamManager()