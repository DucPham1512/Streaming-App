"""
Socket.IO client that sends gesture commands to the Flask backend.
Includes per-command cooldown so a held gesture doesn't spam the server.
"""

import time
import threading
import socketio

# Default cooldowns per command (seconds)
COMMAND_COOLDOWNS: dict[str, float] = {
    "mute_toggle":             2.5,
    "end_stream":              0.0,   # controlled by hold logic in demo.py
    "like_stream":             2.0,
    "entertainment_confetti":  3.0,
    "entertainment_heart":     2.0,
    "entertainment_fireworks": 3.0,
}

DEFAULT_COOLDOWN = 2.0


class GestureClient:
    """
    Thread-safe Socket.IO client with per-command cooldown.
    Commands are dropped (not queued) when the cooldown has not elapsed.
    """

    def __init__(
        self,
        socket_url: str,
        api_key: str | None = None,
        *,
        on_comment=None,
        on_recording_start=None,
        on_streamer_authenticated=None,
    ):
        """
        :param on_comment: optional callback ``fn(username: str, content: str)``
            invoked for each `comment_received` socket event the streamer
            sees in their room. Used by demo.py to feed the local OpenCV
            comment overlay (broadcaster/local_view.CommentBuffer).
        :param on_recording_start: optional callback ``fn(name: str)`` invoked
            when the streamer dashboard fires a `recording_start` event.
            Runs on the socket.io background thread — the consumer must
            hand off to the capture loop's thread (e.g. via a queue).
        :param on_streamer_authenticated: optional callback
            ``fn(api_key: str, user_id: str, username: str)`` invoked when
            the dashboard's login propagates over. Runs on the socket.io
            thread; the consumer should hand off as above.
        """
        self._url = socket_url
        self._api_key = api_key
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()
        self._connected = False
        self._on_comment = on_comment
        self._on_recording_start = on_recording_start
        self._on_streamer_authenticated = on_streamer_authenticated

        self._sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._sio.on("connect", self._on_connect)
        self._sio.on("disconnect", self._on_disconnect)
        self._sio.on("gesture_ack", self._on_ack)
        self._sio.on("connect_error", self._on_error)
        self._sio.on("error", lambda d: print(f"[GestureClient] SERVER ERROR: {d}"))
        if on_comment is not None:
            self._sio.on("comment_received", self._on_comment_received)
        if on_recording_start is not None:
            self._sio.on("recording_start", self._on_recording_start_event)
        if on_streamer_authenticated is not None:
            self._sio.on("streamer_authenticated", self._on_streamer_authenticated_event)

    def set_api_key(self, api_key: str | None) -> None:
        """Swap the bearer token. Takes effect on the next reconnect.

        The python-socketio client doesn't support changing handshake
        headers mid-connection, so we just store the new key and rely on
        the next reconnect (or the streamer not caring that gesture_ack
        events for the next 30s might still be unauthenticated, since
        the per-user gesture handlers run REST-side via ApiClient).
        """
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            self._sio.connect(self._url, headers=headers, wait_timeout=5)
        except Exception as e:
            print(f"[GestureClient] Connection failed: {e}")

    def disconnect(self):
        if self._sio.connected:
            self._sio.disconnect()

    def join_room(self, stream_id: str) -> bool:
        """Join the Socket.IO room for `stream_id` so we receive room-scoped
        events (chat comments, viewer counts, etc.) emitted to that room."""
        if not self._connected:
            print("[GestureClient] join_room: not connected")
            return False
        try:
            self._sio.emit("join_room", {"stream_id": stream_id, "kind": "broadcaster"})
            return True
        except Exception as e:
            print(f"[GestureClient] join_room error: {e}")
            return False

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_gesture(
        self,
        command: str,
        stream_id: str,
        confidence: float = 0.95,
        anchor: tuple[float, float] | None = None,
        secondary: tuple[float, float] | None = None,
    ) -> bool:
        """
        Emit gesture_command_received.
        anchor/secondary: normalized (x, y) in [0, 1] from the webcam frame.
        Returns True if sent, False if on cooldown or not connected.
        """
        if not self._connected:
            print(f"[GestureClient] DROP {command}: not connected")
            return False

        cooldown = COMMAND_COOLDOWNS.get(command, DEFAULT_COOLDOWN)
        now = time.monotonic()

        with self._lock:
            last = self._last_sent.get(command, 0.0)
            if now - last < cooldown:
                print(f"[GestureClient] DROP {command}: cooldown {cooldown - (now - last):.1f}s left")
                return False
            self._last_sent[command] = now

        payload: dict = {
            "command": command,
            "confidence": round(confidence, 3),
            "stream_id": stream_id,
        }
        if anchor is not None:
            payload["anchor"] = {"x": round(anchor[0], 4), "y": round(anchor[1], 4)}
        if secondary is not None:
            payload["secondary"] = {"x": round(secondary[0], 4), "y": round(secondary[1], 4)}

        try:
            self._sio.emit("gesture_command_received", payload)
            print(f"[GestureClient] SENT {command} stream={stream_id[:8]}... anchor={payload.get('anchor')}")
            return True
        except Exception as e:
            print(f"[GestureClient] Emit error: {e}")
            return False

    def cooldown_remaining(self, command: str) -> float:
        """Return seconds left on cooldown for a command (0 if ready)."""
        cooldown = COMMAND_COOLDOWNS.get(command, DEFAULT_COOLDOWN)
        with self._lock:
            elapsed = time.monotonic() - self._last_sent.get(command, 0.0)
        return max(0.0, cooldown - elapsed)

    def cooldown_fraction(self, command: str) -> float:
        """Return fraction [0,1] of cooldown remaining (for UI arc)."""
        cooldown = COMMAND_COOLDOWNS.get(command, DEFAULT_COOLDOWN)
        if cooldown == 0:
            return 0.0
        return self.cooldown_remaining(command) / cooldown

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_connect(self):
        self._connected = True
        print("[GestureClient] Connected to backend")

    def _on_disconnect(self, reason=None):
        self._connected = False
        print(f"[GestureClient] Disconnected: {reason}")

    def _on_ack(self, data):
        print(f"[GestureClient] ACK  {data.get('command')}  status={data.get('status')}")

    def _on_error(self, data):
        print(f"[GestureClient] Connection error: {data}")

    def _on_comment_received(self, data):
        """Forward `comment_received` payloads to the streamer's local overlay.

        Backend payload shape (from app/sockets/social_events.py):
            { "username": "...", "content": "...", ... }
        Defensive about missing fields — chat shouldn't crash the streamer.
        """
        if not callable(self._on_comment):
            return
        try:
            username = (data or {}).get("username", "anon")
            content = (data or {}).get("content", "")
            if content:
                self._on_comment(username, content)
        except Exception as e:
            print(f"[GestureClient] comment handler error: {e}")

    def _on_recording_start_event(self, data):
        """Fires when the streamer dashboard clicks Record.

        Runs on the socket.io thread. We just hand the name to the loop's
        registered callback — the loop is responsible for thread-safety.
        """
        if not callable(self._on_recording_start):
            return
        try:
            name = (data or {}).get("name", "").strip()
            if name:
                self._on_recording_start(name)
        except Exception as e:
            print(f"[GestureClient] recording_start handler error: {e}")

    def _on_streamer_authenticated_event(self, data):
        """Fires when the dashboard signs in or switches accounts.

        Runs on the socket.io thread; the registered callback hands off
        to the loop's main thread to refetch overrides/templates safely.
        """
        if not callable(self._on_streamer_authenticated):
            return
        try:
            api_key = (data or {}).get("api_key", "")
            user_id = (data or {}).get("user_id", "")
            username = (data or {}).get("username", "")
            if api_key:
                self._on_streamer_authenticated(api_key, user_id, username)
        except Exception as e:
            print(f"[GestureClient] streamer_authenticated handler error: {e}")
