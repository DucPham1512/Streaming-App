"""
OpenCV overlay effects rendered on the local webcam preview window.
These are visual-only on the streamer's machine; viewer effects are
handled by the React Native app via Socket.IO.
"""

import math
import random
import time

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Gesture label + cooldown arc
# ---------------------------------------------------------------------------

GESTURE_LABELS = {
    "open_palm":    "Open Palm  - Mute",
    "fist":         "Fist  - End Stream (hold)",
    "thumbs_up":    "Thumbs Up  - Like",
    "peace":        "Peace  - Confetti",
    "finger_heart": "Finger Heart  - Hearts",
    "ily":          "ILY  - Fireworks",
}

GESTURE_COLORS = {
    "open_palm":    (255, 200, 0),
    "fist":         (0, 60, 255),
    "thumbs_up":    (0, 200, 80),
    "peace":        (255, 140, 0),
    "finger_heart": (100, 60, 255),
    "ily":          (0, 200, 255),
}


def draw_gesture_label(frame, gesture: str | None, cooldown_pct: float = 0.0):
    """Draw the gesture name at the bottom of the frame with a cooldown arc."""
    h, w = frame.shape[:2]

    if gesture is None:
        cv2.putText(
            frame, "No gesture detected",
            (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (180, 180, 180), 1, cv2.LINE_AA,
        )
        return

    label = GESTURE_LABELS.get(gesture, gesture)
    color = GESTURE_COLORS.get(gesture, (255, 255, 255))

    # Semi-transparent banner
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 60), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    cv2.putText(
        frame, label,
        (20, h - 20), cv2.FONT_HERSHEY_DUPLEX, 0.75,
        color, 2, cv2.LINE_AA,
    )

    # Cooldown arc (top-right corner)
    if cooldown_pct > 0:
        cx, cy, r = w - 40, 40, 25
        angle = int(360 * cooldown_pct)
        cv2.ellipse(frame, (cx, cy), (r, r), -90, 0, angle, (80, 80, 80), 3)
        cv2.ellipse(frame, (cx, cy), (r, r), -90, 0, 360, (50, 50, 50), 1)


# ---------------------------------------------------------------------------
# Heart shape (drawn with parametric equations)
# ---------------------------------------------------------------------------

def _heart_pts(cx: int, cy: int, size: float, n: int = 80) -> np.ndarray:
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = size * (16 * math.sin(t) ** 3)
        y = -size * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append([int(cx + x), int(cy + y)])
    return np.array(pts, dtype=np.int32)


class HeartEffect:
    """Draws a pulsing heart at screen center that fades over ~45 frames."""

    LIFETIME = 45

    def __init__(self, w: int, h: int):
        self.cx, self.cy = w // 2, h // 2
        self.frame = 0

    @property
    def alive(self) -> bool:
        return self.frame < self.LIFETIME

    def draw(self, frame):
        if not self.alive:
            return
        progress = self.frame / self.LIFETIME            # 0→1
        size = 8 + 6 * math.sin(progress * math.pi)    # pulse
        alpha = 1.0 - progress

        pts = _heart_pts(self.cx, self.cy, size)

        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts], (60, 20, 220))     # BGR red
        cv2.addWeighted(overlay, alpha * 0.85, frame, 1 - alpha * 0.85, 0, frame)
        cv2.polylines(frame, [pts], True, (100, 60, 255), 2, cv2.LINE_AA)

        self.frame += 1


# ---------------------------------------------------------------------------
# Like (thumbs-up) effect
# ---------------------------------------------------------------------------

class LikeEffect:
    """Big thumbs-up emoji-style badge that pops in at center then fades out."""

    LIFETIME = 40

    def __init__(self, w: int, h: int):
        self.cx, self.cy = w // 2, h // 2
        self.frame = 0

    @property
    def alive(self) -> bool:
        return self.frame < self.LIFETIME

    def draw(self, frame):
        if not self.alive:
            return
        progress = self.frame / self.LIFETIME
        # Pop-in scale: snaps up fast then settles
        scale = min(1.0, progress * 3.0) * (1.0 + 0.15 * math.sin(progress * math.pi))
        alpha = 1.0 - progress

        size = int(80 * scale)
        if size < 2:
            self.frame += 1
            return

        cx, cy = self.cx, self.cy
        overlay = frame.copy()

        # Yellow circle background
        cv2.circle(overlay, (cx, cy), size, (0, 200, 255), -1)
        cv2.circle(overlay, (cx, cy), size, (255, 255, 255), max(2, size // 20))

        # Thumb shape (simple stylized): a vertical rectangle with a rounded top
        # representing the thumb, and a square fist below.
        thumb_w = size // 3
        thumb_h = int(size * 0.9)
        fist_w  = int(size * 0.85)
        fist_h  = int(size * 0.55)

        # Fist (lower)
        fx1 = cx - fist_w // 2
        fy1 = cy + size // 6
        fx2 = cx + fist_w // 2
        fy2 = fy1 + fist_h
        cv2.rectangle(overlay, (fx1, fy1), (fx2, fy2), (255, 255, 255), -1)

        # Thumb (upper, slightly left of center for natural look)
        tx1 = cx - thumb_w // 2 - size // 12
        ty2 = fy1 + 2
        tx2 = tx1 + thumb_w
        ty1 = ty2 - thumb_h
        cv2.rectangle(overlay, (tx1, ty1 + thumb_w // 2), (tx2, ty2), (255, 255, 255), -1)
        cv2.circle(overlay, ((tx1 + tx2) // 2, ty1 + thumb_w // 2), thumb_w // 2, (255, 255, 255), -1)

        cv2.addWeighted(overlay, alpha * 0.9, frame, 1 - alpha * 0.9, 0, frame)
        self.frame += 1


# ---------------------------------------------------------------------------
# Confetti particles
# ---------------------------------------------------------------------------

_CONFETTI_COLORS = [
    (255, 80, 80), (80, 200, 255), (80, 255, 130),
    (255, 200, 50), (200, 80, 255), (255, 130, 30),
]


class ConfettiEffect:
    """40 colored rectangles that fall from the top with random drift."""

    LIFETIME = 90

    def __init__(self, w: int, h: int, n: int = 40):
        self.w, self.h = w, h
        self.frame = 0
        self.particles = [
            {
                "x": float(random.randint(0, w)),
                "y": float(random.randint(-h // 2, 0)),
                "vx": random.uniform(-2, 2),
                "vy": random.uniform(3, 7),
                "size": random.randint(6, 14),
                "angle": random.uniform(0, 360),
                "spin": random.uniform(-8, 8),
                "color": random.choice(_CONFETTI_COLORS),
            }
            for _ in range(n)
        ]

    @property
    def alive(self) -> bool:
        return self.frame < self.LIFETIME

    def draw(self, frame):
        if not self.alive:
            return
        alpha = max(0.0, 1.0 - self.frame / self.LIFETIME)
        overlay = frame.copy()
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["angle"] += p["spin"]
            if p["y"] > self.h + 20:
                p["y"] = -20
                p["x"] = random.randint(0, self.w)

            s = p["size"]
            cx, cy = int(p["x"]), int(p["y"])
            rect = np.array([[-s, -s//2], [s, -s//2], [s, s//2], [-s, s//2]], dtype=np.float32)
            angle_rad = math.radians(p["angle"])
            cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
            rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
            rotated = (rect @ rot.T).astype(np.int32) + [cx, cy]
            cv2.fillPoly(overlay, [rotated], p["color"])

        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        self.frame += 1


# ---------------------------------------------------------------------------
# Fireworks effect
# ---------------------------------------------------------------------------

class FireworksEffect:
    """Radial burst of lines expanding outward from screen center."""

    LIFETIME = 60

    def __init__(self, w: int, h: int, n_bursts: int = 3):
        self.cx, self.cy = w // 2, h // 2
        self.frame = 0
        self.bursts = [
            {
                "cx": random.randint(w // 4, 3 * w // 4),
                "cy": random.randint(h // 4, 3 * h // 4),
                "delay": i * 15,
                "color": random.choice(_CONFETTI_COLORS),
                "n_rays": random.randint(10, 18),
            }
            for i in range(n_bursts)
        ]

    @property
    def alive(self) -> bool:
        return self.frame < self.LIFETIME

    def draw(self, frame):
        if not self.alive:
            return
        for burst in self.bursts:
            t = self.frame - burst["delay"]
            if t < 0 or t > 40:
                continue
            radius = int(t * 5)
            alpha = max(0.0, 1.0 - t / 40)
            overlay = frame.copy()
            for i in range(burst["n_rays"]):
                angle = 2 * math.pi * i / burst["n_rays"]
                ex = burst["cx"] + int(radius * math.cos(angle))
                ey = burst["cy"] + int(radius * math.sin(angle))
                cv2.line(overlay, (burst["cx"], burst["cy"]), (ex, ey),
                         burst["color"], 2, cv2.LINE_AA)
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        self.frame += 1


# ---------------------------------------------------------------------------
# End-stream countdown overlay
# ---------------------------------------------------------------------------

def draw_end_countdown(frame, hold_pct: float):
    """
    Shown when the user is holding the fist gesture to end the stream.
    hold_pct: 0.0 → 1.0 (fraction of required hold time elapsed).
    """
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 180), -1)
    cv2.addWeighted(overlay, 0.25 * hold_pct, frame, 1 - 0.25 * hold_pct, 0, frame)

    cx, cy, r = w // 2, h // 2, 60
    angle = int(360 * hold_pct)
    cv2.circle(frame, (cx, cy), r + 4, (30, 30, 30), -1)
    cv2.ellipse(frame, (cx, cy), (r, r), -90, 0, angle, (0, 60, 255), 6)

    label = "Hold to End Stream"
    (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.8, 2)
    cv2.putText(frame, label, ((w - tw) // 2, cy + r + 35),
                cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 60, 255), 2, cv2.LINE_AA)
