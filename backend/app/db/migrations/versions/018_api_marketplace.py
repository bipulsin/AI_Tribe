"""API Marketplace Alembic migration — tokens, subscriptions, chains, audit log.

Revision ID: 018_api_marketplace
Revises: 017_user_roles_supervisor
Create Date: 2026-07-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018_api_marketplace"
down_revision: Union[str, None] = "017_user_roles_supervisor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("token_prefix", sa.String(length=32), nullable=False),
        sa.Column("token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "reminder_sent_7d", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "reminder_sent_1d", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
        sa.CheckConstraint(
            "validity_days IN (30, 60, 90, 120, 180, 360)",
            name="ck_api_tokens_validity_days",
        ),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index(
        "idx_api_tokens_user_current",
        "api_tokens",
        ["user_id"],
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "api_token_reveal_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_prefix", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_api_token_reveal_log_user_id", "api_token_reveal_log", ["user_id"])

    op.create_table(
        "api_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("api_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "api_name", name="uq_api_subscriptions_user_api"),
    )
    op.create_index("ix_api_subscriptions_user_id", "api_subscriptions", ["user_id"])

    op.create_table(
        "api_chains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chain_name", sa.String(length=128), nullable=False),
        sa.Column(
            "head_api",
            sa.String(length=64),
            nullable=False,
            server_default="submit_claim",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_api_chains_user_id", "api_chains", ["user_id"])

    op.create_table(
        "api_chain_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chain_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_chains.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("api_name", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("chain_id", "step_order", name="uq_api_chain_steps_order"),
    )

    op.create_table(
        "api_request_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("token_prefix", sa.String(length=32), nullable=True),
        sa.Column("api_name", sa.String(length=64), nullable=False),
        sa.Column("claim_no", sa.String(length=32), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_api_request_log_user_time",
        "api_request_log",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_api_request_log_user_time", table_name="api_request_log")
    op.drop_table("api_request_log")
    op.drop_table("api_chain_steps")
    op.drop_index("ix_api_chains_user_id", table_name="api_chains")
    op.drop_table("api_chains")
    op.drop_index("ix_api_subscriptions_user_id", table_name="api_subscriptions")
    op.drop_table("api_subscriptions")
    op.drop_index("ix_api_token_reveal_log_user_id", table_name="api_token_reveal_log")
    op.drop_table("api_token_reveal_log")
    op.drop_index("idx_api_tokens_user_current", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")
