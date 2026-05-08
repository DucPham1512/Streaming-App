"""
Wrapper around the Mux Python SDK for live stream operations.

All Mux API interactions go through this module. Route handlers should NOT
import mux_python directly — that keeps the API surface mockable in tests
and makes it easy to swap providers later if needed.
"""
import os
import hmac
import hashlib
import time
from dataclasses import dataclass
from typing import Optional

import mux_python
from mux_python.rest import ApiException


# ---- Module-level SDK config (initialized lazily) ----

_live_api: Optional[mux_python.LiveStreamsApi] = None


def _get_live_api() -> mux_python.LiveStreamsApi:
    """Lazy initialization so tests can patch env vars before first call."""
    global _live_api
    if _live_api is None:
        config = mux_python.Configuration()
        config.username = os.environ['MUX_TOKEN_ID']
        config.password = os.environ['MUX_TOKEN_SECRET']
        _live_api = mux_python.LiveStreamsApi(mux_python.ApiClient(config))
    return _live_api


# ---- Domain DTOs (decoupled from SDK types so route layer doesn't import mux_python) ----

@dataclass
class CreatedStream:
    """Result of creating a new live stream on Mux."""
    mux_stream_id: str
    stream_key: str       # SECRET — only return to the owning user, never list
    playback_id: str
    playback_url: str     # convenience: HLS URL constructed from playback_id

    @property
    def rtmp_url(self) -> str:
        return "rtmp://global-live.mux.com:5222/app"
    
    def __repr__(self) -> str:
        # Prevent accidental logging of the stream key
        return (
            f"CreatedStream(mux_stream_id={self.mux_stream_id!r}, "
            f"stream_key='***REDACTED***', "
            f"playback_id={self.playback_id!r})"
        )


# ---- Public operations ----

class MuxServiceError(Exception):
    """Raised when a Mux API call fails. Wraps the underlying ApiException."""

    def __init__(self, message: str, status: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


def create_live_stream(latency_mode: str = 'standard') -> CreatedStream:
    """
    Create a new live stream on Mux.

    :param latency_mode: 'standard' (cheapest), 'reduced', or 'low'.
                         For an assignment, always use 'standard'.
    :raises MuxServiceError: if the Mux API call fails
    """
    request = mux_python.CreateLiveStreamRequest(
        playback_policy=[mux_python.PlaybackPolicy.PUBLIC],
        new_asset_settings=mux_python.CreateAssetRequest(
            playback_policy=[mux_python.PlaybackPolicy.PUBLIC]
        ),
        latency_mode=latency_mode,
    )

    try:
        response = _get_live_api().create_live_stream(request)
    except ApiException as e:
        raise MuxServiceError(
            f"Failed to create Mux live stream: {e.reason}",
            status=e.status,
            body=e.body,
        ) from e

    stream = response.data
    playback_id = stream.playback_ids[0].id
    return CreatedStream(
        mux_stream_id=stream.id,
        stream_key=stream.stream_key,
        playback_id=playback_id,
        playback_url=f"https://stream.mux.com/{playback_id}.m3u8",
    )


def end_live_stream(mux_stream_id: str) -> None:
    """
    Signal Mux to end a currently-broadcasting stream.

    Idempotent: safe to call on already-ended streams (Mux returns 200).
    """
    try:
        _get_live_api().signal_live_stream_complete(mux_stream_id)
    except ApiException as e:
        # 404 means the stream is already gone — treat as success
        if e.status == 404:
            return
        raise MuxServiceError(
            f"Failed to end Mux live stream {mux_stream_id}: {e.reason}",
            status=e.status,
            body=e.body,
        ) from e


def delete_live_stream(mux_stream_id: str) -> None:
    """
    Permanently delete a stream from Mux. Use sparingly — mostly for test cleanup.
    """
    try:
        _get_live_api().delete_live_stream(mux_stream_id)
    except ApiException as e:
        if e.status == 404:
            return
        raise MuxServiceError(
            f"Failed to delete Mux live stream {mux_stream_id}: {e.reason}",
            status=e.status,
            body=e.body,
        ) from e


# ---- Webhook signature verification ----

class WebhookVerificationError(Exception):
    """Raised when a webhook payload's signature is invalid or expired."""


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> None:
    """
    Verify the Mux-Signature header on an incoming webhook.

    Mux signs each webhook with HMAC-SHA256. The header looks like:
        t=1234567890,v1=abc123def456...

    :param raw_body: The exact raw bytes of the request body (NOT json.loads'd)
    :param signature_header: Value of the 'Mux-Signature' header
    :param secret: The webhook signing secret (from Mux dashboard → Webhooks)
    :param tolerance_seconds: Reject signatures older than this (replay protection)
    :raises WebhookVerificationError: if signature is missing, malformed, or invalid
    """
    if not signature_header:
        raise WebhookVerificationError("Missing Mux-Signature header")

    # Parse "t=...,v1=..."
    parts = dict(part.split('=', 1) for part in signature_header.split(','))
    timestamp = parts.get('t')
    expected_sig = parts.get('v1')

    if not timestamp or not expected_sig:
        raise WebhookVerificationError("Malformed Mux-Signature header")

    # Replay protection: reject old signatures
    try:
        ts_int = int(timestamp)
    except ValueError:
        raise WebhookVerificationError("Invalid timestamp in signature")

    if abs(time.time() - ts_int) > tolerance_seconds:
        raise WebhookVerificationError("Signature timestamp outside tolerance window")

    # Compute expected signature: HMAC-SHA256(secret, "{timestamp}.{body}")
    signed_payload = f"{timestamp}.".encode() + raw_body
    computed_sig = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(computed_sig, expected_sig):
        raise WebhookVerificationError("Signature mismatch")