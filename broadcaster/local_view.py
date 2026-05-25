"""Streamer-side OpenCV overlay helpers — the broadcaster's own view.

Anything drawn here lands ONLY in the local preview window (cv2.imshow on
the streamer's laptop). It must NEVER touch the frame that's published to
LiveKit. See docs/decisions/002-broadcaster-burn-in-compositing.md — the
published frame is composited separately so viewers receive a single
pre-rendered video track.

Current contents:
  * CommentBuffer — thread-safe ring buffer of recent chat messages
                    pushed by the Socket.IO `comment_received` event.
  * render_comment_column(frame, buffer) — draws a fading column of
                                            messages on the right edge.

Future additions (Commits 6b/13): landmark drawing wrapper, gesture
recording status, k-NN distance debug bars.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2


# ---------------------------------------------------------------------------
# Comment buffer
# ---------------------------------------------------------------------------


@dataclass
class _Comment:
    """One chat message held in the local ring buffer."""

    username: str
    content: str
    received_at: float  # monotonic seconds


class CommentBuffer:
    """Thread-safe ring buffer of the most recent chat messages.

    The Socket.IO client thread calls .add() when a `comment_received`
    event arrives. The OpenCV main thread calls .snapshot() each frame
    to render. The internal deque + lock keeps both safe.

    Messages older than ttl_seconds are filtered out at snapshot time
    so they fade off the preview without needing a sweeper thread.
    """

    def __init__(self, capacity: int = 8, ttl_seconds: float = 10.0):
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._items: deque[_Comment] = deque(maxlen=capacity)

    def add(self, username: str, content: str) -> None:
        """Append a new comment. Oldest is evicted past `capacity`."""
        if not isinstance(content, str) or not content:
            return
        item = _Comment(
            username=str(username or "anon"),
            content=content,
            received_at=time.monotonic(),
        )
        with self._lock:
            self._items.append(item)

    def snapshot(self) -> list[_Comment]:
        """Return a list copy of comments still within TTL, oldest first."""
        cutoff = time.monotonic() - self._ttl
        with self._lock:
            return [c for c in self._items if c.received_at >= cutoff]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE = 0.5
_LINE_THICKNESS = 1
_LINE_HEIGHT_PX = 22          # vertical step between message lines
_PADDING_PX = 8
_COLUMN_WIDTH_PX = 280        # right-edge panel width
_BG_ALPHA = 0.45              # background opacity (0=transparent, 1=opaque)
_MAX_CONTENT_CHARS = 60       # truncate longer messages with an ellipsis


def render_comment_column(frame, buffer: CommentBuffer) -> None:
    """Draw the scrolling comment column on the right edge of `frame`.

    Modifies the frame in place. Drawing is skipped entirely when the
    buffer is empty so an empty stream's preview stays uncluttered.

    Layout:
        ┌──── column ────┐
        │ alice: hi!     │   ← oldest at top
        │ bob: 👋        │
        │ carol: nice    │   ← newest at bottom
        └────────────────┘
    Each message fades to ~30% alpha in its final second of TTL.
    """
    comments = buffer.snapshot()
    if not comments:
        return

    h, w = frame.shape[:2]
    col_left = w - _COLUMN_WIDTH_PX
    col_top = _PADDING_PX
    col_bottom = col_top + len(comments) * _LINE_HEIGHT_PX + _PADDING_PX

    # Semi-transparent dark background panel
    overlay = frame.copy()
    cv2.rectangle(overlay, (col_left, col_top), (w - _PADDING_PX, col_bottom),
                  (0, 0, 0), thickness=-1)
    cv2.addWeighted(overlay, _BG_ALPHA, frame, 1.0 - _BG_ALPHA, 0, dst=frame)

    now = time.monotonic()
    # Comments are oldest-first from snapshot; draw top-down so most recent
    # is at the bottom of the column (closest to where the eye expects "new").
    for i, comment in enumerate(comments):
        age = now - comment.received_at
        # Linear fade in the last 1 second of TTL.
        remaining = max(0.0, buffer._ttl - age)
        alpha = 1.0 if remaining >= 1.0 else max(0.3, remaining)

        text = f"{comment.username}: {comment.content}"
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[: _MAX_CONTENT_CHARS - 1] + "…"

        # OpenCV doesn't support per-glyph alpha; approximate by blending
        # the text color toward black as alpha decays.
        color = tuple(int(255 * alpha) for _ in range(3))

        y = col_top + _PADDING_PX + (i + 1) * _LINE_HEIGHT_PX - 6
        cv2.putText(frame, text, (col_left + _PADDING_PX, y),
                    _FONT, _FONT_SCALE, color, _LINE_THICKNESS, cv2.LINE_AA)
