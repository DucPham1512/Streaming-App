"""add_social_tables

Member 4 — Social Interaction: adds comments, follows, and emotes tables.

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stream_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], name="fk_comments_stream_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_comments_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_stream_id", "comments", ["stream_id"])
    op.create_index("ix_comments_user_id", "comments", ["user_id"])
    op.create_index("ix_comments_created_at", "comments", ["created_at"])

    op.create_table(
        "follows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("follower_id", sa.String(length=36), nullable=False),
        sa.Column("followed_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], name="fk_follows_follower_id"),
        sa.ForeignKeyConstraint(["followed_id"], ["users.id"], name="fk_follows_followed_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("follower_id", "followed_id", name="uq_follows_pair"),
    )
    op.create_index("ix_follows_follower_id", "follows", ["follower_id"])
    op.create_index("ix_follows_followed_id", "follows", ["followed_id"])

    op.create_table(
        "emotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stream_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("emote_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], name="fk_emotes_stream_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_emotes_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emotes_stream_id", "emotes", ["stream_id"])
    op.create_index("ix_emotes_user_id", "emotes", ["user_id"])
    op.create_index("ix_emotes_created_at", "emotes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_emotes_created_at", table_name="emotes")
    op.drop_index("ix_emotes_user_id", table_name="emotes")
    op.drop_index("ix_emotes_stream_id", table_name="emotes")
    op.drop_table("emotes")

    op.drop_index("ix_follows_followed_id", table_name="follows")
    op.drop_index("ix_follows_follower_id", table_name="follows")
    op.drop_table("follows")

    op.drop_index("ix_comments_created_at", table_name="comments")
    op.drop_index("ix_comments_user_id", table_name="comments")
    op.drop_index("ix_comments_stream_id", table_name="comments")
    op.drop_table("comments")
