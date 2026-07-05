"""VMMR manual correction queue and vehicle identity_source.

Revision ID: 009_vmmr_correction_queue
Revises: 008_fraud_graph_garages
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_vmmr_correction_queue"
down_revision: Union[str, None] = "008_fraud_graph_garages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column(
            "identity_source",
            sa.String(length=32),
            nullable=False,
            server_default="vmmr",
        ),
    )
    op.create_table(
        "vmmr_correction_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("image_paths", sa.JSON(), nullable=False),
        sa.Column("scratch_image_paths", sa.JSON(), nullable=True),
        sa.Column("confirmed_make", sa.String(length=64), nullable=False),
        sa.Column("confirmed_model", sa.String(length=64), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "used_in_training",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_vmmr_correction_queue_claim_id",
        "vmmr_correction_queue",
        ["claim_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_vmmr_correction_queue_claim_id", table_name="vmmr_correction_queue")
    op.drop_table("vmmr_correction_queue")
    op.drop_column("vehicles", "identity_source")
