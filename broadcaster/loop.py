"""End-to-end capture → detect → composite → publish loop.

This is the new heart of the broadcaster, replacing the body of the
historical `gesture_demo/demo.py`. Designed to be wired up by __main__.py
(or by tests) with already-prepared collaborators:

  * LiveKitPublisher    — connected + ready, accepts BGR numpy frames
  * GestureClient       — Socket.IO connected + already in the stream's room
  * CommentBuffer       — fed by client's on_comment callback
  * (camera index)      — passed to cv2.VideoCapture

Frame ordering matters:

  1. Camera capture + mirror
  2. Gesture detection + effect triggers
  3. `effects.draw(frame)` — BURNS EFFECTS into the frame
  4. `publisher.publish_frame(frame)` — viewers receive camera+effects only.
  5. Streamer-only overlays added on top: hand landmarks, HUD, scrolling
     comments. These never reach LiveKit; see decision 002.
  6. `cv2.imshow` shows the fully-overlaid local frame.

Modifying the frame after step 4 is safe because publish_frame copies
the bytes synchronously (BGR→BGRA into a preallocated buf → tobytes()).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import cv2

from .detector import (
    GESTURE_COMMANDS,
    GestureDetector,
    draw_landmarks,
)
from .effects import (
    ConfettiEffect,
    FireworksEffect,
    HeartEffect,
    LikeEffect,
    draw_end_countdown,
    draw_gesture_label,
)

log = logging.getLogger(__name__)


# Gesture → local effect name. Mirrors the legacy demo.py mapping; kept
# here because the broadcaster owns burn-in compositing now (decision 002),
# so these effects must be triggered on the broadcaster side and drawn into
# the frame BEFORE publishing.
COMMAND_LOCAL_EFFECT: dict[str, Optional[str]] = {
    "mute_toggle":             None,
    "end_stream":              None,
    "like_stream":             "like",
    "entertainment_confetti":  "confetti",
    "entertainment_heart":     "heart",
    "entertainment_fireworks": "fireworks",
}

END_STREAM_HOLD_FRAMES = 90      # ~3s @ 30 fps fist hold to terminate
WINDOW_NAME = "VSR Broadcaster — Q quit, M mute, R reset effects"


@dataclass
class LoopResult:
    """What the loop returned and why, so __main__.py can decide next steps."""
    reason: str          # "quit" | "end_stream_gesture" | "camera_error"
    frames_published: int


class _EffectManager:
    """Local effect manager — additive list of in-flight visual effects.

    Lifted from gesture_demo/demo.py's inline EffectManager. The plan is
    that Commit 15 deletes the legacy file once nothing imports from it;
    until then this class is the single source of truth for live effect
    composition.
    """
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self._effects: list = []

    def trigger(self, effect_name: str, origin: Optional[tuple[int, int]] = None):
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


class BroadcastLoop:
    """Owns the camera, the detector, and the rendering split.

    Lifecycle:
        loop = BroadcastLoop(...)
        result = loop.run()        # blocks until quit or end_stream
        # caller handles cleanup of publisher/client based on result.reason
    """

    def __init__(
        self,
        *,
        stream_id: str,
        publisher,                        # broadcaster.publisher.LiveKitPublisher
        client,                           # broadcaster.client.GestureClient
        comments,                         # broadcaster.local_view.CommentBuffer
        camera_index: int,
        width: int = 1280,
        height: int = 720,
        show_preview: bool = True,
        builtin_actions: Optional[dict] = None,
        classifier=None,                  # broadcaster.custom_classifier.CustomGestureClassifier
        api_client=None,                  # broadcaster.api_client.ApiClient (for R/E/L)
    ):
        """
        :param builtin_actions: maps built-in gesture name → effective action
            (override or default). When None, falls back to the hardcoded
            GESTURE_COMMANDS in detector.py — no per-user override applied.
        :param classifier: optional k-NN matcher for user-recorded custom
            gestures. None disables custom-gesture detection entirely.
        """
        self._stream_id = stream_id
        self._publisher = publisher
        self._client = client
        self._comments = comments
        self._camera_index = camera_index
        self._width = width
        self._height = height
        self._show_preview = show_preview
        self._builtin_actions = builtin_actions or {}
        self._classifier = classifier
        self._api_client = api_client
        self._recording_session = None  # set when R is pressed

    def run(self) -> LoopResult:
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            log.error("Cannot open camera %d", self._camera_index)
            return LoopResult(reason="camera_error", frames_published=0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        # Real dimensions may differ slightly from requested.
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (w, h) != (self._width, self._height):
            log.warning(
                "Camera negotiated %dx%d (requested %dx%d). Publisher was "
                "configured for the requested size; frames will be dropped.",
                w, h, self._width, self._height,
            )

        effects = _EffectManager(w, h)
        muted = False
        fist_hold_frames = 0
        last_stable_gesture: Optional[str] = None
        reason = "quit"
        frames_published = 0

        with GestureDetector() as detector:
            while True:
                ret, frame = cap.read()
                if not ret:
                    log.error("Camera read failed; ending loop")
                    reason = "camera_error"
                    break

                frame = cv2.flip(frame, 1)   # mirror for natural interaction
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                gesture, hand_lm, anchor_norm, secondary_norm = detector.process(rgb)

                # ---- Advance the recording state machine (R hotkey) ----
                # Done synchronously per-frame so capture is paced by the
                # camera, not the wall clock. Skip frames with no hand
                # detected; the streamer can hold still a beat longer
                # without breaking the recording.
                if self._recording_session is not None:
                    self._recording_session.tick(hand_lm)
                    if self._recording_session.phase == "done":
                        self._finalize_recording()
                    elif self._recording_session.phase == "aborted":
                        self._recording_session = None

                # ---- Fist-hold for end_stream ----
                if gesture == "fist":
                    fist_hold_frames += 1
                else:
                    fist_hold_frames = 0
                end_stream_progress = min(1.0, fist_hold_frames / END_STREAM_HOLD_FRAMES)

                # ---- Leading-edge gesture commands ----
                # Resolve via 3-step priority:
                #   1. Rule-based built-in detector returned a name.
                #      → fire user's effective action for it (override or default).
                #   2. Otherwise, run the custom k-NN classifier each frame.
                #      → fire the matched template's action when confirmed.
                if gesture != last_stable_gesture:
                    last_stable_gesture = gesture
                    if gesture is not None:
                        # Override takes precedence over hardcoded default.
                        cmd = self._builtin_actions.get(gesture) or GESTURE_COMMANDS.get(gesture)
                        if cmd and cmd != "end_stream":
                            origin_px = None
                            if anchor_norm is not None:
                                origin_px = (
                                    int(anchor_norm[0] * w),
                                    int(anchor_norm[1] * h),
                                )
                            sent = self._client.send_gesture(
                                cmd, self._stream_id,
                                anchor=anchor_norm, secondary=secondary_norm,
                            )
                            if sent:
                                local_fx = COMMAND_LOCAL_EFFECT.get(cmd)
                                if local_fx:
                                    effects.trigger(local_fx, origin=origin_px)
                                if cmd == "mute_toggle":
                                    muted = not muted

                # ---- Custom k-NN classifier (only runs when no built-in match) ----
                if (
                    self._classifier is not None
                    and gesture is None
                    and hand_lm is not None
                ):
                    custom = self._classifier.classify(hand_lm)
                    if custom is not None:
                        log.info(
                            "Custom gesture '%s' → action '%s'",
                            custom.name, custom.action,
                        )
                        sent = self._client.send_gesture(
                            custom.action, self._stream_id,
                            anchor=anchor_norm, secondary=secondary_norm,
                        )
                        if sent:
                            local_fx = COMMAND_LOCAL_EFFECT.get(custom.action)
                            if local_fx:
                                origin_px = None
                                if anchor_norm is not None:
                                    origin_px = (
                                        int(anchor_norm[0] * w),
                                        int(anchor_norm[1] * h),
                                    )
                                effects.trigger(local_fx, origin=origin_px)
                            if custom.action == "mute_toggle":
                                muted = not muted

                # ---- Full fist hold → end stream ----
                if fist_hold_frames == END_STREAM_HOLD_FRAMES:
                    self._client.send_gesture(
                        "end_stream", self._stream_id,
                        confidence=1.0, anchor=anchor_norm,
                    )
                    reason = "end_stream_gesture"
                    break

                # ---- Step 3+4: composite effects, publish to LiveKit ----
                effects.draw(frame)
                if self._publisher.publish_frame(frame):
                    frames_published += 1

                # ---- Step 5+6: streamer-only overlays + preview ----
                if self._show_preview:
                    self._draw_local_overlays(
                        frame, gesture, hand_lm, anchor_norm,
                        end_stream_progress, muted,
                    )
                    cv2.imshow(WINDOW_NAME, frame)

                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        reason = "quit"
                        break
                    elif key == ord("m"):
                        muted = not muted
                    elif key == ord("c"):
                        # 'c' clears effects (used to be 'r' before the
                        # custom-gesture recording hotkey took 'r').
                        effects.clear()
                    elif key == ord("r"):
                        self._start_recording()
                    elif key == ord("e"):
                        self._erase_last_template()
                    elif key == ord("l"):
                        self._list_templates()

        cap.release()
        if self._show_preview:
            cv2.destroyAllWindows()
        return LoopResult(reason=reason, frames_published=frames_published)

    # ------------------------------------------------------------------
    # Streamer-only overlay rendering (lands in the local cv2 window only)
    # ------------------------------------------------------------------

    def _draw_local_overlays(
        self, frame, gesture, hand_lm, anchor_norm, end_stream_progress, muted,
    ) -> None:
        h, w = frame.shape[:2]

        if hand_lm:
            draw_landmarks(frame, hand_lm)

        if gesture == "fist":
            draw_end_countdown(frame, end_stream_progress)

        # Connection status badge (top-right)
        if self._publisher.ready:
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
            if cmd:
                cooldown_pct = self._client.cooldown_fraction(cmd)
        draw_gesture_label(frame, gesture, cooldown_pct)

        # Recording HUD (overrides nothing — drawn centered top)
        if self._recording_session is not None:
            self._draw_recording_hud(frame)

        # Scrolling comments column (right edge)
        from .local_view import render_comment_column
        render_comment_column(frame, self._comments)

    def _draw_recording_hud(self, frame) -> None:
        """Center-top banner showing recording phase + sample progress."""
        h, w = frame.shape[:2]
        session = self._recording_session
        if session is None:
            return
        phase = session.phase
        if phase == "countdown":
            text = session.countdown_label()
            color = (40, 180, 255)        # amber
        elif phase == "capturing":
            text = session.progress_label()
            color = (60, 220, 60)         # green
        else:
            text = "Saving…"
            color = (200, 200, 200)
        # Background pill
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.8, 2)
        x = (w - tw) // 2
        y = 60
        overlay = frame.copy()
        cv2.rectangle(overlay, (x - 16, y - th - 12), (x + tw + 16, y + 12),
                      (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, 0.8,
                    color, 2, cv2.LINE_AA)

    # ------------------------------------------------------------------
    # R/E/L hotkey handlers
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        if self._api_client is None:
            log.warning("Recording disabled: no api_client provided")
            return
        if self._recording_session is not None:
            log.info("Already recording; ignoring R")
            return
        # Pull the name from the terminal. This blocks the camera loop
        # for a beat — acceptable, the streamer just initiated it.
        try:
            print()  # newline so the prompt isn't appended to a log line
            name = input("Gesture name (blank to cancel): ").strip()
        except EOFError:
            return
        if not name:
            print("Recording cancelled.")
            return
        from .recording import RecordingSession
        self._recording_session = RecordingSession(name=name)
        log.info("Recording '%s' — hold the pose...", name)

    def _finalize_recording(self) -> None:
        session = self._recording_session
        self._recording_session = None
        if session is None:
            return
        from .recording import upload_recording
        from .api_client import ApiError
        try:
            resp = upload_recording(self._api_client, session)
            tpl = resp.get("template", {})
            log.info(
                "Saved template '%s' (id=%s) with %d samples. "
                "Assign an action via the FE Gesture Library.",
                session.name, tpl.get("id"), len(session.samples),
            )
        except ApiError as e:
            log.error("Failed to upload recording: %s", e)

    def _erase_last_template(self) -> None:
        if self._api_client is None:
            log.warning("E disabled: no api_client provided")
            return
        from .api_client import ApiError
        try:
            resp = self._api_client.get("/api/v1/gestures/templates")
            templates = resp.get("templates", [])
        except ApiError as e:
            log.error("List templates failed: %s", e)
            return
        if not templates:
            log.info("No templates to erase.")
            return
        # /templates is ordered by created_at desc, so [0] is the newest.
        newest = templates[0]
        try:
            self._api_client.delete(
                f"/api/v1/gestures/templates/{newest['id']}"
            )
            log.info("Erased template '%s'", newest.get("name"))
        except ApiError as e:
            log.error("Delete failed: %s", e)

    def _list_templates(self) -> None:
        if self._api_client is None:
            log.warning("L disabled: no api_client provided")
            return
        from .api_client import ApiError
        try:
            resp = self._api_client.get("/api/v1/gestures/templates")
            templates = resp.get("templates", [])
        except ApiError as e:
            log.error("List templates failed: %s", e)
            return
        if not templates:
            print("\nNo templates recorded yet. Press R to record one.\n")
            return
        print(f"\n{len(templates)} template(s):")
        for t in templates:
            print(
                f"  - {t['name']:24s}  action={t['action']:24s}  "
                f"samples={t['sample_count']}  handedness={t['handedness']}"
            )
        print()
