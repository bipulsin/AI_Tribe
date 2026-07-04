"""Add pipeline_events.work_seconds for unpadded stage duration.

Revision ID: 007_pipeline_work_seconds
Revises: 006_estimate_fallback_source
Create Date: 2026-07-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_pipeline_work_seconds"
down_revision: Union[str, None] = "006_estimate_fallback_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("pipeline_events")}
    if "work_seconds" not in columns:
        op.add_column(
            "pipeline_events",
            sa.Column("work_seconds", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("pipeline_events")}
    if "work_seconds" in columns:
        op.drop_column("pipeline_events", "work_seconds")
