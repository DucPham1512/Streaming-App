"""
Hand gesture detection using MediaPipe Tasks API (0.10+).

Landmark indices (21 points):
  0  = WRIST
  1-4  = THUMB  (CMC, MCP, IP, TIP)
  5-8  = INDEX  (MCP, PIP, DIP, TIP)
  9-12 = MIDDLE (MCP, PIP, DIP, TIP)
  13-16= RING   (MCP, PIP, DIP, TIP)
  17-20= PINKY  (MCP, PIP, DIP, TIP)
"""

import math
import os
import urllib.request
from collections import deque

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

# Model is downloaded automatically on first run (~1 MB)
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")

# Landmark connections for drawing the hand skeleton with OpenCV
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),           # index
    (0, 9), (9, 10), (10, 11), (11, 12),      # middle
    (0, 13), (13, 14), (14, 15), (15, 16),    # ring
    (0, 17), (17, 18), (18, 19), (19, 20),    # pinky
    (5, 9), (9, 13), (13, 17),                # palm knuckle bar
]

# Finger tip / PIP indices for extension detection
FINGER_TIPS = [8, 12, 16, 20]
FINGER_PIPS = [6, 10, 14, 18]
THUMB_TIP = 4
THUMB_IP  = 3
INDEX_TIP = 8


def _ensure_model():
    if not os.path.exists(MODEL_PATH):
        print(f"Downloading hand landmark model (~1 MB) ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Download complete.")


def _dist(a, b) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def _fingers_extended(lm) -> list[bool]:
    """
    Orientation-agnostic extension: a finger is extended if its tip is
    farther from the wrist than its PIP joint (works regardless of which
    way the hand is rotated or which side of the palm faces the camera).
    """
    wrist = lm[0]
    out = []
    for tip, pip in zip(FINGER_TIPS, FINGER_PIPS):
        out.append(_dist(lm[tip], wrist) > _dist(lm[pip], wrist) * 1.1)
    return out


def _thumb_extended(lm) -> bool:
    """Thumb extended if its tip is much farther from the wrist than its IP joint."""
    return _dist(lm[THUMB_TIP], lm[0]) > _dist(lm[THUMB_IP], lm[0]) * 1.2


def classify(lm, handedness: str) -> str | None:
    """Map 21 hand landmarks to a gesture name, or None if unrecognised."""
    ext = _fingers_extended(lm)
    thumb = _thumb_extended(lm)
    index_ext, middle_ext, ring_ext, pinky_ext = ext

    hand_width = _dist(lm[0], lm[9])

    # Finger-heart shape (described from camera POV):
    #   - tips of middle/ring/pinky are LOWER on screen than the index tip
    #   - thumb tip and index tip meet near the top to form the heart's peak
    #   - the index is only HALF-curled (so its tip is still well away from its
    #     base knuckle) — this is the key signal that separates heart from fist
    index_tip_y = lm[INDEX_TIP].y
    others_below_index = (
        lm[12].y > index_tip_y and
        lm[16].y > index_tip_y and
        lm[20].y > index_tip_y
    )
    thumb_index_meet = _dist(lm[THUMB_TIP], lm[INDEX_TIP]) < 0.5 * hand_width
    # Index half-curled: tip is still reasonably far from its MCP base
    index_half_curled = _dist(lm[INDEX_TIP], lm[5]) > 0.6 * hand_width
    # All four fingertips pulled in close to the palm (fist signature)
    all_fingers_curled_tight = (
        _dist(lm[8],  lm[5])  < 0.6 * hand_width and
        _dist(lm[12], lm[9])  < 0.6 * hand_width and
        _dist(lm[16], lm[13]) < 0.6 * hand_width and
        _dist(lm[20], lm[17]) < 0.6 * hand_width
    )
    # Thumb folded across or against the fingers (fist), not sticking out sideways
    thumb_tucked = _dist(lm[THUMB_TIP], lm[9]) < 1.2 * hand_width

    # Order matters — check the most specific gestures first.

    # ILY: thumb + index + pinky extended, middle + ring curled
    if thumb and index_ext and not middle_ext and not ring_ext and pinky_ext:
        return "ily"

    # Peace: index + middle extended, ring + pinky curled (thumb can be either)
    if index_ext and middle_ext and not ring_ext and not pinky_ext:
        return "peace"

    # Thumbs up: ONLY thumb extended, all fingers curled, thumb above wrist
    if thumb and not index_ext and not middle_ext and not ring_ext and not pinky_ext:
        if lm[THUMB_TIP].y < lm[0].y:
            return "thumbs_up"

    # Fist: ALL five elements tight against the palm — four fingertips pulled
    # close to their MCP joints AND the thumb tucked against/across the
    # fingers. Checked BEFORE finger_heart so a deeply-curled hand wins.
    if all_fingers_curled_tight and thumb_tucked:
        return "fist"

    # Finger heart: middle/ring/pinky tips sit below the index tip, thumb
    # meets the index tip, and the index is only HALF-curled (not pulled all
    # the way down to its base — that would be a fist).
    if (others_below_index and thumb_index_meet and index_half_curled
            and not middle_ext and not ring_ext and not pinky_ext):
        return "finger_heart"

    # Open palm: all five extended
    if thumb and index_ext and middle_ext and ring_ext and pinky_ext:
        return "open_palm"

    return None


# Anchor point selection per gesture. Returns one or two normalized (x, y)
# points in [0, 1] (MediaPipe's native space, relative to the webcam frame).
# These are the fingertips/keypoints viewers' effects should originate from.
def _midpoint(a, b) -> tuple[float, float]:
    return ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def anchor_for(
    gesture: str,
    lm,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Return (anchor, secondary) normalized points for the given gesture."""
    if gesture == "finger_heart":
        return _midpoint(lm[THUMB_TIP], lm[INDEX_TIP]), None
    if gesture == "thumbs_up":
        return (lm[THUMB_TIP].x, lm[THUMB_TIP].y), None
    if gesture == "peace":
        return _midpoint(lm[8], lm[12]), None
    if gesture == "ily":
        return (lm[INDEX_TIP].x, lm[INDEX_TIP].y), (lm[20].x, lm[20].y)
    if gesture in ("open_palm", "fist"):
        return (lm[9].x, lm[9].y), None
    return None, None


# Gesture → stream command mapping
GESTURE_COMMANDS: dict[str, str] = {
    "open_palm":    "mute_toggle",
    "fist":         "end_stream",
    "thumbs_up":    "like_stream",
    "peace":        "entertainment_confetti",
    "finger_heart": "entertainment_heart",
    "ily":          "entertainment_fireworks",
}


def draw_landmarks(frame, landmarks):
    """Draw hand skeleton on frame using pure OpenCV (no mp.solutions needed)."""
    h, w = frame.shape[:2]
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
    for a, b in _HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (0, 200, 0), 2, cv2.LINE_AA)
    for pt in pts:
        cv2.circle(frame, pt, 5, (255, 255, 255), -1)
        cv2.circle(frame, pt, 5, (0, 140, 0), 1)


class Stabilizer:
    """Fires a gesture only after it has been held for N consecutive frames."""

    def __init__(self, required: int = 8):
        self.required = required
        self._history: deque[str | None] = deque(maxlen=required)

    def update(self, gesture: str | None) -> str | None:
        self._history.append(gesture)
        if len(self._history) < self.required:
            return None
        if all(g == gesture for g in self._history) and gesture is not None:
            return gesture
        return None


class GestureDetector:
    """
    Wraps MediaPipe HandLandmarker (Tasks API) + classification + stabilization.

    Usage:
        with GestureDetector() as detector:
            gesture, landmarks = detector.process(rgb_frame)
    """

    def __init__(self, max_hands: int = 1, detection_confidence: float = 0.7):
        _ensure_model()
        base_options = mp_tasks.BaseOptions(model_asset_path=MODEL_PATH)
        options = mp_vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=0.7,
            min_tracking_confidence=0.6,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self._stabilizer = Stabilizer(required=15)
        self._ts_ms = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._landmarker.close()

    def process(self, rgb_frame):
        """
        Process one RGB frame.
        Returns (stable_gesture_name | None, landmark_list | None,
                 anchor | None, secondary | None).
        anchor / secondary are normalized (x, y) tuples or None.
        """
        self._ts_ms += 33  # simulate ~30 fps timestamps
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect_for_video(mp_image, self._ts_ms)

        if not result.hand_landmarks:
            self._stabilizer.update(None)
            return None, None, None, None

        landmarks = result.hand_landmarks[0]
        handedness = (
            result.handedness[0][0].category_name
            if result.handedness
            else "Right"
        )

        raw = classify(landmarks, handedness)
        stable = self._stabilizer.update(raw)
        anchor, secondary = (None, None)
        if stable is not None:
            anchor, secondary = anchor_for(stable, landmarks)
        return stable, landmarks, anchor, secondary
