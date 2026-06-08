"""add_owner_id_to_streams

Revision ID: e5f6a7b8c9d0e1f2
Revises: c3d4e5f6a7b8
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0e1f2"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "streams",
        sa.Column(
            "owner_id",
            sa.String(36),
            sa.ForeignKey("users.id", name="fk_streams_owner_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_streams_owner_id", "streams", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_streams_owner_id", table_name="streams")
    op.drop_column("streams", "owner_id")
