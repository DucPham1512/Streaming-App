"""Webhook event audit log — also enforces idempotency.

Webhook providers (LiveKit today; previously Mux) retry failed deliveries,
so we may receive duplicates. The unique constraint on external_event_id
makes processing the same event twice a no-op.
"""

from datetime import datetime, timezone
from app.extensions import db


class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Event ID from the upstream provider (LiveKit). Unique constraint = automatic dedup.
    external_event_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    event_type = db.Column(db.String(64), nullable=False)
    # Store the raw payload as text (SQLite has no native JSON type)
    payload = db.Column(db.Text, nullable=False)
    received_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    processed_at = db.Column(db.DateTime, nullable=True)