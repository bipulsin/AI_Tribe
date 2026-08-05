"""Per-user API connector settings (Salesforce WIP).

Revision ID: 020_api_connector_settings
Revises: 019_usage_events
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_api_connector_settings"
down_revision: Union[str, None] = "019_usage_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_connector_settings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("api_name", sa.String(length=64), nullable=False),
        sa.Column("server_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("connector_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "api_name", name="uq_api_connector_settings_user_api"),
    )
    op.create_index(
        "ix_api_connector_settings_user_id",
        "api_connector_settings",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_connector_settings_user_id", table_name="api_connector_settings")
    op.drop_table("api_connector_settings")
