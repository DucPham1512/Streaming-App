"""add_missing_streams_columns

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("streams", sa.Column("mux_stream_id", sa.String(length=64), nullable=True))
    op.add_column("streams", sa.Column("mux_playback_id", sa.String(length=64), nullable=True))
    op.add_column("streams", sa.Column("mux_stream_key", sa.String(length=128), nullable=True))
    op.add_column("streams", sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("streams", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.create_index("ix_streams_mux_stream_id", "streams", ["mux_stream_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_streams_mux_stream_id", table_name="streams")
    op.drop_column("streams", "started_at")
    op.drop_column("streams", "like_count")
    op.drop_column("streams", "mux_stream_key")
    op.drop_column("streams", "mux_playback_id")
    op.drop_column("streams", "mux_stream_id")
