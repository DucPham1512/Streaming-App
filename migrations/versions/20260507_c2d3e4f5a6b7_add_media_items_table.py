"""add_media_items_table

Story B5 — creates the MediaItem table and (optionally) adds the FK from
``users.avatar_media_id`` to ``media_items.id``. The FK is created via
``op.create_foreign_key`` for backends that support it; SQLite ignores
ALTER TABLE ADD CONSTRAINT, in which case the FK is enforced only at the
ORM level. Either way the runtime contract is the same.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mimetype", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_bucket", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("thumbnail_key", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_media_items_owner_id_users"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_items_owner_id", "media_items", ["owner_id"], unique=False)
    op.create_index("ix_media_items_deleted_at", "media_items", ["deleted_at"], unique=False)
    op.create_index(
        "ix_media_items_owner_deleted_created",
        "media_items",
        ["owner_id", "deleted_at", "created_at"],
        unique=False,
    )

    # Backfill the FK from users.avatar_media_id -> media_items.id.
    # SQLite will skip this silently; Postgres will enforce it.
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_users_avatar_media_id_media_items",
            "users",
            "media_items",
            ["avatar_media_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "fk_users_avatar_media_id_media_items", "users", type_="foreignkey"
        )
    op.drop_index("ix_media_items_owner_deleted_created", table_name="media_items")
    op.drop_index("ix_media_items_deleted_at", table_name="media_items")
    op.drop_index("ix_media_items_owner_id", table_name="media_items")
    op.drop_table("media_items")
