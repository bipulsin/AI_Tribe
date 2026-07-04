"""Add garages and claim garage/surveyor/claimant fields for fraud graph.

Revision ID: 008_fraud_graph_garages
Revises: 007_pipeline_work_seconds
Create Date: 2026-07-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_fraud_graph_garages"
down_revision: Union[str, None] = "007_pipeline_work_seconds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "garages" not in tables:
        op.create_table(
            "garages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=128), nullable=False),
        )
        op.create_index("ix_garages_name", "garages", ["name"], unique=True)

    columns = {col["name"] for col in inspector.get_columns("claims")}
    if "garage_id" not in columns:
        op.add_column("claims", sa.Column("garage_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_claims_garage_id_garages",
            "claims",
            "garages",
            ["garage_id"],
            ["id"],
        )
        op.create_index("ix_claims_garage_id", "claims", ["garage_id"])
    if "claimant_name" not in columns:
        op.add_column("claims", sa.Column("claimant_name", sa.String(length=128), nullable=True))
    if "surveyor_name" not in columns:
        op.add_column("claims", sa.Column("surveyor_name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "surveyor_name")
    op.drop_column("claims", "claimant_name")
    op.drop_index("ix_claims_garage_id", table_name="claims")
    op.drop_constraint("fk_claims_garage_id_garages", "claims", type_="foreignkey")
    op.drop_column("claims", "garage_id")
    op.drop_index("ix_garages_name", table_name="garages")
    op.drop_table("garages")
