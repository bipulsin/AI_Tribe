"""Policy booking demo tables.

Revision ID: 021_policy_booking
Revises: 020_api_connector_settings
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "021_policy_booking"
down_revision: Union[str, None] = "020_api_connector_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "policy_booking_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_reference", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("current_step", sa.String(length=64), nullable=False, server_default="welcome"),
        sa.Column("previous_policy_declared", sa.Boolean(), nullable=True),
        sa.Column("kyc_mode_used", sa.String(length=64), nullable=True),
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
        sa.UniqueConstraint("booking_reference", name="uq_policy_booking_reference"),
        sa.UniqueConstraint("session_id", name="uq_policy_booking_session_id"),
    )
    op.create_index("ix_policy_booking_requests_session_id", "policy_booking_requests", ["session_id"])
    op.create_index("ix_policy_booking_requests_user_id", "policy_booking_requests", ["user_id"])
    op.create_index("ix_policy_booking_requests_status", "policy_booking_requests", ["status"])
    op.create_index("ix_policy_booking_requests_created_at", "policy_booking_requests", ["created_at"])

    op.create_table(
        "policy_customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column("id_type", sa.String(length=16), nullable=True),
        sa.Column("id_masked", sa.String(length=32), nullable=True),
        sa.Column("id_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("dob", sa.String(length=16), nullable=True),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("pincode", sa.String(length=8), nullable=True),
        sa.UniqueConstraint("booking_request_id", name="uq_policy_customers_booking"),
    )

    op.create_table(
        "policy_vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("registration_number", sa.String(length=16), nullable=False),
        sa.Column("make", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("fuel_type", sa.String(length=32), nullable=True),
        sa.Column("owner_name", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="demo_fallback"),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("booking_request_id", name="uq_policy_vehicles_booking"),
    )
    op.create_index("ix_policy_vehicles_registration_number", "policy_vehicles", ["registration_number"])

    op.create_table(
        "policy_conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=16), nullable=False, server_default="text"),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_policy_conversation_messages_booking_request_id",
        "policy_conversation_messages",
        ["booking_request_id"],
    )

    op.create_table(
        "policy_kyc_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("id_type", sa.String(length=16), nullable=False),
        sa.Column("id_number_masked", sa.String(length=32), nullable=False),
        sa.Column("validation_mode", sa.String(length=64), nullable=False),
        sa.Column("validation_result", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("demo_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_policy_kyc_events_booking_request_id", "policy_kyc_events", ["booking_request_id"])

    op.create_table(
        "policy_quote_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("insurer_code", sa.String(length=8), nullable=False),
        sa.Column("insurer_name", sa.String(length=64), nullable=False),
        sa.Column("premium", sa.Float(), nullable=False),
        sa.Column("package_type", sa.String(length=32), nullable=False),
        sa.Column("coverage_summary", sa.Text(), nullable=False),
        sa.Column(
            "validity_note",
            sa.String(length=128),
            nullable=False,
            server_default="Illustrative only · 7-day demo validity",
        ),
        sa.Column("source_mode", sa.String(length=32), nullable=False, server_default="demo_rules"),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_policy_quote_options_booking_request_id", "policy_quote_options", ["booking_request_id"])

    op.create_table(
        "policy_issued_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("policy_reference", sa.String(length=40), nullable=False),
        sa.Column("document_path", sa.String(length=512), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False, server_default="demo_issuance"),
        sa.Column("insurer_name", sa.String(length=64), nullable=False),
        sa.Column("package_type", sa.String(length=32), nullable=False),
        sa.Column("premium", sa.Float(), nullable=False),
        sa.UniqueConstraint("booking_request_id", name="uq_policy_issued_booking"),
        sa.UniqueConstraint("policy_reference", name="uq_policy_issued_reference"),
    )

    op.create_table(
        "policy_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", name="uq_policy_settings_user"),
    )


def downgrade() -> None:
    op.drop_table("policy_settings")
    op.drop_table("policy_issued_policies")
    op.drop_index("ix_policy_quote_options_booking_request_id", table_name="policy_quote_options")
    op.drop_table("policy_quote_options")
    op.drop_index("ix_policy_kyc_events_booking_request_id", table_name="policy_kyc_events")
    op.drop_table("policy_kyc_events")
    op.drop_index("ix_policy_conversation_messages_booking_request_id", table_name="policy_conversation_messages")
    op.drop_table("policy_conversation_messages")
    op.drop_index("ix_policy_vehicles_registration_number", table_name="policy_vehicles")
    op.drop_table("policy_vehicles")
    op.drop_table("policy_customers")
    op.drop_index("ix_policy_booking_requests_created_at", table_name="policy_booking_requests")
    op.drop_index("ix_policy_booking_requests_status", table_name="policy_booking_requests")
    op.drop_index("ix_policy_booking_requests_user_id", table_name="policy_booking_requests")
    op.drop_index("ix_policy_booking_requests_session_id", table_name="policy_booking_requests")
    op.drop_table("policy_booking_requests")
