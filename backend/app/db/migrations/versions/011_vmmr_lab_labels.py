"""VMMR lab labeling queue (VehiDE / future CarDD — not live claims).

Revision ID: 011_vmmr_lab_labels
Revises: 010_widen_claim_status
Create Date: 2026-07-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_vmmr_lab_labels"
down_revision: Union[str, None] = "010_widen_claim_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vmmr_lab_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_dataset", sa.String(length=32), nullable=False),
        sa.Column("image_path", sa.String(length=512), nullable=False),
        sa.Column("image_rel_path", sa.String(length=256), nullable=True),
        sa.Column("damage_hint", sa.String(length=64), nullable=True),
        sa.Column("suggested_make", sa.String(length=64), nullable=True),
        sa.Column("suggested_model", sa.String(length=64), nullable=True),
        sa.Column("suggested_confidence", sa.Float(), nullable=True),
        sa.Column("guess_source", sa.String(length=32), nullable=True),
        sa.Column("guess_detail", sa.Text(), nullable=True),
        sa.Column("suggested_alternatives", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_make", sa.String(length=64), nullable=True),
        sa.Column("confirmed_model", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("license_tag", sa.String(length=64), nullable=False),
        sa.Column("scratch_copy_path", sa.String(length=512), nullable=True),
        sa.Column("labeled_by", sa.Integer(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["labeled_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("image_path"),
    )
    op.create_index(
        "ix_vmmr_lab_labels_status",
        "vmmr_lab_labels",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_vmmr_lab_labels_status", table_name="vmmr_lab_labels")
    op.drop_table("vmmr_lab_labels")
