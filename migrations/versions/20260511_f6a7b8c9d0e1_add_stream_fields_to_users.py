"""add_stream_fields_to_users

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("stream_key", sa.String(length=128), nullable=True))
    op.create_index("ix_users_stream_key", "users", ["stream_key"], unique=True)
    op.add_column("users", sa.Column("mux_stream_id", sa.String(length=64), nullable=True))
    op.create_index("ix_users_mux_stream_id", "users", ["mux_stream_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_mux_stream_id", table_name="users")
    op.drop_column("users", "mux_stream_id")
    op.drop_index("ix_users_stream_key", table_name="users")
    op.drop_column("users", "stream_key")
