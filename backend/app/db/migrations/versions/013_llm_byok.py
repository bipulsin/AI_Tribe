"""BYOK LLM keys, preferences, assist logs, vehicle LLM suggestions.

Revision ID: 013_llm_byok
Revises: 012_user_profile_fields
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_llm_byok"
down_revision: Union[str, None] = "012_user_profile_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_llm_provider_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_hint", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_llm_provider"),
    )
    op.create_index("ix_user_llm_provider_keys_user_id", "user_llm_provider_keys", ["user_id"])

    op.create_table(
        "user_llm_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("active_provider", sa.String(length=32), nullable=True),
        sa.Column("toggle_deepfake", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("toggle_vmmr", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("toggle_estimation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("toggle_fraud", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "llm_assist_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("agreed_with_internal", sa.Boolean(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_assist_logs_claim_id", "llm_assist_logs", ["claim_id"])

    op.add_column("vehicles", sa.Column("llm_suggest_make", sa.String(length=64), nullable=True))
    op.add_column("vehicles", sa.Column("llm_suggest_model", sa.String(length=64), nullable=True))
    op.add_column("vehicles", sa.Column("llm_suggest_provider", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "llm_suggest_provider")
    op.drop_column("vehicles", "llm_suggest_model")
    op.drop_column("vehicles", "llm_suggest_make")
    op.drop_index("ix_llm_assist_logs_claim_id", table_name="llm_assist_logs")
    op.drop_table("llm_assist_logs")
    op.drop_table("user_llm_preferences")
    op.drop_index("ix_user_llm_provider_keys_user_id", table_name="user_llm_provider_keys")
    op.drop_table("user_llm_provider_keys")
