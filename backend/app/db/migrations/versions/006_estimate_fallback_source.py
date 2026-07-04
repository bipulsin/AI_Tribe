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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("estimates")}
    if "fallback_source_model" not in columns:
        op.add_column(
            "estimates",
            sa.Column("fallback_source_model", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("estimates")}
    if "fallback_source_model" in columns:
        op.drop_column("estimates", "fallback_source_model")
