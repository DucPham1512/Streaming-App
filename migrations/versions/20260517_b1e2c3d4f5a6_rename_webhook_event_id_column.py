"""rename webhook_events.mux_event_id to external_event_id

Revision ID: b1e2c3d4f5a6
Revises: 9eec425259c4
Create Date: 2026-05-17

Now that webhook events come from LiveKit (and could come from anywhere
in the future), the column gets a provider-neutral name. The backing
unique constraint follows the column through the rename (its name —
uq_webhook_events_mux_event_id — is now stylistically stale but not
functionally wrong; renaming the constraint is left to a future cleanup
to keep this migration minimal and reversible on SQLite).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b1e2c3d4f5a6"
down_revision: Union[str, None] = "9eec425259c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.alter_column("mux_event_id", new_column_name="external_event_id")


def downgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.alter_column("external_event_id", new_column_name="mux_event_id")
