"""add gesture_templates table

Revision ID: c2f3d4e5a6b7
Revises: b1e2c3d4f5a6
Create Date: 2026-05-17

Storage for user-recorded k-NN gesture templates (see
docs/decisions/004-knn-gesture-templates.md). The existing
gesture_mappings table (override of built-in gesture→action) is
untouched and continues to serve its role.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2f3d4e5a6b7"
down_revision: Union[str, None] = "b1e2c3d4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gesture_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False, server_default="unmapped"),
        sa.Column("handedness", sa.String(length=8), nullable=False, server_default="Any"),
        sa.Column("landmarks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_gesture_templates_user_id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_template_name"),
    )
    op.create_index(
        "ix_gesture_templates_user_id",
        "gesture_templates",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gesture_templates_user_id", table_name="gesture_templates")
    op.drop_table("gesture_templates")
