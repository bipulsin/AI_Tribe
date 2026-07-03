"""Seed default admin user and parts catalog.

Creates username `admin` / password `admin` (bcrypt-hashed) when the users
table is empty. This default credential must be changed before any use
beyond local lab demos.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import REPO_ROOT
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import PartsCatalog, User

logger = logging.getLogger("ai_tribe.seed")

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"
PARTS_SEED_CSV = REPO_ROOT / "data" / "parts_seed" / "india_parts_seed.csv"


def seed_admin(db) -> None:
    count = db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        logger.info("Users table already has %s row(s); skipping admin seed.", count)
        return

    admin = User(
        username=DEFAULT_ADMIN_USERNAME,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        full_name="Lab Administrator",
        role="admin",
    )
    db.add(admin)
    db.commit()
    print(
        "\n"
        "!" * 72 + "\n"
        "  SEEDED default user: admin / admin\n"
        "  Change this credential before anything resembling production use.\n"
        + "!" * 72
        + "\n"
    )


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
                    source=(row.get("source") or "seed_india_v1").strip(),
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
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
