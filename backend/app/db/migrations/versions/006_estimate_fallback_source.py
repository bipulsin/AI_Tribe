"""Add estimates.fallback_source_model for same-make catalog fallback.

Revision ID: 006_estimate_fallback_source
Revises: 005_vehicle_pricing_basis
Create Date: 2026-07-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_estimate_fallback_source"
down_revision: Union[str, None] = "005_vehicle_pricing_basis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "estimates",
        sa.Column("fallback_source_model", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("estimates", "fallback_source_model")
