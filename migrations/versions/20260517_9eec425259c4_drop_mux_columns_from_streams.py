"""drop mux columns from streams

Revision ID: 9eec425259c4
Revises: a7b8c9d0e1f2
Create Date: 2026-05-17

Removes the three mux_* columns from streams now that all stream
provisioning goes through LiveKit. See docs/decisions/001-livekit-over-mux.md.

NOTE: alembic --autogenerate also flagged unrelated pre-existing drift
between the models and the live schema (chat_messages table missing,
users index/constraint uniqueness, avatar_media_id FK). Those are not
part of this migration; they are tracked separately in
PROBLEMS_AND_SOLUTIONS.md and should be addressed in their own commits.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "9eec425259c4"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite cannot drop columns with simple ALTER TABLE; alembic's batch_alter_table
    # rebuilds the table for us on SQLite while behaving as a normal DROP COLUMN on Postgres.
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_index("ix_streams_mux_stream_id")
        batch_op.drop_column("mux_stream_id")
        batch_op.drop_column("mux_playback_id")
        batch_op.drop_column("mux_stream_key")


def downgrade() -> None:
    import sqlalchemy as sa
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(sa.Column("mux_stream_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("mux_playback_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("mux_stream_key", sa.String(length=128), nullable=True))
        batch_op.create_index("ix_streams_mux_stream_id", ["mux_stream_id"], unique=True)
