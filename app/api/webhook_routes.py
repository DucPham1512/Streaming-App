"""Mux webhook handler — receives stream lifecycle events.

Mux POSTs to this endpoint for events like stream connected/active/disconnected/idle.
We use these to keep our DB status in sync with Mux's reality.

Idempotency: Mux retries failed webhooks, so we may receive duplicates.
The unique constraint on WebhookEvent.mux_event_id catches dupes for free.
"""

import os
import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.webhook_event import WebhookEvent
from app.services import mux_service
from app.services.stream_manager import stream_manager

log = logging.getLogger(__name__)

webhook_bp = Blueprint("webhooks", __name__, url_prefix="/api/v1/webhooks")


@webhook_bp.route("/mux", methods=["POST"])
def mux_webhook():
    """Receive a webhook from Mux."""

    raw_body = request.get_data()  # raw bytes — needed for signature verification
    signature = request.headers.get("Mux-Signature", "")

    # Verify signature (skip in dev if no secret configured)
    secret = os.environ.get("MUX_WEBHOOK_SECRET")
    if secret:
        try:
            mux_service.verify_webhook_signature(raw_body, signature, secret)
        except mux_service.WebhookVerificationError as e:
            log.warning(f"Webhook signature verification failed: {e}")
            return jsonify({"error": "Invalid signature"}), 401
    else:
        log.warning("MUX_WEBHOOK_SECRET not set — accepting webhook without verification")

    # Parse the payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    event_id = payload.get("id")
    event_type = payload.get("type", "")
    data = payload.get("data", {})

    if not event_id:
        return jsonify({"error": "Missing event id"}), 400

    # Idempotency check — record the event, fail fast on duplicates
    event_record = WebhookEvent(
        mux_event_id=event_id,
        event_type=event_type,
        payload=raw_body.decode("utf-8"),
    )
    db.session.add(event_record)
    try:
        db.session.commit()
    except IntegrityError:
        # Already processed — return 200 so Mux stops retrying
        db.session.rollback()
        log.info(f"Duplicate webhook event {event_id}, ignoring")
        return jsonify({"status": "duplicate, already processed"}), 200

    # Dispatch by event type. data.id is the Mux stream ID for live_stream events.
    mux_stream_id = data.get("id")

    if event_type == "video.live_stream.connected":
        stream_manager.mark_connected(mux_stream_id)
        log.info(f"Stream {mux_stream_id} marked connected")

    elif event_type in ("video.live_stream.active", "video.live_stream.recording"):
        stream_manager.mark_active(mux_stream_id)
        log.info(f"Stream {mux_stream_id} marked active (via {event_type})")

    elif event_type == "video.live_stream.disconnected":
        stream_manager.mark_disconnected(mux_stream_id)
        log.info(f"Stream {mux_stream_id} marked disconnected (transient)")

    elif event_type == "video.live_stream.idle":
        stream_manager.mark_idle(mux_stream_id)
        log.info(f"Stream {mux_stream_id} marked ended (idle)")

    else:
        log.debug(f"Unhandled event type: {event_type}")

    # Mark as processed
    event_record.processed_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({"status": "ok"}), 200