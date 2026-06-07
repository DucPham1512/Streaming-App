"""merge heads

Revision ID: 70cfe6767f5d
Revises: c2f3d4e5a6b7, a1b2c3d4e5f6
Create Date: 2026-06-07 23:22:08.633111

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '70cfe6767f5d'
down_revision: Union[str, None] = ('c2f3d4e5a6b7', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
