"""LiveKit webhook handler — receives room lifecycle events.

LiveKit POSTs to this endpoint for events like participant_joined,
track_published, track_unpublished, room_started, room_finished. We use
`track_published` / `track_unpublished` / `room_finished` to keep our DB
status in sync with what LiveKit observes.

Why track_published instead of participant_joined: only publishers
publish tracks; viewers subscribe. That makes track_published(video)
the cleanest "broadcaster is now live" signal — no need to encode the
publisher role in identity strings.

Idempotency: LiveKit retries failed webhooks, so we may receive
duplicates. The unique constraint on WebhookEvent.mux_event_id catches
dupes for free (the column is renamed external_event_id in Commit 5).
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.webhook_event import WebhookEvent
from app.services import livekit_service
from app.services.stream_manager import stream_manager

log = logging.getLogger(__name__)

webhook_bp = Blueprint("webhooks", __name__, url_prefix="/api/v1/webhooks")


@webhook_bp.route("/livekit", methods=["POST"])
def livekit_webhook():
    """Receive a webhook from LiveKit Server."""

    raw_body = request.get_data()  # raw bytes — needed for signature verification
    auth_header = request.headers.get("Authorization", "")

    try:
        event = livekit_service.verify_and_decode_webhook(raw_body, auth_header)
    except livekit_service.WebhookVerificationError as e:
        log.warning("LiveKit webhook signature verification failed: %s", e)
        return jsonify({"error": "Invalid signature"}), 401

    event_id = event.get("id")
    event_type = event.get("event", "")

    if not event_id:
        return jsonify({"error": "Missing event id"}), 400

    # Idempotency check — record the event, fail fast on duplicates.
    event_record = WebhookEvent(
        mux_event_id=event_id,  # column renamed external_event_id in Commit 5
        event_type=event_type,
        payload=raw_body.decode("utf-8"),
    )
    db.session.add(event_record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        log.info("Duplicate webhook event %s, ignoring", event_id)
        return jsonify({"status": "duplicate, already processed"}), 200

    # room.name is the LiveKit room ID, which equals Stream.id (UUID).
    room = event.get("room") or {}
    stream_id = room.get("name")
    track = event.get("track") or {}

    if event_type == "track_published" and track.get("type") == "VIDEO":
        # Broadcaster has started publishing video → stream is watchable.
        if stream_id:
            stream_manager.mark_active(stream_id)
            log.info("Stream %s marked active (video track published)", stream_id)

    elif event_type == "track_unpublished" and track.get("type") == "VIDEO":
        # Broadcaster's video track went away → likely a transient drop.
        if stream_id:
            stream_manager.mark_disconnected(stream_id)
            log.info("Stream %s marked disconnected (video unpublished)", stream_id)

    elif event_type == "room_finished":
        if stream_id:
            stream_manager.mark_ended(stream_id)
            log.info("Stream %s marked ended (room finished)", stream_id)

    else:
        log.debug("Unhandled LiveKit event type: %s", event_type)

    # Mark as processed.
    event_record.processed_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({"status": "ok"}), 200
