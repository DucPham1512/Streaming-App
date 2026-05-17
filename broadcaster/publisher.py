"""LiveKit video publisher — thin wrapper around livekit-rtc.

Exposes a sync API to the OpenCV capture loop (Commit 6b-iii / loop.py)
while keeping the livekit-rtc asyncio machinery on its own thread.

Threading model:
  * Owner thread (e.g. demo.py / loop.py): blocking OpenCV capture; calls
    .start(), .publish_frame(bgr_ndarray), .stop().
  * Worker thread: runs an asyncio event loop, holds the rtc.Room and the
    rtc.VideoSource, performs connect / publish_track / disconnect.

Why a dedicated thread:
  livekit-rtc is asyncio-native (aiohttp, awaitable Room.connect, etc.).
  Bridging it into a sync OpenCV `cv2.VideoCapture` loop without blocking
  the capture is cleanest with a one-loop-per-process worker. asyncio.run()
  per-call would tear the connection down between frames.

Frame format:
  capture_frame() takes BGR uint8 numpy arrays from OpenCV. We convert to
  BGRA (alpha=255) once per frame and hand the bytes to livekit-rtc via
  VideoBufferType.BGRA. cv2 already provides cvtColor for this — fast and
  GIL-friendly (releases the GIL inside the C ext).

See docs/decisions/001-livekit-over-mux.md for the rationale on choosing
self-hosted LiveKit, and 003-python-broadcaster-not-phone.md for why the
publisher lives in this Python process at all.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

from livekit import rtc

log = logging.getLogger(__name__)


class LiveKitPublisher:
    """Publishes a single camera video track to a LiveKit room.

    Audio is intentionally out of scope for this first cut — add a mic
    AudioSource alongside in a follow-up if/when we need talking-head
    voice. For a 10-person demo, video-only is fine and keeps the
    failure surface small.

    Use:
        pub = LiveKitPublisher(url, token, width=1280, height=720)
        pub.start()                       # blocks briefly while connecting
        while capturing:
            pub.publish_frame(bgr_frame)  # non-blocking, drops if not ready
        pub.stop()
    """

    def __init__(
        self,
        livekit_url: str,
        token: str,
        width: int,
        height: int,
        *,
        track_name: str = "broadcaster-camera",
    ):
        self._url = livekit_url
        self._token = token
        self._width = width
        self._height = height
        self._track_name = track_name

        # State owned by the worker thread; main thread reads these via
        # atomic-ish attribute access (single-word reads in CPython).
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._room: Optional[rtc.Room] = None
        self._source: Optional[rtc.VideoSource] = None
        self._ready = threading.Event()    # set after connect + publish_track
        self._error: Optional[BaseException] = None

        self._worker: Optional[threading.Thread] = None
        self._stop_requested = False

        # Preallocated BGRA buffer reused per frame to avoid per-frame allocs.
        self._bgra_buf: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # Public sync API (called from the capture thread)
    # ------------------------------------------------------------------

    def start(self, *, connect_timeout_seconds: float = 10.0) -> None:
        """Spin up the worker thread and block until the track is published.

        Raises whatever the worker hit during connect (LiveKit reachability,
        bad token, etc.) so the caller can decide to bail or fall back.
        """
        if self._worker is not None:
            raise RuntimeError("LiveKitPublisher.start() called twice")
        self._worker = threading.Thread(
            target=self._run_worker, name="livekit-publisher", daemon=True
        )
        self._worker.start()

        if not self._ready.wait(timeout=connect_timeout_seconds):
            if self._error is not None:
                raise self._error
            raise TimeoutError(
                f"LiveKit publisher did not become ready within "
                f"{connect_timeout_seconds:.1f}s (no error reported)."
            )
        if self._error is not None:
            raise self._error

    def publish_frame(self, frame_bgr: np.ndarray) -> bool:
        """Push a BGR uint8 numpy frame to LiveKit. Returns False if dropped.

        Drops silently in the following cases:
          - publisher not yet started or already stopped
          - frame shape mismatch (caller should reconfigure)
        These are not exceptions because they're routine during connect /
        teardown and the caller is in a tight render loop.
        """
        if not self._ready.is_set() or self._source is None or self._stop_requested:
            return False
        if frame_bgr.shape[0] != self._height or frame_bgr.shape[1] != self._width:
            log.warning(
                "Frame shape %s does not match publisher %dx%d; dropping.",
                frame_bgr.shape, self._width, self._height,
            )
            return False

        # Convert BGR -> BGRA in a preallocated buffer to skip per-frame alloc.
        if self._bgra_buf is None:
            self._bgra_buf = np.empty(
                (self._height, self._width, 4), dtype=np.uint8
            )
        cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA, dst=self._bgra_buf)

        vframe = rtc.VideoFrame(
            self._width,
            self._height,
            rtc.VideoBufferType.BGRA,
            self._bgra_buf.tobytes(),
        )
        # capture_frame is sync and thread-safe to call from outside the loop.
        self._source.capture_frame(
            vframe, timestamp_us=int(time.monotonic_ns() / 1000)
        )
        return True

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        """Disconnect from the room and join the worker thread."""
        if self._worker is None:
            return
        self._stop_requested = True
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._worker.join(timeout=timeout_seconds)
        self._worker = None

    @property
    def ready(self) -> bool:
        """True once track is published and frames will be accepted."""
        return self._ready.is_set() and not self._stop_requested

    # ------------------------------------------------------------------
    # Worker (asyncio side)
    # ------------------------------------------------------------------

    def _run_worker(self) -> None:
        """Worker thread entry point.

        Runs an asyncio event loop forever (until stop() requests it stop)
        with the Room and VideoSource bound to that loop.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_connect())
            # If connect raised, _ready stays clear and the main thread
            # will re-raise via .start(); avoid running the loop further.
            if self._error is None:
                self._loop.run_forever()
            self._loop.run_until_complete(self._async_teardown())
        except BaseException as e:                  # noqa: BLE001
            log.exception("LiveKit worker crashed")
            self._error = e
            self._ready.set()  # unblock .start() so it can raise
        finally:
            self._loop.close()
            self._loop = None

    async def _async_connect(self) -> None:
        try:
            self._room = rtc.Room()
            await self._room.connect(self._url, self._token)
            log.info("LiveKit room connected (sid=%s)", self._room.sid)

            self._source = rtc.VideoSource(self._width, self._height)
            track = rtc.LocalVideoTrack.create_video_track(
                self._track_name, self._source
            )
            opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
            await self._room.local_participant.publish_track(track, opts)
            log.info("LiveKit video track published")
            self._ready.set()
        except BaseException as e:                  # noqa: BLE001
            self._error = e
            self._ready.set()  # unblock waiters; .start() re-raises
            raise

    async def _async_teardown(self) -> None:
        if self._source is not None:
            try:
                await self._source.aclose()
            except Exception:                       # noqa: BLE001
                log.exception("VideoSource.aclose failed; continuing")
        if self._room is not None:
            try:
                await self._room.disconnect()
            except Exception:                       # noqa: BLE001
                log.exception("Room.disconnect failed; continuing")
