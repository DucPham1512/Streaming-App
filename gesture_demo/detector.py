"""
Hand gesture detection using MediaPipe Hands.

Landmark indices (21 points):
  0  = WRIST
  1-4  = THUMB  (CMC, MCP, IP, TIP)
  5-8  = INDEX  (MCP, PIP, DIP, TIP)
  9-12 = MIDDLE (MCP, PIP, DIP, TIP)
  13-16= RING   (MCP, PIP, DIP, TIP)
  17-20= PINKY  (MCP, PIP, DIP, TIP)
"""

import math
from collections import deque

import mediapipe as mp

# Tip and PIP landmark indices for fingers 1-4 (not thumb)
FINGER_TIPS = [8, 12, 16, 20]   # index, middle, ring, pinky
FINGER_PIPS = [6, 10, 14, 18]

THUMB_TIP = 4
THUMB_IP  = 3
THUMB_MCP = 2

INDEX_TIP = 8
INDEX_PIP = 6


def _dist(a, b) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def _fingers_extended(lm) -> list[bool]:
    """Return [index, middle, ring, pinky] extended flags."""
    return [lm[tip].y < lm[pip].y for tip, pip in zip(FINGER_TIPS, FINGER_PIPS)]


def _thumb_extended(lm, handedness: str) -> bool:
    """Thumb is extended when its tip clears the IP joint horizontally."""
    if handedness == "Right":
        return lm[THUMB_TIP].x < lm[THUMB_IP].x
    return lm[THUMB_TIP].x > lm[THUMB_IP].x


def classify(lm, handedness: str) -> str | None:
    """
    Map 21 hand landmarks to a gesture name.
    Returns None if no known gesture is detected.
    """
    ext = _fingers_extended(lm)           # [index, middle, ring, pinky]
    thumb = _thumb_extended(lm, handedness)

    index_ext, middle_ext, ring_ext, pinky_ext = ext

    # Finger heart: thumb tip very close to index tip (thumb crosses over index)
    hand_width = _dist(lm[0], lm[9])      # wrist to middle MCP as scale
    tip_dist = _dist(lm[THUMB_TIP], lm[INDEX_TIP])
    if tip_dist < 0.09 * hand_width:
        return "finger_heart"

    # Open palm: all 5 extended
    if thumb and index_ext and middle_ext and ring_ext and pinky_ext:
        return "open_palm"

    # Fist: all curled
    if not thumb and not any(ext):
        return "fist"

    # Thumbs up: only thumb extended, all fingers curled
    if thumb and not any(ext):
        # Extra check: thumb tip must be above wrist (pointing up)
        if lm[THUMB_TIP].y < lm[0].y:
            return "thumbs_up"

    # Peace sign: index + middle extended, ring + pinky curled
    if index_ext and middle_ext and not ring_ext and not pinky_ext:
        return "peace"

    # ILY / Shaka: thumb + index + pinky extended, middle + ring curled
    if thumb and index_ext and not middle_ext and not ring_ext and pinky_ext:
        return "ily"

    return None


# Gesture → stream command mapping (can be overridden by DB GestureMapping)
GESTURE_COMMANDS: dict[str, str] = {
    "open_palm":    "mute_toggle",
    "fist":         "end_stream",
    "thumbs_up":    "like_stream",
    "peace":        "entertainment_confetti",
    "finger_heart": "entertainment_heart",
    "ily":          "entertainment_fireworks",
}


class Stabilizer:
    """
    Fires a gesture only when it has been held for `required` consecutive frames.
    Prevents single-frame flickers from triggering commands.
    """

    def __init__(self, required: int = 8):
        self.required = required
        self._history: deque[str | None] = deque(maxlen=required)

    def update(self, gesture: str | None) -> str | None:
        """
        Feed the latest classified gesture.
        Returns the stable gesture name if confirmed, else None.
        """
        self._history.append(gesture)
        if len(self._history) < self.required:
            return None
        if all(g == gesture for g in self._history) and gesture is not None:
            return gesture
        return None


class GestureDetector:
    """
    Wraps MediaPipe Hands inference + classification + stabilization.
    Usage:
        detector = GestureDetector()
        with detector:
            gesture, hand_landmarks = detector.process(rgb_frame)
    """

    def __init__(self, max_hands: int = 1, detection_confidence: float = 0.7):
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            max_num_hands=max_hands,
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=0.6,
        )
        self._stabilizer = Stabilizer(required=8)
        self.drawing = mp.solutions.drawing_utils
        self.drawing_styles = mp.solutions.drawing_styles

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._hands.close()

    def process(self, rgb_frame) -> tuple[str | None, list | None]:
        """
        Process one RGB frame.
        Returns (stable_gesture_name | None, hand_landmarks | None).
        """
        result = self._hands.process(rgb_frame)

        if not result.multi_hand_landmarks:
            self._stabilizer.update(None)
            return None, None

        hand_lm = result.multi_hand_landmarks[0]
        handedness = (
            result.multi_handedness[0].classification[0].label
            if result.multi_handedness
            else "Right"
        )

        raw = classify(hand_lm.landmark, handedness)
        stable = self._stabilizer.update(raw)
        return stable, hand_lm
