"""Normalize user roles and introduce Supervisor (view-all) role.

Revision ID: 017_user_roles_supervisor
Revises: 016_chat_draft_state
Create Date: 2026-07-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_user_roles_supervisor"
down_revision: Union[str, None] = "016_chat_draft_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One role per user: only username "admin" keeps Admin; all others become User.
    # Supervisor is assigned later via admin UI / provisioning.
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET role = 'user'"))
    conn.execute(
        sa.text("UPDATE users SET role = 'admin' WHERE lower(username) = 'admin'")
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET role = 'user' WHERE lower(coalesce(role, '')) = 'supervisor'"
        )
    )
