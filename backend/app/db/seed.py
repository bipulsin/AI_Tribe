"""Seed default admin user and parts catalog.

Local development (no ADMIN_PASSWORD): creates admin/admin when the users
table is empty.

Production / paperclip-vm (APP_ENV=production): ADMIN_PASSWORD is required.
On boot, if the admin user still has the seeded default password, it is
rotated to ADMIN_PASSWORD.
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import REPO_ROOT
from app.core.database import SessionLocal
from app.core.security import hash_password, verify_password
from app.db.seed_fraud_demo import seed_fraud_demo
from app.models import PartsCatalog, User

logger = logging.getLogger("ai_tribe.seed")

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"
PARTS_SEED_CSV = REPO_ROOT / "data" / "parts_seed" / "india_parts_seed.csv"


def _resolve_admin_password() -> str:
    explicit = os.environ.get("ADMIN_PASSWORD", "").strip()
    app_env = os.environ.get("APP_ENV", "development").strip().lower()

    if app_env == "production":
        if not explicit:
            raise RuntimeError(
                "ADMIN_PASSWORD must be set when APP_ENV=production "
                "(paperclip-vm / internet-facing deploy)."
            )
        return explicit

    return explicit or DEFAULT_ADMIN_PASSWORD


def seed_admin(db) -> None:
    password = _resolve_admin_password()
    explicit = bool(os.environ.get("ADMIN_PASSWORD", "").strip())

    admin = db.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))

    if admin is None:
        count = db.scalar(select(func.count()).select_from(User))
        if count and count > 0:
            logger.info("Users table has %s row(s) but no admin; skipping.", count)
            return

        admin = User(
            username=DEFAULT_ADMIN_USERNAME,
            password_hash=hash_password(password),
            full_name="Bipul Sahay",
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        if explicit:
            print(
                "\n"
                "!" * 72 + "\n"
                "  SEEDED admin user with ADMIN_PASSWORD from environment.\n"
                + "!" * 72
                + "\n"
            )
        else:
            print(
                "\n"
                "!" * 72 + "\n"
                "  SEEDED default user: admin / admin\n"
                "  Change this credential before anything resembling production use.\n"
                + "!" * 72
                + "\n"
            )
        return

    # Keep the display name current for the live demo account.
    if admin.full_name != "Bipul Sahay":
        admin.full_name = "Bipul Sahay"
        db.commit()
        logger.info("Updated admin full_name to Bipul Sahay.")

    # Rotate away from the lab default when ADMIN_PASSWORD is provided.
    if explicit and verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash):
        admin.password_hash = hash_password(password)
        db.commit()
        print(
            "\n"
            "!" * 72 + "\n"
            "  ROTATED admin password from seeded default using ADMIN_PASSWORD.\n"
            + "!" * 72
            + "\n"
        )
        logger.info("Rotated admin password from default using ADMIN_PASSWORD.")
    elif explicit:
        logger.info("Admin user present; password already non-default — left unchanged.")
    else:
        logger.info("Admin user already present; skipping seed.")


def seed_parts_catalog(db) -> None:
    count = db.scalar(select(func.count()).select_from(PartsCatalog))
    if count and count > 0:
        logger.info("Parts catalog already has %s row(s); skipping.", count)
        return

    if not PARTS_SEED_CSV.exists():
        logger.warning("Parts seed CSV not found at %s; skipping catalog seed.", PARTS_SEED_CSV)
        return

    rows: list[PartsCatalog] = []
    with PARTS_SEED_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            price_raw = row.get("price") or row.get("price_inr") or "0"
            labor_raw = row.get("labor_hours") or "1.0"
            rows.append(
                PartsCatalog(
                    make=row["make"].strip(),
                    model=row["model"].strip(),
                    part_name=row["part_name"].strip(),
                    part_number=(row.get("part_number") or "").strip() or None,
                    price=float(price_raw),
                    labor_hours=float(labor_raw),
                    currency=(row.get("currency") or "INR").strip(),
                    region=(row.get("region") or "IN").strip(),
                    source=(
                        (row.get("source") or "seed_india_v1").strip()
                        + (
                            f"; sourced_at={row['sourced_at'].strip()}"
                            if (row.get("sourced_at") or "").strip()
                            else ""
                        )
                    ),
                )
            )

    db.add_all(rows)
    db.commit()
    logger.info("Seeded %s parts catalog rows.", len(rows))


def run_seed() -> None:
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_parts_catalog(db)
        seed_fraud_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
