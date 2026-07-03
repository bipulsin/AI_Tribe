"""Add vehicle identity_confirmed and estimate pricing_basis.

Revision ID: 003_pricing_basis
Revises: 002_labor_hours
Create Date: 2026-07-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_pricing_basis"
down_revision: Union[str, None] = "002_labor_hours"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column(
            "identity_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "estimates",
        sa.Column(
            "pricing_basis",
            sa.String(length=32),
            nullable=False,
            server_default="provisional_fallback",
        ),
    )


def downgrade() -> None:
    op.drop_column("estimates", "pricing_basis")
    op.drop_column("vehicles", "identity_confirmed")
