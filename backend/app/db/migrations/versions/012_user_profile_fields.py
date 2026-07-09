"""Add date_of_birth to users for profile panel.

Revision ID: 012_user_profile_fields
Revises: 011_vmmr_lab_labels
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_user_profile_fields"
down_revision: Union[str, None] = "011_vmmr_lab_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "date_of_birth")
