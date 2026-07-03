"""Add labor_hours to parts_catalog.

Revision ID: 002_labor_hours
Revises: 001_initial
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_labor_hours"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "parts_catalog",
        sa.Column(
            "labor_hours",
            sa.Numeric(precision=6, scale=2),
            nullable=False,
            server_default="1.0",
        ),
    )


def downgrade() -> None:
    op.drop_column("parts_catalog", "labor_hours")
