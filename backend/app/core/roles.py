"""Application user roles.

Stored as a single string on users.role. One role per user at a time.
"""

from __future__ import annotations

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_SUPERVISOR = "supervisor"

VALID_ROLES = frozenset({ROLE_USER, ROLE_ADMIN, ROLE_SUPERVISOR})

ROLE_LABELS = {
    ROLE_USER: "User",
    ROLE_ADMIN: "Admin",
    ROLE_SUPERVISOR: "Supervisor",
}


def normalize_role(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in VALID_ROLES:
        return raw
    # Accept display labels from the admin UI.
    for key, label in ROLE_LABELS.items():
        if raw == label.lower():
            return key
    raise ValueError("Role must be User, Admin, or Supervisor")


def is_admin(role: str | None) -> bool:
    return (role or "").strip().lower() == ROLE_ADMIN


def can_view_all_claims(role: str | None) -> bool:
    """Admin and Supervisor can view every claim; User only own claims."""
    return (role or "").strip().lower() in {ROLE_ADMIN, ROLE_SUPERVISOR}


def role_label(role: str | None) -> str:
    key = (role or ROLE_USER).strip().lower()
    return ROLE_LABELS.get(key, ROLE_LABELS[ROLE_USER])
