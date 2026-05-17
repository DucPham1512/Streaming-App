"""Broadcaster entry point.

Runs the full pipeline on the host machine (camera + mic + display all
require host access, so this is NOT a containerized service):

  1. Talk to the Flask backend's REST API:
     POST /api/v1/streams → receives {stream, publisher_token, livekit_url}.
  2. Start a LiveKitPublisher with the issued credentials.
  3. Connect a Socket.IO GestureClient + join the stream's room so gesture
     commands flow out and chat comments flow in.
  4. Hand both collaborators to BroadcastLoop.run().
  5. On exit (Q pressed or fist-hold), POST /api/v1/streams/<id>/end.

Usage:
    python -m broadcaster --camera 2

Env vars (typically loaded from broadcaster/.env via python-dotenv):
    API_BASE          backend REST URL (default: http://localhost:5001)
    SOCKET_URL        backend Socket.IO URL (default: API_BASE)
    API_KEY           optional Bearer token for authenticated routes
    BROADCAST_CAMERA_INDEX   camera index for cv2.VideoCapture (default: 0)

Out of scope for this commit (lands in Commit 9):
    --login flag, multi-streamer CLI shape, choosing existing stream
    instead of creating one.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

import dotenv

dotenv.load_dotenv()

# Imports are relative (package form) so `python -m broadcaster` works.
# For direct script invocation `python broadcaster/__main__.py`, run via
# `python -m broadcaster` instead.
from .api_client import ApiClient
from .client import GestureClient
from .custom_classifier import CustomGestureClassifier
from .local_view import CommentBuffer
from .loop import BroadcastLoop
from .publisher import LiveKitPublisher


log = logging.getLogger("broadcaster")


# ---------------------------------------------------------------------------
# Backend REST helpers
# ---------------------------------------------------------------------------


def _http_json(method: str, url: str, body: dict | None, api_key: str | None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"{method} {url} → HTTP {e.code}: {e.read().decode()[:200]}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"{method} {url} failed: {e}") from e


def create_stream(api_base: str, api_key: str | None, title: str) -> dict:
    """POST /api/v1/streams. Returns the full response dict."""
    return _http_json(
        "POST",
        f"{api_base.rstrip('/')}/api/v1/streams",
        {"title": title},
        api_key,
    )


def end_stream(api_base: str, api_key: str | None, stream_id: str) -> bool:
    """POST /api/v1/streams/<id>/end. Returns True on 2xx."""
    try:
        _http_json(
            "POST",
            f"{api_base.rstrip('/')}/api/v1/streams/{stream_id}/end",
            None,
            api_key,
        )
        return True
    except Exception as e:
        log.warning("end_stream failed: %s", e)
        return False


def fetch_builtins(api_base: str, api_key: str | None) -> dict[str, str]:
    """GET /api/v1/gestures/builtins. Returns {gesture: effective_action}.

    Falls back to {} (which the caller treats as "use built-in defaults")
    when auth is missing or the call fails. The broadcaster should not
    refuse to start just because the gesture-library endpoint is unreachable.
    """
    if not api_key:
        return {}
    try:
        resp = _http_json(
            "GET",
            f"{api_base.rstrip('/')}/api/v1/gestures/builtins",
            None,
            api_key,
        )
        return {row["gesture"]: row["action"] for row in resp.get("builtins", [])}
    except Exception as e:
        log.warning("fetch_builtins failed (using defaults): %s", e)
        return {}


def fetch_templates(api_base: str, api_key: str | None) -> list[dict]:
    """GET /api/v1/gestures/templates. Returns [] on failure or no auth."""
    if not api_key:
        return []
    try:
        resp = _http_json(
            "GET",
            f"{api_base.rstrip('/')}/api/v1/gestures/templates",
            None,
            api_key,
        )
        return resp.get("templates", [])
    except Exception as e:
        log.warning("fetch_templates failed (no custom gestures): %s", e)
        return []


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VSR broadcaster (laptop side)")
    parser.add_argument(
        "--camera", type=int,
        default=int(os.environ.get("BROADCAST_CAMERA_INDEX", "0")),
        help="cv2.VideoCapture device index",
    )
    parser.add_argument(
        "--title", default="Live now",
        help="initial stream title (can be edited later via PATCH)",
    )
    parser.add_argument(
        "--width", type=int, default=1280,
        help="published video width",
    )
    parser.add_argument(
        "--height", type=int, default=720,
        help="published video height",
    )
    parser.add_argument(
        "--no-audio", action="store_true",
        help="publish video only (useful when no mic is available)",
    )
    parser.add_argument(
        "--no-preview", action="store_true",
        help="run headless — skip cv2.imshow and keyboard handling",
    )
    parser.add_argument(
        "--api-base",
        help="backend REST URL (overrides API_BASE env). Required when "
             "running on a second laptop pointed at the host machine.",
    )
    parser.add_argument(
        "--socket-url",
        help="backend Socket.IO URL (overrides SOCKET_URL env, defaults "
             "to --api-base).",
    )
    parser.add_argument(
        "--api-key",
        help="Bearer token for authenticated routes (overrides API_KEY env). "
             "Optional — required only once stream routes are auth-gated.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # CLI flags take precedence over env vars; env vars fall back to defaults.
    api_base = args.api_base or os.environ.get("API_BASE", "http://localhost:5001")
    socket_url = args.socket_url or os.environ.get("SOCKET_URL", api_base)
    api_key = args.api_key or os.environ.get("API_KEY") or None

    log.info("Backend: %s", api_base)
    log.info("Camera:  index=%d (%dx%d)", args.camera, args.width, args.height)

    # ---- 1. Create the Stream + receive publisher credentials ----
    try:
        resp = create_stream(api_base, api_key, args.title)
    except Exception as e:
        log.error("Failed to create stream: %s", e)
        return 2
    stream_id = resp["stream"]["id"]
    publisher_token = resp["publisher_token"]
    livekit_url = resp["livekit_url"]
    log.info("Stream created: id=%s", stream_id)
    log.info("LiveKit URL: %s", livekit_url)

    # ---- 2. Fetch per-user gesture customization (best-effort) ----
    # builtin_actions: { built-in gesture name -> effective action }.
    # Empty {} means "use hardcoded defaults from detector.GESTURE_COMMANDS".
    # templates: list of /gestures/templates rows for the k-NN classifier.
    builtin_actions = fetch_builtins(api_base, api_key)
    templates = fetch_templates(api_base, api_key)
    if builtin_actions:
        log.info(
            "Loaded %d built-in overrides for this user", len(builtin_actions)
        )
    if templates:
        log.info("Loaded %d custom gesture template(s)", len(templates))
    classifier = CustomGestureClassifier(templates) if templates else None

    # ---- 3. Comment buffer, Socket.IO client, LiveKit publisher ----
    comments = CommentBuffer(capacity=8, ttl_seconds=10.0)
    client = GestureClient(socket_url, api_key, on_comment=comments.add)
    publisher = LiveKitPublisher(
        livekit_url,
        publisher_token,
        args.width,
        args.height,
        enable_audio=not args.no_audio,
    )

    # Connect Socket.IO in the background; join the room once connected.
    import threading
    threading.Thread(target=client.connect, daemon=True).start()
    # Give the connection a moment, then join the room.
    for _ in range(20):
        if client.connected:
            break
        time.sleep(0.1)
    client.join_room(stream_id)

    # Start LiveKit publisher (blocks briefly while connecting).
    try:
        publisher.start(connect_timeout_seconds=10.0)
    except Exception as e:
        log.error("Publisher failed to start: %s", e)
        # Try to clean up the half-created stream so it doesn't linger.
        end_stream(api_base, api_key, stream_id)
        client.disconnect()
        return 3
    log.info("LiveKit publisher ready; entering capture loop")

    # ---- 4. Run the capture/composite/publish loop ----
    api = ApiClient(api_base, api_key)
    loop = BroadcastLoop(
        stream_id=stream_id,
        publisher=publisher,
        client=client,
        comments=comments,
        camera_index=args.camera,
        width=args.width,
        height=args.height,
        show_preview=not args.no_preview,
        builtin_actions=builtin_actions,
        classifier=classifier,
        api_client=api,
    )
    result = loop.run()
    log.info(
        "Loop exited (%s); %d frames published",
        result.reason, result.frames_published,
    )

    # ---- 5. Cleanup ----
    publisher.stop()
    end_stream(api_base, api_key, stream_id)
    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
