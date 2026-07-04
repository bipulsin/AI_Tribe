"""Add vehicles.pricing_basis for needs_confirmation tier.

Revision ID: 005_vehicle_pricing_basis
Revises: 004_model_runs
Create Date: 2026-07-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_vehicle_pricing_basis"
down_revision: Union[str, None] = "004_model_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column(
            "pricing_basis",
            sa.String(length=32),
            nullable=False,
            server_default="provisional_fallback",
        ),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "pricing_basis")
