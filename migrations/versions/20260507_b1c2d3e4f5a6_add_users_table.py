"""add_users_table

Story A5 — introduces the User model as an app-wide foundation.

Note: ``avatar_media_id`` is created as a plain String column without a
foreign-key constraint here. Story B's migration adds the FK pointing at
``media_items.id`` once that table exists. SQLAlchemy ORM still declares
the FK; only DB-level enforcement is deferred.

Revision ID: b1c2d3e4f5a6
Revises: a9006969e999
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9006969e999"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("avatar_media_id", sa.String(length=36), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("api_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("api_key", name="uq_users_api_key"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_api_key", "users", ["api_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_api_key", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
