"""Initial schema for AI Tribe motor damage assessment.

Revision ID: 001_initial
Revises:
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "parts_catalog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("make", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("part_name", sa.String(length=128), nullable=False),
        sa.Column("part_number", sa.String(length=64), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_parts_catalog_make", "parts_catalog", ["make"])
    op.create_index("ix_parts_catalog_model", "parts_catalog", ["model"])
    op.create_index("ix_parts_catalog_part_name", "parts_catalog", ["part_name"])

    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_reference", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_claims_claim_reference", "claims", ["claim_reference"], unique=True)

    op.create_table(
        "claim_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("image_order", sa.Integer(), nullable=False),
        sa.Column("is_video", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("quality_gate_passed", sa.Boolean(), nullable=True),
        sa.Column("authenticity_verdict", sa.String(length=16), nullable=True),
        sa.Column("authenticity_reason", sa.Text(), nullable=True),
        sa.Column("phash", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_claim_images_claim_id", "claim_images", ["claim_id"])
    op.create_index("ix_claim_images_phash", "claim_images", ["phash"])

    op.create_table(
        "pipeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("stage_key", sa.String(length=64), nullable=False),
        sa.Column("stage_label", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_pipeline_events_claim_id", "pipeline_events", ["claim_id"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("make", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("variant", sa.String(length=64), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("vin", sa.String(length=32), nullable=True),
        sa.Column("plate_number", sa.String(length=32), nullable=True),
        sa.Column(
            "source_claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False
        ),
    )
    op.create_index("ix_vehicles_source_claim_id", "vehicles", ["source_claim_id"])

    op.create_table(
        "damage_detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column(
            "claim_image_id", sa.Integer(), sa.ForeignKey("claim_images.id"), nullable=False
        ),
        sa.Column("part_name", sa.String(length=128), nullable=False),
        sa.Column("damage_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("repair_or_replace", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
    )
    op.create_index("ix_damage_detections_claim_id", "damage_detections", ["claim_id"])
    op.create_index(
        "ix_damage_detections_claim_image_id", "damage_detections", ["claim_image_id"]
    )

    op.create_table(
        "fraud_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_fraud_signals_claim_id", "fraud_signals", ["claim_id"])

    op.create_table(
        "estimates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("line_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tax", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("grand_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reason_summary", sa.Text(), nullable=False),
    )
    op.create_index("ix_estimates_claim_id", "estimates", ["claim_id"], unique=True)


def downgrade() -> None:
    op.drop_table("estimates")
    op.drop_table("fraud_signals")
    op.drop_table("damage_detections")
    op.drop_table("vehicles")
    op.drop_table("pipeline_events")
    op.drop_table("claim_images")
    op.drop_table("claims")
    op.drop_table("parts_catalog")
    op.drop_table("users")
