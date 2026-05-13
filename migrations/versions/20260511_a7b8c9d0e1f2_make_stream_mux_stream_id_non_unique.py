"""make_stream_mux_stream_id_non_unique

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-11
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_streams_mux_stream_id")
    op.execute("CREATE INDEX ix_streams_mux_stream_id ON streams (mux_stream_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_streams_mux_stream_id")
    op.execute("CREATE UNIQUE INDEX ix_streams_mux_stream_id ON streams (mux_stream_id)")
