"""Add accident_date to claims.

Revision ID: 015_claim_accident_date
Revises: 014_user_email_admin
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_claim_accident_date"
down_revision: Union[str, None] = "014_user_email_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("accident_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "accident_date")
