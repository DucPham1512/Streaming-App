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
import urllib.error
import urllib.request
import json

import cv2
import dotenv
import numpy as np

dotenv.load_dotenv()

from detector import GestureDetector, GESTURE_COMMANDS, draw_landmarks
from effects import (
    draw_gesture_label, draw_end_countdown,
    HeartEffect, ConfettiEffect, FireworksEffect, LikeEffect,
)
from client import GestureClient

# Make the sibling `broadcaster/` package importable. Commit 6b will move
# this whole file into that package and the path hack goes away.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
from broadcaster.local_view import CommentBuffer, render_comment_column


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOCKET_URL  = os.getenv("SOCKET_URL", "http://localhost:5001")
API_BASE    = os.getenv("API_BASE", SOCKET_URL)
API_KEY     = os.getenv("API_KEY", "")
WINDOW_NAME = "Gesture Demo  |  Press Q to quit"


def _http_request(method: str, path: str, body: dict | None = None) -> dict | None:
    """Tiny stdlib HTTP helper. Returns parsed JSON or None on error."""
    url = f"{API_BASE.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if API_KEY:
        req.add_header("Authorization", f"Bearer {API_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[HTTP {method} {path}] {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"[HTTP {method} {path}] {e}")
    return None


def discover_active_stream_id() -> str | None:
    """Hit GET /api/v1/streams and return the most recently started active stream."""
    result = _http_request("GET", "/api/v1/streams")
    if not result:
        return None
    streams = result.get("streams") or []
    if not streams:
        print("[discover] No active streams found.")
        return None
    if len(streams) > 1:
        print(f"[discover] {len(streams)} active streams — picking most recent.")
    # list_streams already orders by started_at desc, so streams[0] is newest
    chosen = streams[0]
    print(f"[discover] Using stream {chosen['id']} ({chosen.get('title')!r})")
    return chosen["id"]


def end_stream_via_api(stream_id: str) -> bool:
    """Hit POST /api/v1/streams/<id>/end to actually terminate the stream."""
    result = _http_request("POST", f"/api/v1/streams/{stream_id}/end")
    return result is not None

# How many frames the fist must be held to trigger end_stream (~3 s at 30 fps)
END_STREAM_HOLD_FRAMES = 90


# ---------------------------------------------------------------------------
# Effect manager
# ---------------------------------------------------------------------------

class EffectManager:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self._effects = []

    def trigger(self, effect_name: str, origin: tuple[int, int] | None = None):
        if effect_name == "heart":
            self._effects.append(HeartEffect(self.w, self.h, origin=origin))
        elif effect_name == "like":
            self._effects.append(LikeEffect(self.w, self.h, origin=origin))
        elif effect_name == "confetti":
            self._effects.append(ConfettiEffect(self.w, self.h, origin=origin))
        elif effect_name == "fireworks":
            self._effects.append(FireworksEffect(self.w, self.h, origin=origin))

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
    "like_stream":             "like",
    "entertainment_confetti":  "confetti",
    "entertainment_heart":     "heart",
    "entertainment_fireworks": "fireworks",
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(stream_id: str, dry_run: bool = False, camera: int = 0):
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera {camera}. Try a different --camera index.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Camera: {w}x{h}")
    print(f"Stream ID: {stream_id}")
    print(f"Backend: {SOCKET_URL}")

    # Comment buffer fed by the Socket.IO client's `comment_received` handler.
    # Drawn in the local preview only — never composited into the published frame.
    comments = CommentBuffer(capacity=8, ttl_seconds=10.0)

    # Connect Socket.IO client in background
    client = GestureClient(SOCKET_URL, API_KEY or None, on_comment=comments.add)
    if not dry_run:
        t = threading.Thread(target=client.connect, daemon=True)
        t.start()
        time.sleep(1.5)   # give the connection a moment
        # Subscribe to the stream's room so `comment_received` events reach us.
        client.join_room(stream_id)

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

            gesture, hand_lm, anchor_norm, secondary_norm = detector.process(rgb)

            # Draw hand skeleton
            if hand_lm:
                draw_landmarks(frame, hand_lm)

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
                        # Convert normalized coords -> pixel coords for the local preview
                        origin_px = None
                        if anchor_norm is not None:
                            origin_px = (int(anchor_norm[0] * w), int(anchor_norm[1] * h))

                        sent = False
                        if not dry_run:
                            sent = client.send_gesture(
                                command, stream_id,
                                anchor=anchor_norm, secondary=secondary_norm,
                            )
                        else:
                            sent = True

                        if sent:
                            local_fx = COMMAND_LOCAL_EFFECT.get(command)
                            if local_fx:
                                effects.trigger(local_fx, origin=origin_px)
                            if command == "mute_toggle":
                                muted = not muted
                            print(f"  Gesture: {gesture:15s}  Command: {command}  anchor={anchor_norm}")

            # Trigger end_stream after full hold
            if fist_hold_frames == END_STREAM_HOLD_FRAMES:
                if not dry_run:
                    client.send_gesture("end_stream", stream_id, confidence=1.0,
                                        anchor=anchor_norm)
                    # Socket event alone only broadcasts a message; we also need
                    # to call the REST endpoint to actually terminate the stream.
                    if end_stream_via_api(stream_id):
                        print("  Gesture: fist            Command: end_stream  (TERMINATED)")
                    else:
                        print("  Gesture: fist            Command: end_stream  (API call failed)")
                else:
                    print("  Gesture: fist            Command: end_stream  (dry-run)")
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

            # Scrolling chat overlay (right edge) — local preview only.
            render_comment_column(frame, comments)

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
        "--stream-id", default=None,
        help="UUID of the stream. If omitted, auto-discovers the most recent "
             "active stream via GET /api/v1/streams.",
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

    stream_id = args.stream_id
    if not stream_id and not args.dry_run:
        stream_id = discover_active_stream_id()
        if not stream_id:
            print("ERROR: No --stream-id given and no active stream found via API.")
            print(f"       Tried: {API_BASE}/api/v1/streams")
            sys.exit(1)
    elif not stream_id:
        stream_id = "dry-run-stream"

    run(stream_id=stream_id, dry_run=args.dry_run, camera=args.camera)


if __name__ == "__main__":
    main()
