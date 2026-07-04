"""Seed garages, surveyors, and claims for the fraud-graph illustration."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import REPO_ROOT, get_settings
from app.models import (
    Claim,
    ClaimImage,
    DamageDetection,
    Garage,
    User,
    Vehicle,
)
from app.models.enums import AuthenticityVerdict, ClaimStatus, DamageType, Severity
from app.services.parts import estimate_builder
from app.services.storage import LocalFilesystemStorage

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

# FGVD / VMMR class folder → (make, model, identity_confirmed, pricing_basis)
_VEHICLE_PROFILES: list[tuple[str, str, str, bool, str]] = [
    ("Maruti_Swift", "Maruti", "Swift", True, "confirmed"),
    ("Toyota_Innova", "Toyota", "Innova", True, "confirmed"),
    ("Hyundai_i20", "Hyundai", "i20", True, "confirmed"),
    ("Maruti_Swift", "Maruti", "Swift", True, "confirmed"),
    ("Toyota_Innova", "Toyota", "Innova", True, "confirmed"),
    ("Hyundai_i20", "Hyundai", "i20", True, "confirmed"),
    ("Honda_City", "Honda", "City", False, "needs_confirmation"),
    ("Maruti_Baleno", "Maruti", "Baleno", False, "needs_confirmation"),
    ("Hyundai_Creta", "Hyundai", "Creta", False, "needs_confirmation"),
    ("Maruti_Swift", "Maruti", "Swift", True, "confirmed"),
    ("Toyota_Innova", "Toyota", "Innova", True, "confirmed"),
    ("Hyundai_i20", "Hyundai", "i20", True, "confirmed"),
    ("Renault_Kwid", "Renault", "Kwid", False, "needs_confirmation"),
    ("Mahindra_XUV500", "Mahindra", "XUV500", False, "needs_confirmation"),
    ("Maruti_Swift", "Maruti", "Swift", True, "confirmed"),
    ("Toyota_Innova", "Toyota", "Innova", True, "confirmed"),
    ("Hyundai_i20", "Hyundai", "i20", True, "confirmed"),
    ("Honda_City", "Honda", "City", False, "needs_confirmation"),
]

# Part / damage profiles (catalogue part names + damage type + severity + action)
_DAMAGE_PROFILES: list[list[tuple[str, DamageType, Severity, str, float]]] = [
    [
        ("Front Bumper", DamageType.dent, Severity.moderate, "replace", 0.91),
        ("Headlamp", DamageType.lamp_broken, Severity.severe, "replace", 0.88),
    ],
    [
        ("Rear Bumper", DamageType.scratch, Severity.minor, "repair", 0.84),
        ("Tail Lamp", DamageType.lamp_broken, Severity.moderate, "replace", 0.86),
    ],
    [
        ("Front Door", DamageType.dent, Severity.moderate, "repair", 0.89),
        ("Side Mirror", DamageType.crack, Severity.minor, "replace", 0.82),
    ],
    [
        ("Hood", DamageType.dent, Severity.severe, "replace", 0.93),
        ("Front Grill", DamageType.crack, Severity.moderate, "replace", 0.80),
    ],
    [
        ("Front Fender", DamageType.dent, Severity.moderate, "repair", 0.87),
        ("Fog Lamp", DamageType.lamp_broken, Severity.minor, "replace", 0.79),
    ],
    [
        ("Rear Door", DamageType.scratch, Severity.minor, "repair", 0.81),
        ("Quarter Panel", DamageType.dent, Severity.moderate, "repair", 0.85),
    ],
    [
        ("Windshield", DamageType.glass_shatter, Severity.severe, "replace", 0.94),
        ("Hood", DamageType.scratch, Severity.minor, "repair", 0.77),
    ],
    [
        ("Front Bumper", DamageType.dent, Severity.moderate, "replace", 0.90),
        ("Front Fender", DamageType.scratch, Severity.minor, "repair", 0.83),
    ],
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


def _seed_image_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = (os.environ.get("SEED_IMAGE_ROOT") or "").strip()
    if env_root:
        roots.append(Path(env_root))
    roots.extend(
        [
            REPO_ROOT / "data" / "seed_images",
            Path("/app/data/seed_images"),
            Path("/mnt/ml-scratch/vmmr_data/crops"),
            Path("/mnt/ml-scratch/vmmr_data"),
            Path("/mnt/ml-scratch/vmmr_data/train"),
            Path("/mnt/ml-scratch/vmmr_data/val"),
            Path("/mnt/ml-scratch/vmmr_data/test"),
        ]
    )
    return roots


def _find_class_images(class_folder: str, *, limit: int = 2) -> list[Path]:
    """Locate sample photos for a VMMR/FGVD class folder name."""
    found: list[Path] = []
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    for root in _seed_image_roots():
        if not root.exists():
            continue
        candidates = [
            root / class_folder,
            root / "crops" / class_folder,
            root / "train" / class_folder,
            root / "val" / class_folder,
            root / "test" / class_folder,
        ]
        for folder in candidates:
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in suffixes:
                    found.append(path)
                    if len(found) >= limit:
                        return found
    return found


def _placeholder_image(make: str, model: str) -> bytes:
    """Small labeled JPEG when ML sample photos are not mounted."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 400), color=(28, 40, 58))
    draw = ImageDraw.Draw(img)
    draw.rectangle((24, 24, 616, 376), outline=(184, 134, 11), width=3)
    label = f"{make} {model}"
    draw.text((40, 170), label, fill=(232, 236, 241))
    draw.text((40, 210), "Seed vehicle photo", fill=(184, 134, 11))
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _images_are_placeholders(claim: Claim) -> bool:
    if not claim.images:
        return False
    return all(
        "Placeholder" in (image.authenticity_reason or "") for image in claim.images
    )


def _attach_images(
    storage: LocalFilesystemStorage,
    db: Session,
    claim: Claim,
    class_folder: str,
    make: str,
    model: str,
) -> tuple[list[ClaimImage], str]:
    """Return (images, source) where source is ml | placeholder | existing."""
    paths = _find_class_images(class_folder, limit=2)
    if claim.images and not (_images_are_placeholders(claim) and paths):
        return list(claim.images), "existing"

    if claim.images and paths:
        for detection in list(claim.damage_detections):
            db.delete(detection)
        db.flush()
        for image in list(claim.images):
            storage.delete(image.file_path)
            db.delete(image)
        db.flush()
        claim.images.clear()
        claim.damage_detections.clear()

    images: list[ClaimImage] = []
    if paths:
        for order, path in enumerate(paths, start=1):
            relative = storage.save(path, claim.id, path.name)
            images.append(
                ClaimImage(
                    claim_id=claim.id,
                    file_path=relative,
                    image_order=order,
                    is_video=False,
                    quality_gate_passed=True,
                    authenticity_verdict=AuthenticityVerdict.clear,
                    authenticity_reason="Seeded from VMMR/FGVD sample photos.",
                )
            )
        return images, "ml"

    relative = storage.save_bytes(
        _placeholder_image(make, model),
        claim.id,
        f"{class_folder.lower()}.jpg",
    )
    images.append(
        ClaimImage(
            claim_id=claim.id,
            file_path=relative,
            image_order=1,
            is_video=False,
            quality_gate_passed=True,
            authenticity_verdict=AuthenticityVerdict.clear,
            authenticity_reason="Placeholder seed image (no ML sample photos found).",
        )
    )
    return images, "placeholder"


def enrich_graph_claims(db: Session) -> None:
    """Attach vehicle, images, damage parts, and estimates to graph seed claims."""
    claims = list(
        db.scalars(
            select(Claim)
            .options(
                selectinload(Claim.images),
                selectinload(Claim.vehicles),
                selectinload(Claim.damage_detections),
                selectinload(Claim.estimate),
            )
            .where(
                Claim.claimant_name.in_(CLAIMANTS),
                Claim.surveyor_name.in_(SURVEYORS),
            )
            .order_by(Claim.id.asc())
        ).all()
    )
    if not claims:
        return

    storage = LocalFilesystemStorage(get_settings().upload_path)
    updated = 0
    used_ml_images = 0
    used_placeholders = 0

    for index, claim in enumerate(claims):
        profile = _VEHICLE_PROFILES[index % len(_VEHICLE_PROFILES)]
        class_folder, make, model, confirmed, pricing_basis = profile
        damage_profile = _DAMAGE_PROFILES[index % len(_DAMAGE_PROFILES)]

        images, image_source = _attach_images(
            storage, db, claim, class_folder, make, model
        )
        if image_source in {"ml", "placeholder"}:
            db.add_all(images)
            db.flush()
            if image_source == "ml":
                used_ml_images += 1
            else:
                used_placeholders += 1

        if not claim.vehicles:
            db.add(
                Vehicle(
                    make=make,
                    model=model,
                    year=2019 + (index % 5),
                    identity_confirmed=confirmed,
                    pricing_basis=pricing_basis,
                    source_claim_id=claim.id,
                )
            )

        if not claim.damage_detections:
            image_id = images[0].id if images else None
            if image_id is None and claim.images:
                image_id = claim.images[0].id
            if image_id is None:
                continue
            for part_name, damage_type, severity, action, confidence in damage_profile:
                db.add(
                    DamageDetection(
                        claim_id=claim.id,
                        claim_image_id=image_id,
                        part_name=part_name,
                        damage_type=damage_type,
                        severity=severity,
                        repair_or_replace=action,
                        confidence_score=confidence,
                    )
                )

        if claim.status == ClaimStatus.estimate_ready:
            db.flush()
            estimate_builder.persist_estimate(db, claim.id)

        updated += 1

    db.commit()
    logger.info(
        "Enriched %s graph claims (ml_images=%s, placeholders=%s).",
        updated,
        used_ml_images,
        used_placeholders,
    )


def seed_fraud_demo(db: Session) -> None:
    seed_garages(db)
    seed_graph_claims(db)
    enrich_graph_claims(db)
