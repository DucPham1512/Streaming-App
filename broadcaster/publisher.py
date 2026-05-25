"""LiveKit publisher — thin wrapper around livekit-rtc for video + audio.

Exposes a sync API to the OpenCV capture loop (Commit 6b-iii / loop.py)
while keeping the livekit-rtc asyncio machinery on its own thread. The
microphone is handled internally via a sounddevice InputStream whose
callback fires on the PortAudio audio thread; audio frames are
trampolined onto the worker asyncio loop with `call_soon_threadsafe`.

Threading model:
  * Owner thread (e.g. demo.py / loop.py): blocking OpenCV capture; calls
    .start(), .publish_frame(bgr_ndarray), .stop().
  * Worker thread: runs an asyncio event loop, holds the rtc.Room, the
    rtc.VideoSource, and the rtc.AudioSource. Performs connect /
    publish_track / disconnect.
  * PortAudio audio thread: sounddevice fires the mic callback ~100x/s
    (10ms blocks @ 48kHz); the callback marshals each frame onto the
    worker loop without blocking.

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


# Audio capture constants. 48kHz mono 10ms frames is what WebRTC pipelines
# expect; matches LiveKit's default and avoids per-frame resampling.
_AUDIO_SAMPLE_RATE = 48000
_AUDIO_CHANNELS = 1
_AUDIO_BLOCK_MS = 10
_AUDIO_BLOCK_SAMPLES = _AUDIO_SAMPLE_RATE * _AUDIO_BLOCK_MS // 1000   # 480


class LiveKitPublisher:
    """Publishes a camera video track + microphone audio to a LiveKit room.

    Audio uses the system default input device (sounddevice / PortAudio).
    If the mic is missing or PortAudio isn't installed, the publisher logs
    a warning and continues with video only — a missing mic must NOT crash
    the whole stream.

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
        video_track_name: str = "broadcaster-camera",
        audio_track_name: str = "broadcaster-mic",
        enable_audio: bool = True,
        audio_device: Optional[int] = None,
    ):
        """
        :param audio_device: sounddevice device index; None = system default.
                             Run `python -m sounddevice` to list devices.
        :param enable_audio: set False to publish a silent stream (CI/testing).
        """
        self._url = livekit_url
        self._token = token
        self._width = width
        self._height = height
        self._video_track_name = video_track_name
        self._audio_track_name = audio_track_name
        self._enable_audio = enable_audio
        self._audio_device = audio_device

        # State owned by the worker thread; main thread reads these via
        # atomic-ish attribute access (single-word reads in CPython).
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._room: Optional[rtc.Room] = None
        self._source: Optional[rtc.VideoSource] = None
        self._audio_source: Optional[rtc.AudioSource] = None
        self._mic_stream = None  # sounddevice.InputStream when running
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
            sid = await self._room.sid
            log.info("LiveKit room connected (sid=%s)", sid)

            # --- Video track ---
            self._source = rtc.VideoSource(self._width, self._height)
            vtrack = rtc.LocalVideoTrack.create_video_track(
                self._video_track_name, self._source
            )
            await self._room.local_participant.publish_track(
                vtrack,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA),
            )
            log.info("LiveKit video track published")

            # --- Audio track (best-effort: missing mic must not block video) ---
            if self._enable_audio:
                try:
                    self._audio_source = rtc.AudioSource(
                        _AUDIO_SAMPLE_RATE, _AUDIO_CHANNELS
                    )
                    atrack = rtc.LocalAudioTrack.create_audio_track(
                        self._audio_track_name, self._audio_source
                    )
                    await self._room.local_participant.publish_track(
                        atrack,
                        rtc.TrackPublishOptions(
                            source=rtc.TrackSource.SOURCE_MICROPHONE
                        ),
                    )
                    self._start_mic_capture()
                    log.info("LiveKit audio track published; mic running")
                except Exception:                   # noqa: BLE001
                    log.exception(
                        "Audio setup failed; continuing with video-only stream"
                    )
                    self._audio_source = None
                    self._mic_stream = None

            self._ready.set()
        except BaseException as e:                  # noqa: BLE001
            self._error = e
            self._ready.set()  # unblock waiters; .start() re-raises
            raise

    def _start_mic_capture(self) -> None:
        """Open the sounddevice input stream that pushes PCM frames to LiveKit.

        Called from inside _async_connect once the AudioSource has been
        published. The PortAudio callback runs on a separate thread; each
        frame is trampolined onto the worker loop via call_soon_threadsafe.
        """
        # Local import keeps publisher.py importable on systems without
        # PortAudio installed — the failure mode is only at .start() time
        # when audio is enabled, not at module import time.
        import sounddevice as sd

        def _on_audio_block(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                # XRUN, overflow, etc. Log but don't drop the frame.
                log.warning("sounddevice status: %s", status)
            # indata is a (frames, channels) int16 ndarray. tobytes() is C-contig.
            pcm_bytes = bytes(indata)
            try:
                frame = rtc.AudioFrame(
                    pcm_bytes,
                    _AUDIO_SAMPLE_RATE,
                    _AUDIO_CHANNELS,
                    frames,
                )
            except Exception:                       # noqa: BLE001
                log.exception("Failed to wrap PCM block into AudioFrame")
                return
            if self._loop is None or self._audio_source is None:
                return
            # Schedule the async capture on the worker loop, non-blocking.
            self._loop.call_soon_threadsafe(self._enqueue_audio_frame, frame)

        self._mic_stream = sd.InputStream(
            samplerate=_AUDIO_SAMPLE_RATE,
            channels=_AUDIO_CHANNELS,
            dtype="int16",
            blocksize=_AUDIO_BLOCK_SAMPLES,
            callback=_on_audio_block,
            device=self._audio_device,
        )
        self._mic_stream.start()

    def _enqueue_audio_frame(self, frame: "rtc.AudioFrame") -> None:
        """Worker-loop callback: hand one AudioFrame to LiveKit.

        AudioSource.capture_frame is a coroutine, but we don't want to
        await it from the PortAudio thread. asyncio.create_task() schedules
        it on the currently-running worker loop without blocking.
        """
        if self._audio_source is None:
            return
        try:
            asyncio.create_task(self._audio_source.capture_frame(frame))
        except Exception:                           # noqa: BLE001
            log.exception("Failed to schedule AudioSource.capture_frame")

    async def _async_teardown(self) -> None:
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:                       # noqa: BLE001
                log.exception("Mic stream teardown failed; continuing")
        if self._audio_source is not None:
            try:
                await self._audio_source.aclose()
            except Exception:                       # noqa: BLE001
                log.exception("AudioSource.aclose failed; continuing")
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
