"""
Hand Gesture Demo — main entry point.

Usage:
    python demo.py --stream-id <stream-uuid>

Controls:
    Q  — quit
    M  — toggle mute display (local only, for testing without a backend)
    R  — reset all effects
"""

import argparse
import os
import sys
import threading
import time

import cv2
import dotenv
import numpy as np

dotenv.load_dotenv()

from detector import GestureDetector, GESTURE_COMMANDS
from effects import (
    draw_landmarks, draw_gesture_label, draw_end_countdown,
    HeartEffect, ConfettiEffect, FireworksEffect,
)
from client import GestureClient


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOCKET_URL  = os.getenv("SOCKET_URL", "http://localhost:5001")
API_KEY     = os.getenv("API_KEY", "")
WINDOW_NAME = "Gesture Demo  |  Press Q to quit"

# How many frames the fist must be held to trigger end_stream (~3 s at 30 fps)
END_STREAM_HOLD_FRAMES = 90


# ---------------------------------------------------------------------------
# Effect manager
# ---------------------------------------------------------------------------

class EffectManager:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self._effects = []

    def trigger(self, effect_name: str):
        if effect_name == "heart":
            self._effects.append(HeartEffect(self.w, self.h))
        elif effect_name == "confetti":
            self._effects.append(ConfettiEffect(self.w, self.h))
        elif effect_name == "fireworks":
            self._effects.append(FireworksEffect(self.w, self.h))

    def draw(self, frame):
        for fx in self._effects:
            fx.draw(frame)
        self._effects = [fx for fx in self._effects if fx.alive]

    def clear(self):
        self._effects.clear()


# ---------------------------------------------------------------------------
# Gesture → local effect mapping
# ---------------------------------------------------------------------------

COMMAND_LOCAL_EFFECT = {
    "mute_toggle":             None,
    "end_stream":              None,
    "like_stream":             "heart",
    "entertainment_confetti":  "confetti",
    "entertainment_heart":     "heart",
    "entertainment_fireworks": "fireworks",
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(stream_id: str, dry_run: bool = False):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Cannot open webcam (device 0). Try --camera 1 if you have multiple cameras.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Camera: {w}x{h}")
    print(f"Stream ID: {stream_id}")
    print(f"Backend: {SOCKET_URL}")

    # Connect Socket.IO client in background
    client = GestureClient(SOCKET_URL, API_KEY or None)
    if not dry_run:
        t = threading.Thread(target=client.connect, daemon=True)
        t.start()
        time.sleep(1.5)   # give the connection a moment

    effects = EffectManager(w, h)
    muted = False
    fist_hold_frames = 0
    last_stable_gesture = None

    with GestureDetector() as detector:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)   # mirror for natural interaction
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            gesture, hand_lm = detector.process(rgb)

            # Draw hand skeleton
            if hand_lm:
                draw_landmarks(
                    frame, hand_lm,
                    detector.drawing, detector._mp_hands, detector.drawing_styles,
                )

            # -----------------------------------------------------------------
            # Fist hold logic (end stream requires sustained hold)
            # -----------------------------------------------------------------
            if gesture == "fist":
                fist_hold_frames += 1
            else:
                fist_hold_frames = 0

            end_stream_progress = min(1.0, fist_hold_frames / END_STREAM_HOLD_FRAMES)
            if gesture == "fist":
                draw_end_countdown(frame, end_stream_progress)

            # -----------------------------------------------------------------
            # Fire command when gesture becomes stable (leading edge only)
            # -----------------------------------------------------------------
            if gesture != last_stable_gesture:
                last_stable_gesture = gesture

                if gesture is not None:
                    command = GESTURE_COMMANDS.get(gesture)
                    if command and command != "end_stream":
                        sent = False
                        if not dry_run:
                            sent = client.send_gesture(command, stream_id)
                        else:
                            sent = True

                        if sent:
                            local_fx = COMMAND_LOCAL_EFFECT.get(command)
                            if local_fx:
                                effects.trigger(local_fx)
                            if command == "mute_toggle":
                                muted = not muted
                            print(f"  Gesture: {gesture:15s}  Command: {command}")

            # Trigger end_stream after full hold
            if fist_hold_frames == END_STREAM_HOLD_FRAMES:
                if not dry_run:
                    client.send_gesture("end_stream", stream_id, confidence=1.0)
                print("  Gesture: fist            Command: end_stream  (SENT)")
                # Small delay to prevent re-trigger
                fist_hold_frames = END_STREAM_HOLD_FRAMES + 1

            # -----------------------------------------------------------------
            # Draw effects
            # -----------------------------------------------------------------
            effects.draw(frame)

            # -----------------------------------------------------------------
            # HUD
            # -----------------------------------------------------------------
            # Connection status badge
            if not dry_run:
                if client.connected:
                    cv2.circle(frame, (w - 18, 18), 8, (0, 220, 0), -1)
                    cv2.putText(frame, "LIVE", (w - 60, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), 1, cv2.LINE_AA)
                else:
                    cv2.circle(frame, (w - 18, 18), 8, (0, 60, 255), -1)
                    cv2.putText(frame, "OFFLINE", (w - 80, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 60, 255), 1, cv2.LINE_AA)

            # Mute badge
            if muted:
                overlay = frame.copy()
                cv2.rectangle(overlay, (10, 10), (110, 46), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
                cv2.putText(frame, "MUTED", (18, 36),
                            cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 60, 255), 2, cv2.LINE_AA)

            # Gesture label + cooldown arc
            cooldown_pct = 0.0
            if gesture:
                cmd = GESTURE_COMMANDS.get(gesture, "")
                cooldown_pct = client.cooldown_fraction(cmd) if (not dry_run and cmd) else 0.0
            draw_gesture_label(frame, gesture, cooldown_pct)

            # Gesture reference guide (bottom-right)
            _draw_guide(frame, w, h)

            cv2.imshow(WINDOW_NAME, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break
            elif key == ord("m"):
                muted = not muted
            elif key == ord("r"):
                effects.clear()

    cap.release()
    cv2.destroyAllWindows()
    if not dry_run:
        client.disconnect()


def _draw_guide(frame, w: int, h: int):
    """Small reference card in the bottom-right corner."""
    lines = [
        "Gestures:",
        "Open Palm  -> Mute",
        "Fist (hold)-> End Stream",
        "Thumbs Up  -> Like",
        "Peace      -> Confetti",
        "Finger Heart-> Hearts",
        "ILY        -> Fireworks",
    ]
    line_h = 18
    box_h = len(lines) * line_h + 12
    box_w = 220
    x0, y0 = w - box_w - 10, h - box_h - 70

    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + box_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

    for i, line in enumerate(lines):
        color = (220, 220, 220) if i > 0 else (100, 220, 255)
        bold = 2 if i == 0 else 1
        cv2.putText(frame, line, (x0 + 8, y0 + 16 + i * line_h),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, bold, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Hand Gesture Demo")
    parser.add_argument(
        "--stream-id", required=True,
        help="UUID of the active stream (from POST /api/v1/streams)",
    )
    parser.add_argument(
        "--camera", type=int, default=0,
        help="Camera device index (default: 0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run without connecting to the backend (useful for testing gestures offline)",
    )
    args = parser.parse_args()

    run(stream_id=args.stream_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
