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

    def __init__(self, socket_url: str, api_key: str | None = None):
        self._url = socket_url
        self._api_key = api_key
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()
        self._connected = False

        self._sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._sio.on("connect", self._on_connect)
        self._sio.on("disconnect", self._on_disconnect)
        self._sio.on("gesture_ack", self._on_ack)
        self._sio.on("connect_error", self._on_error)

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
    ) -> bool:
        """
        Emit gesture_command_received.
        Returns True if sent, False if on cooldown or not connected.
        """
        if not self._connected:
            return False

        cooldown = COMMAND_COOLDOWNS.get(command, DEFAULT_COOLDOWN)
        now = time.monotonic()

        with self._lock:
            last = self._last_sent.get(command, 0.0)
            if now - last < cooldown:
                return False
            self._last_sent[command] = now

        try:
            self._sio.emit(
                "gesture_command_received",
                {
                    "command": command,
                    "confidence": round(confidence, 3),
                    "stream_id": stream_id,
                },
            )
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
