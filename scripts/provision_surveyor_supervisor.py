#!/usr/bin/env python3
"""Provision surveyor@tradentical.com as Supervisor (view-all) role."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.roles import ROLE_SUPERVISOR
from app.core.security import hash_password, verify_password
from app.models import User

EMAIL = "surveyor@tradentical.com"
PASSWORD = "suRv@y0r"
FULL_NAME = "Surveyor"


def main() -> int:
    db = SessionLocal()
    try:
        user = db.scalar(
            select(User).where(
                (User.email == EMAIL) | (User.username == EMAIL)
            )
        )
        if user:
            user.username = EMAIL
            user.email = EMAIL
            user.full_name = user.full_name or FULL_NAME
            user.role = ROLE_SUPERVISOR
            user.is_active = True
            if not verify_password(PASSWORD, user.password_hash):
                user.password_hash = hash_password(PASSWORD)
            db.commit()
            print(f"Updated existing user id={user.id} role={user.role}")
        else:
            user = User(
                username=EMAIL,
                email=EMAIL,
                password_hash=hash_password(PASSWORD),
                full_name=FULL_NAME,
                role=ROLE_SUPERVISOR,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Created user id={user.id} role={user.role}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
