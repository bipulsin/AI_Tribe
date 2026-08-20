"""Add policy payment table and payment columns.

Revision ID: 023_policy_payments
Revises: 022_eko_integration
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_policy_payments"
down_revision: Union[str, None] = "022_eko_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("policy_booking_requests", sa.Column("payment_method", sa.String(length=20), nullable=True))
    op.create_table(
        "policy_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "booking_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("policy_booking_requests.id"),
            nullable=False,
        ),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("card_holder_name", sa.String(length=255), nullable=True),
        sa.Column("card_number_masked", sa.String(length=10), nullable=True),
        sa.Column("expiry_masked", sa.String(length=5), nullable=True),
        sa.Column("cvv_masked", sa.String(length=5), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="simulated"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_policy_payments_booking_request_id", "policy_payments", ["booking_request_id"])
    op.add_column(
        "policy_issued_policies",
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policy_payments.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("policy_issued_policies", "payment_id")
    op.drop_index("ix_policy_payments_booking_request_id", table_name="policy_payments")
    op.drop_table("policy_payments")
    op.drop_column("policy_booking_requests", "payment_method")
