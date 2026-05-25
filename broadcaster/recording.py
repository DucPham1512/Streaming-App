"""Per-stream recording state machine for the `R` hotkey.

The OpenCV loop in loop.py drives this: when the streamer presses `r`,
a `RecordingSession` is created. The loop then calls `tick(landmarks)`
once per frame. The session reports its current `phase` (countdown,
capturing, done) so the loop can draw the right HUD text. When the
session is done, the loop POSTs the captured samples to the backend.

Kept separate from loop.py so the state machine is unit-testable
without OpenCV or MediaPipe.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from .custom_classifier import _normalize


log = logging.getLogger(__name__)


DEFAULT_COUNTDOWN_SECONDS = 3
DEFAULT_SAMPLES = 10


@dataclass
class RecordingSession:
    """In-progress recording of a single custom gesture.

    Lifecycle:
        countdown (N seconds, drawn as N..1) → capturing → done.

    Caller owns the wall-clock — call tick() on each captured frame
    and feed it the current MediaPipe landmarks (None when no hand is
    visible). When phase == "done", read .samples and dispatch to the
    backend, then drop the session.
    """

    name: str
    handedness: str = "Any"
    countdown_seconds: float = DEFAULT_COUNTDOWN_SECONDS
    target_samples: int = DEFAULT_SAMPLES
    started_at: float = field(default_factory=time.monotonic)
    samples: list[list[float]] = field(default_factory=list)
    aborted: bool = False

    @property
    def phase(self) -> str:
        if self.aborted:
            return "aborted"
        elapsed = time.monotonic() - self.started_at
        if elapsed < self.countdown_seconds:
            return "countdown"
        if len(self.samples) < self.target_samples:
            return "capturing"
        return "done"

    def countdown_label(self) -> str:
        """e.g. 'Recording "wave" in 2…' — for the HUD.

        Ceil-based: at t=0.0 we show "in N", flips to "in N-1" at t=1.0,
        etc. Clamps to 1 so we never display "in 0" mid-countdown.
        """
        elapsed = time.monotonic() - self.started_at
        remaining = max(1, math.ceil(self.countdown_seconds - elapsed))
        return f'Recording "{self.name}" in {remaining}…'

    def progress_label(self) -> str:
        """e.g. 'Captured 4 / 10'."""
        return f"Captured {len(self.samples)} / {self.target_samples}"

    def tick(self, landmarks) -> None:
        """Advance the state machine for one frame.

        landmarks: a MediaPipe landmark list, or None when no hand is in
        view. During the `capturing` phase we skip frames with no hand
        rather than feeding zeros — the streamer can hold still for an
        extra frame or two without aborting.
        """
        if self.phase != "capturing":
            return
        normalized = _normalize(landmarks) if landmarks is not None else None
        if normalized is None:
            return
        self.samples.append(normalized)

    def abort(self) -> None:
        self.aborted = True


def upload_recording(api_client, session: RecordingSession) -> dict:
    """POST a finished session as a new GestureTemplate.

    Returns the parsed response. Raises broadcaster.api_client.ApiError
    on backend failure (duplicate name, 401, etc.) — caller logs and
    keeps the session around or drops it as appropriate.
    """
    payload = {
        "name": session.name,
        "action": "unmapped",        # streamer assigns one via the FE later
        "handedness": session.handedness,
        "landmarks": session.samples,
    }
    return api_client.post("/api/v1/gestures/templates", payload)
