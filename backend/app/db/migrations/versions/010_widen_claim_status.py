"""Widen claims.status for paused_awaiting_vehicle_confirmation (35 chars).

Revision ID: 010_widen_claim_status
Revises: 009_vmmr_correction_queue
"""

from alembic import op

revision: str = "010_widen_claim_status"
down_revision: str | None = "009_vmmr_correction_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE claims ALTER COLUMN status TYPE VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE claims ALTER COLUMN status TYPE VARCHAR(32)")
