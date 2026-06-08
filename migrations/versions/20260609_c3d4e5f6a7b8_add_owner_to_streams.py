"""add_owner_to_streams

Revision ID: c3d4e5f6a7b8
Revises: 70cfe6767f5d
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "70cfe6767f5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("streams", sa.Column("owner_identity", sa.String(255), nullable=True))
    op.add_column("streams", sa.Column("owner_display_name", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("streams", "owner_display_name")
    op.drop_column("streams", "owner_identity")
