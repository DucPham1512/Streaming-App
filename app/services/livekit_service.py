"""
Wrapper around the LiveKit Server SDK for live stream operations.

All LiveKit API interactions go through this module. Route handlers should NOT
import livekit.api directly — that keeps the API surface mockable in tests
and matches the pattern previously used by mux_service.

The Python SDK's room admin operations are async (aiohttp under the hood);
this module hides that behind sync wrappers since Flask route handlers are
sync. Token minting itself is synchronous (just JWT signing).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from livekit import api as lk_api


# ---- Module-level SDK config (lazy) ----

_room_client: Optional[lk_api.LiveKitAPI] = None


def _api_key() -> str:
    return os.environ["LIVEKIT_API_KEY"]


def _api_secret() -> str:
    return os.environ["LIVEKIT_API_SECRET"]


def _server_url() -> str:
    """URL the *backend* uses to reach LiveKit Server.

    Inside docker-compose this is the internal hostname (LIVEKIT_URL_INTERNAL).
    For host-mode dev, falls back to LIVEKIT_URL.
    """
    return os.environ.get("LIVEKIT_URL_INTERNAL") or os.environ["LIVEKIT_URL"]


def _public_url() -> str:
    """URL handed to *clients* (phones, browsers) — must be reachable from the LAN."""
    return os.environ["LIVEKIT_URL"]


def _get_room_client() -> lk_api.LiveKitAPI:
    """Lazy init so tests can patch env vars before first call."""
    global _room_client
    if _room_client is None:
        _room_client = lk_api.LiveKitAPI(_server_url(), _api_key(), _api_secret())
    return _room_client


def _run_sync(coro):
    """Run an async coroutine from sync code.

    Flask's dev server (Werkzeug) doesn't run inside an event loop, so we
    can use asyncio.run() per call. Creates a new loop each invocation
    (acceptable for low-frequency room-admin operations).
    """
    return asyncio.run(coro)


# ---- Domain DTOs (decoupled from SDK types) ----


@dataclass
class CreatedRoom:
    """Result of provisioning a LiveKit room for a Stream."""

    room_name: str         # equal to Stream.id (UUID) — LiveKit room namespace
    publisher_token: str   # JWT the broadcaster uses to publish; KEEP SECRET
    livekit_url: str       # WebSocket URL clients connect to

    def __repr__(self) -> str:
        # Prevent accidental logging of the publisher JWT
        return (
            f"CreatedRoom(room_name={self.room_name!r}, "
            f"publisher_token='***REDACTED***', "
            f"livekit_url={self.livekit_url!r})"
        )


# ---- Public operations ----


class LiveKitServiceError(Exception):
    """Raised when a LiveKit API call fails."""


def mint_access_token(
    room_name: str,
    identity: str,
    *,
    can_publish: bool,
    can_subscribe: bool = True,
    display_name: Optional[str] = None,
    ttl_seconds: int = 6 * 60 * 60,
) -> str:
    """Mint a JWT granting access to a specific LiveKit room.

    :param room_name: Room namespace (we use Stream.id).
    :param identity: Unique participant identifier; reusing one disconnects
                     the previous session with the same identity.
    :param can_publish: Publisher token (broadcaster) vs subscriber-only (viewer).
    :param can_subscribe: Normally True; set False to mint a publish-only token.
    :param display_name: Optional human-readable name shown to other participants.
    :param ttl_seconds: Token validity window. Default 6h covers a long demo.
    """
    grants = lk_api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=can_publish,
        can_subscribe=can_subscribe,
        can_publish_data=True,
    )

    token = (
        lk_api.AccessToken(_api_key(), _api_secret())
        .with_identity(identity)
        .with_ttl(timedelta(seconds=ttl_seconds))
        .with_grants(grants)
    )
    if display_name:
        token = token.with_name(display_name)

    return token.to_jwt()


def create_stream_room(
    stream_id: str,
    owner_identity: str,
    *,
    owner_display_name: Optional[str] = None,
    empty_timeout_seconds: int = 300,
) -> CreatedRoom:
    """Provision a room for a Stream and mint the broadcaster's publisher token.

    Room auto-creation is enabled in livekit.yaml, so this call is technically
    optional — but creating up front lets us set empty_timeout (how long the
    room sticks around with no participants) and surface errors early.

    :raises LiveKitServiceError: if the LiveKit API call fails (not 409/conflict).
    """
    try:
        _run_sync(
            _get_room_client().room.create_room(
                lk_api.CreateRoomRequest(
                    name=stream_id,
                    empty_timeout=empty_timeout_seconds,
                )
            )
        )
    except Exception as e:
        # LiveKit returns "already exists" if the room is recreated; treat as ok.
        # The SDK doesn't expose typed errors, so we string-match defensively.
        msg = str(e).lower()
        if "already exists" not in msg and "twirp error already_exists" not in msg:
            raise LiveKitServiceError(
                f"Failed to create LiveKit room for stream {stream_id}: {e}"
            ) from e

    publisher_token = mint_access_token(
        room_name=stream_id,
        identity=owner_identity,
        can_publish=True,
        display_name=owner_display_name,
    )

    return CreatedRoom(
        room_name=stream_id,
        publisher_token=publisher_token,
        livekit_url=_public_url(),
    )


def delete_stream_room(stream_id: str) -> None:
    """Disconnect all participants and delete the room.

    Idempotent: deleting a nonexistent room is treated as success.
    """
    try:
        _run_sync(
            _get_room_client().room.delete_room(
                lk_api.DeleteRoomRequest(room=stream_id)
            )
        )
    except Exception as e:
        msg = str(e).lower()
        if "not_found" in msg or "does not exist" in msg:
            return
        raise LiveKitServiceError(
            f"Failed to delete LiveKit room {stream_id}: {e}"
        ) from e


# ---- Webhook signature verification ----


class WebhookVerificationError(Exception):
    """Raised when an incoming LiveKit webhook fails signature verification."""


def verify_and_decode_webhook(raw_body: bytes, auth_header: str) -> dict[str, Any]:
    """Verify a LiveKit webhook and return the parsed event payload.

    LiveKit webhooks carry an `Authorization` header containing a JWT signed
    with the same api_key/api_secret. The JWT's `sha256` claim must match
    the SHA256 of the raw request body — that's the integrity check.

    :param raw_body: Exact raw bytes of the request body.
    :param auth_header: Value of the `Authorization` header on the incoming request.
    :raises WebhookVerificationError: if header missing, JWT invalid, or hash mismatch.
    :return: parsed WebhookEvent as a dict (see LiveKit docs for fields).
    """
    if not auth_header:
        raise WebhookVerificationError("Missing Authorization header on webhook")

    try:
        receiver = lk_api.WebhookReceiver(
            lk_api.TokenVerifier(_api_key(), _api_secret())
        )
        event = receiver.receive(raw_body.decode("utf-8"), auth_header)
    except Exception as e:
        raise WebhookVerificationError(
            f"LiveKit webhook verification failed: {e}"
        ) from e

    # WebhookEvent is a protobuf message; convert to a plain dict for the route layer.
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(event, preserving_proto_field_name=True)
