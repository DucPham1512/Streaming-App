"""k-NN gesture classifier — runtime side of the per-user templates.

Templates come from `GET /api/v1/gestures/templates`. Each row has a
list of recorded sample frames; each sample is a 63-float vector of
normalized landmarks (wrist-centered, palm-scale-invariant — see
`_normalize` below).

Why k-NN over a trained model: see
docs/decisions/004-knn-gesture-templates.md.

Each frame the broadcaster:
  1. Runs the rule-based `detector.classify()` first. If that returns
     a built-in gesture, the broadcaster uses the user's effective
     action (override if present, default otherwise). The classifier
     in THIS file is bypassed for that frame.
  2. If no built-in match, normalize the current landmarks and ask
     `CustomGestureClassifier.classify(...)` for the nearest template.

Hysteresis: a custom gesture must "win" for `min_consecutive_frames`
in a row to fire. Prevents single-frame false positives.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# Landmark indices we use for normalization.
_WRIST = 0
_MIDDLE_MCP = 9


def _normalize(lm_seq) -> list[float]:
    """Wrist-center and palm-scale-normalize 21 MediaPipe landmarks.

    Accepts either:
      * MediaPipe landmark objects (with .x .y .z attributes), as produced
        by `GestureDetector.process(...)`, or
      * a flat list of 63 floats (already normalized — used for tests).

    Returns a flat list of 63 floats:
      [x0, y0, z0, x1, y1, z1, ...] after subtracting the wrist position
      and dividing each coordinate by the wrist→MCP9 distance. This makes
      "same gesture closer vs. farther from the camera" land near each
      other in vector space.

    Returns None if the input is unusable.
    """
    if isinstance(lm_seq, list) and len(lm_seq) == 63 and all(
        isinstance(x, (int, float)) for x in lm_seq
    ):
        return list(lm_seq)
    if lm_seq is None or len(lm_seq) != 21:
        return None

    wx, wy, wz = lm_seq[_WRIST].x, lm_seq[_WRIST].y, lm_seq[_WRIST].z
    mx, my, mz = lm_seq[_MIDDLE_MCP].x, lm_seq[_MIDDLE_MCP].y, lm_seq[_MIDDLE_MCP].z
    scale = math.sqrt((mx - wx) ** 2 + (my - wy) ** 2 + (mz - wz) ** 2)
    if scale < 1e-6:
        return None

    out: list[float] = []
    for p in lm_seq:
        out.append((p.x - wx) / scale)
        out.append((p.y - wy) / scale)
        out.append((p.z - wz) / scale)
    return out


def _euclid(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@dataclass
class _PreparedTemplate:
    """Pre-computed per-template stats so per-frame compare is cheap."""
    template_id: int
    name: str
    action: str
    mean: list[float]
    # within-template scalar std: average of |sample - mean| over samples.
    # Used as a per-template tolerance scale — tight templates (fist) and
    # loose templates (wave) both get a sensible threshold without manual
    # tuning. See decision-004.
    std: float


@dataclass
class _MatchState:
    """Running state for the consecutive-frame hysteresis."""
    template_id: Optional[int] = None
    consecutive: int = 0


def _prepare(template_row: dict) -> Optional[_PreparedTemplate]:
    """Convert one /gestures/templates row into per-template stats.

    Returns None when the row's landmarks are malformed (zero samples,
    wrong frame width, etc.); the broadcaster logs and skips it.
    """
    samples_raw = template_row.get("landmarks") or []
    samples: list[list[float]] = []
    for s in samples_raw:
        if isinstance(s, list) and len(s) == 63 and all(
            isinstance(x, (int, float)) for x in s
        ):
            samples.append(list(s))
    if not samples:
        return None

    dim = 63
    n = len(samples)
    mean = [sum(s[i] for s in samples) / n for i in range(dim)]
    # Scalar within-template std: average frame-to-mean Euclidean distance.
    deviations = [_euclid(s, mean) for s in samples]
    std = (sum(deviations) / n) if deviations else 0.0

    return _PreparedTemplate(
        template_id=int(template_row.get("id", 0)),
        name=str(template_row.get("name", "")),
        action=str(template_row.get("action", "unmapped")),
        mean=mean,
        std=max(std, 1e-3),  # floor so threshold = std_factor * std never collapses
    )


@dataclass
class ClassifyResult:
    """A successful (template fire) or no-op (None) classification."""
    template_id: int
    name: str
    action: str


class CustomGestureClassifier:
    """Stateful k-NN matcher with consecutive-frame hysteresis.

    Construct once at stream start with the user's templates fetched
    from the backend. Call `classify(landmarks)` every frame the
    rule-based detector did NOT recognise. A non-None return means
    the user just performed that custom gesture and an action should
    be fired (caller dispatches via the same code path built-ins use).
    """

    def __init__(
        self,
        template_rows: list[dict],
        *,
        std_factor: float = 2.5,
        min_consecutive_frames: int = 5,
    ):
        self._std_factor = std_factor
        self._min_consecutive = min_consecutive_frames

        self._templates: list[_PreparedTemplate] = []
        for row in template_rows:
            prepped = _prepare(row)
            if prepped is None:
                log.warning("Skipping malformed template row: %s", row.get("name"))
                continue
            # "unmapped" templates remain matchable but fire no action — the
            # streamer recorded them but hasn't picked an action yet. Useful
            # for the Gesture Library UI distance-score debug, but we skip
            # them at fire time below.
            self._templates.append(prepped)

        self._state = _MatchState()

    # ------------------------------------------------------------------
    # Read-only introspection (used by the OpenCV preview's debug bars)
    # ------------------------------------------------------------------

    @property
    def template_count(self) -> int:
        return len(self._templates)

    def distance_scores(self, landmarks) -> list[tuple[str, float]]:
        """For each template, return (name, distance) for the current frame.

        Returns [] when landmarks can't be normalized. The preview can
        render these as small bars so the streamer sees how close they
        are to each saved template while rehearsing.
        """
        normalized = _normalize(landmarks)
        if normalized is None:
            return []
        return [(t.name, _euclid(normalized, t.mean)) for t in self._templates]

    # ------------------------------------------------------------------
    # Per-frame classify
    # ------------------------------------------------------------------

    def classify(self, landmarks) -> Optional[ClassifyResult]:
        """Return a ClassifyResult on the frame the gesture is CONFIRMED.

        Returns the result exactly once per sustained gesture: the frame
        after `min_consecutive_frames` matches in a row. Subsequent
        frames return None until the streamer breaks the pose and
        re-poses (otherwise a held gesture would fire repeatedly).
        """
        if not self._templates:
            return None

        normalized = _normalize(landmarks)
        if normalized is None:
            self._state = _MatchState()
            return None

        # Nearest template + its per-template threshold.
        nearest: Optional[_PreparedTemplate] = None
        nearest_dist = math.inf
        for t in self._templates:
            d = _euclid(normalized, t.mean)
            if d < nearest_dist:
                nearest_dist = d
                nearest = t

        if nearest is None or nearest_dist > self._std_factor * nearest.std:
            self._state = _MatchState()
            return None

        # Hysteresis: same template wins this frame as last?
        if self._state.template_id == nearest.template_id:
            self._state.consecutive += 1
        else:
            self._state = _MatchState(template_id=nearest.template_id, consecutive=1)

        if self._state.consecutive < self._min_consecutive:
            return None
        # Edge-trigger: increment past the threshold so we don't re-fire
        # while the pose is still held. Resets when distance crosses
        # threshold again (caller breaks the pose).
        if self._state.consecutive > self._min_consecutive:
            return None

        if nearest.action == "unmapped":
            # Recognized but no action assigned — log it for the preview
            # debug, don't fire anything.
            log.debug("Recognized unmapped template: %s", nearest.name)
            return None
        return ClassifyResult(
            template_id=nearest.template_id,
            name=nearest.name,
            action=nearest.action,
        )
