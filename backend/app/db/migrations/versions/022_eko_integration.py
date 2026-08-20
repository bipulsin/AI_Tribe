"""Add EKO integration columns on policy vehicles and KYC events.

Revision ID: 022_eko_integration
Revises: 021_policy_booking
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "022_eko_integration"
down_revision: Union[str, None] = "021_policy_booking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("policy_vehicles", sa.Column("client_ref_id", sa.String(length=20), nullable=True))
    op.add_column("policy_vehicles", sa.Column("rc_status", sa.String(length=64), nullable=True))
    op.add_column("policy_vehicles", sa.Column("insurance_validity", sa.String(length=64), nullable=True))
    op.add_column("policy_vehicles", sa.Column("blacklist_status", sa.String(length=32), nullable=True))
    op.add_column(
        "policy_vehicles",
        sa.Column("blacklist_acknowledged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("policy_kyc_events", sa.Column("client_ref_id", sa.String(length=20), nullable=True))
    op.add_column("policy_kyc_events", sa.Column("raw_response", postgresql.JSONB(), nullable=True))
    op.add_column("policy_kyc_events", sa.Column("name_match", sa.String(length=8), nullable=True))
    op.add_column("policy_kyc_events", sa.Column("dob_match", sa.String(length=8), nullable=True))
    op.add_column("policy_kyc_events", sa.Column("pan_status", sa.String(length=16), nullable=True))
    op.add_column("policy_kyc_events", sa.Column("aadhaar_seeding_status", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("policy_kyc_events", "aadhaar_seeding_status")
    op.drop_column("policy_kyc_events", "pan_status")
    op.drop_column("policy_kyc_events", "dob_match")
    op.drop_column("policy_kyc_events", "name_match")
    op.drop_column("policy_kyc_events", "raw_response")
    op.drop_column("policy_kyc_events", "client_ref_id")
    op.drop_column("policy_vehicles", "blacklist_acknowledged")
    op.drop_column("policy_vehicles", "blacklist_status")
    op.drop_column("policy_vehicles", "insurance_validity")
    op.drop_column("policy_vehicles", "rc_status")
    op.drop_column("policy_vehicles", "client_ref_id")
