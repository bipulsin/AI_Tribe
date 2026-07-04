"""Seed garages, surveyors, and claims for the fraud-graph illustration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

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

# Surveyor display names only — not login users.
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
    logger.info("Seeded %s garages.", len(garages))
    return garages


def _rename_legacy_demo_prefixes(db: Session) -> None:
    """Migrate any legacy DEMO- references to the normal CLM- sequence."""
    legacy = db.scalars(
        select(Claim).where(Claim.claim_reference.like("DEMO-%"))
    ).all()
    if not legacy:
        return
    year = datetime.now(timezone.utc).year
    for claim in legacy:
        claim.claim_reference = f"CLM-{year}-{claim.id:06d}"
    db.commit()
    logger.info("Renamed %s legacy DEMO- claim references to CLM-.", len(legacy))


def seed_graph_claims(db: Session) -> None:
    """Insert claims with deliberate garage/surveyor/claimant overlap."""
    _rename_legacy_demo_prefixes(db)

    seeded = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(
            Claim.claimant_name.in_(CLAIMANTS),
            Claim.surveyor_name.in_(SURVEYORS),
        )
    )
    if seeded and seeded >= 18:
        logger.info("Graph seed claims already present (%s); skipping.", seeded)
        return

    admin = db.scalar(select(User).where(User.username == "admin"))
    if admin is None:
        logger.warning("No admin user; cannot seed graph claims.")
        return

    garages = seed_garages(db)
    by_name = {g.name: g for g in garages}

    # Deliberate patterns for the network view.
    specs = [
        ("Rahul Mehta", "Ananya Deshmukh", "Shree Balaji Motors, Pune"),
        ("Priya Sharma", "Ananya Deshmukh", "Shree Balaji Motors, Pune"),
        ("Amit Joshi", "Ananya Deshmukh", "Shree Balaji Motors, Pune"),
        ("Neha Kulkarni", "Rohit Kulkarni", "Shree Balaji Motors, Pune"),
        ("Suresh Rao", "Rohit Kulkarni", "Deccan Auto Care, Hyderabad"),
        ("Kavita Singh", "Vikram Chauhan", "Deccan Auto Care, Hyderabad"),
        ("Imran Sheikh", "Sneha Patil", "Deccan Auto Care, Hyderabad"),
        ("Deepa Nambiar", "Meera Iyer", "Highway Point Car Care, Indore"),
        ("Rahul Mehta", "Meera Iyer", "Highway Point Car Care, Indore"),
        ("Priya Sharma", "Arjun Nair", "Ganesh Multi-Brand Workshop, Nashik"),
        ("Amit Joshi", "Arjun Nair", "Sai Service Point, Nagpur"),
        ("Neha Kulkarni", "Vikram Chauhan", "Metro Motors Garage, Ahmedabad"),
        ("Suresh Rao", "Sneha Patil", "Krishna Auto Works, Jaipur"),
        ("Kavita Singh", "Rohit Kulkarni", "Coastal Car Care, Kochi"),
        ("Imran Sheikh", "Ananya Deshmukh", "Unity Multi-Brand Service, Lucknow"),
        ("Deepa Nambiar", "Meera Iyer", "Pearl Auto Hub, Chandigarh"),
        ("Rahul Mehta", "Vikram Chauhan", "Ganesh Multi-Brand Workshop, Nashik"),
        ("Priya Sharma", "Sneha Patil", "Sai Service Point, Nagpur"),
    ]

    year = datetime.now(timezone.utc).year
    for claimant, surveyor, garage_name in specs:
        claim = Claim(
            claim_reference="PENDING",
            created_by=admin.id,
            claimant_name=claimant,
            surveyor_name=surveyor,
            garage_id=by_name[garage_name].id,
            status=ClaimStatus.estimate_ready,
        )
        db.add(claim)
        db.flush()
        claim.claim_reference = f"CLM-{year}-{claim.id:06d}"
    db.commit()
    logger.info("Seeded %s claims for fraud-graph illustration.", len(specs))


def seed_fraud_demo(db: Session) -> None:
    seed_garages(db)
    seed_graph_claims(db)
