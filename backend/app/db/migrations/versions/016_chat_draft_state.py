"""Add chat_draft_states for persisted conversational claim drafts.

Revision ID: 016_chat_draft_state
Revises: 015_claim_accident_date
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "016_chat_draft_state"
down_revision: Union[str, None] = "015_claim_accident_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_draft_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=False, server_default="submit_claim"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("garage_name", sa.String(length=128), nullable=True),
        sa.Column("accident_date", sa.String(length=32), nullable=True),
        sa.Column("surveyor_name", sa.String(length=128), nullable=True),
        sa.Column(
            "uploaded_files",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_chat_draft_states_user_id", "chat_draft_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_draft_states_user_id", table_name="chat_draft_states")
    op.drop_table("chat_draft_states")
