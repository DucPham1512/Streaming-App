"""drop_owner_id_from_streams

Revision ID: a2b3c4d5e6f7
Revises: e5f6a7b8c9d0e1f2
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "e5f6a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_streams_owner_id", table_name="streams")
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_constraint("fk_streams_owner_id", type_="foreignkey")
        batch_op.drop_column("owner_id")


def downgrade() -> None:
    import sqlalchemy as sa
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_streams_owner_id", "users", ["owner_id"], ["id"]
        )
    op.create_index("ix_streams_owner_id", "streams", ["owner_id"])
