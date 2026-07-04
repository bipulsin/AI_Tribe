"""Seed demo garages, surveyors, and DEMO- claims for the fraud-graph illustration."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Claim, Garage, User
from app.models.enums import ClaimStatus

logger = logging.getLogger("ai_tribe.seed")

GARAGE_NAMES = [
    "Shree Balaji Motors, Pune",
    "Deccan Auto Care, Hyderabad",
    "Ganesh Multi-Brand Workshop, Nashik",
    "Highway Point Car Care, Indore",
    "Sai Service Point, Nagpur",
    "Metro Motors Garage, Ahmedabad",
    "Krishna Auto Works, Jaipur",
    "Coastal Car Care, Kochi",
    "Unity Multi-Brand Service, Lucknow",
    "Pearl Auto Hub, Chandigarh",
]

# Demo surveyor display names only — not login users.
SURVEYORS = [
    "Ananya Deshmukh",
    "Rohit Kulkarni",
    "Meera Iyer",
    "Vikram Chauhan",
    "Sneha Patil",
    "Arjun Nair",
]

CLAIMANTS = [
    "Rahul Mehta",
    "Priya Sharma",
    "Amit Joshi",
    "Neha Kulkarni",
    "Suresh Rao",
    "Kavita Singh",
    "Imran Sheikh",
    "Deepa Nambiar",
]


def seed_garages(db: Session) -> list[Garage]:
    existing = db.scalars(select(Garage)).all()
    if existing:
        logger.info("Garages already seeded (%s).", len(existing))
        return list(existing)

    garages = [Garage(name=name) for name in GARAGE_NAMES]
    db.add_all(garages)
    db.commit()
    for garage in garages:
        db.refresh(garage)
    logger.info("Seeded %s demo garages.", len(garages))
    return garages


def seed_demo_claims(db: Session) -> None:
    """Insert DEMO- claims with deliberate garage/surveyor/claimant overlap."""
    demo_count = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(Claim.claim_reference.like("DEMO-%"))
    )
    if demo_count and demo_count > 0:
        logger.info("Demo claims already present (%s); skipping.", demo_count)
        return

    admin = db.scalar(select(User).where(User.username == "admin"))
    if admin is None:
        logger.warning("No admin user; cannot seed demo claims.")
        return

    garages = seed_garages(db)
    by_name = {g.name: g for g in garages}

    # Deliberate patterns:
    # - Shree Balaji Motors appears on 4 claims
    # - Deccan Auto Care on 3 claims
    # - Ananya Deshmukh surveyor on 3 claims with Balaji
    # - Rahul Mehta claimant on 2 claims with different garages
    # - Meera Iyer + Highway Point pair on 2 claims
    specs = [
        ("DEMO-2026-000001", "Rahul Mehta", "Ananya Deshmukh", "Shree Balaji Motors, Pune"),
        ("DEMO-2026-000002", "Priya Sharma", "Ananya Deshmukh", "Shree Balaji Motors, Pune"),
        ("DEMO-2026-000003", "Amit Joshi", "Ananya Deshmukh", "Shree Balaji Motors, Pune"),
        ("DEMO-2026-000004", "Neha Kulkarni", "Rohit Kulkarni", "Shree Balaji Motors, Pune"),
        ("DEMO-2026-000005", "Suresh Rao", "Rohit Kulkarni", "Deccan Auto Care, Hyderabad"),
        ("DEMO-2026-000006", "Kavita Singh", "Vikram Chauhan", "Deccan Auto Care, Hyderabad"),
        ("DEMO-2026-000007", "Imran Sheikh", "Sneha Patil", "Deccan Auto Care, Hyderabad"),
        ("DEMO-2026-000008", "Deepa Nambiar", "Meera Iyer", "Highway Point Car Care, Indore"),
        ("DEMO-2026-000009", "Rahul Mehta", "Meera Iyer", "Highway Point Car Care, Indore"),
        ("DEMO-2026-000010", "Priya Sharma", "Arjun Nair", "Ganesh Multi-Brand Workshop, Nashik"),
        ("DEMO-2026-000011", "Amit Joshi", "Arjun Nair", "Sai Service Point, Nagpur"),
        ("DEMO-2026-000012", "Neha Kulkarni", "Vikram Chauhan", "Metro Motors Garage, Ahmedabad"),
        ("DEMO-2026-000013", "Suresh Rao", "Sneha Patil", "Krishna Auto Works, Jaipur"),
        ("DEMO-2026-000014", "Kavita Singh", "Rohit Kulkarni", "Coastal Car Care, Kochi"),
        ("DEMO-2026-000015", "Imran Sheikh", "Ananya Deshmukh", "Unity Multi-Brand Service, Lucknow"),
        ("DEMO-2026-000016", "Deepa Nambiar", "Meera Iyer", "Pearl Auto Hub, Chandigarh"),
        ("DEMO-2026-000017", "Rahul Mehta", "Vikram Chauhan", "Ganesh Multi-Brand Workshop, Nashik"),
        ("DEMO-2026-000018", "Priya Sharma", "Sneha Patil", "Sai Service Point, Nagpur"),
    ]

    for ref, claimant, surveyor, garage_name in specs:
        db.add(
            Claim(
                claim_reference=ref,
                created_by=admin.id,
                claimant_name=claimant,
                surveyor_name=surveyor,
                garage_id=by_name[garage_name].id,
                status=ClaimStatus.estimate_ready,
            )
        )
    db.commit()
    logger.info("Seeded %s DEMO- claims for fraud-graph illustration.", len(specs))


def seed_fraud_demo(db: Session) -> None:
    seed_garages(db)
    seed_demo_claims(db)
