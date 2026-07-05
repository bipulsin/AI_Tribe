"""VehiDE overlap queue build + DB import for lab labeling."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PartsCatalog, VmmrLabLabel
from app.models.vmmr_lab_label import LICENSE_VEHIDE_NC_LAB
from app.services.vmmr import vmmr_classifier
from app.services.vmmr.lab_labeling.constants import (
    LAB_LABEL_NOTICE,
    OVERLAP_QUEUE_PATH,
    VEHIDE_LABEL_DIR,
    VEHIDE_RAW_ROOT,
)
from app.services.vmmr.lab_labeling.vision_guess import suggest_make_model

logger = logging.getLogger("ai_tribe.vmmr.lab_labeling")


def catalog_pairs(db: Session) -> set[tuple[str, str]]:
    rows = db.execute(
        select(PartsCatalog.make, PartsCatalog.model).distinct()
    ).all()
    return {(m.strip(), mod.strip()) for m, mod in rows if m and mod}


def _resolve_image(raw_root: Path, rel_path: str) -> Path | None:
    candidate = raw_root / rel_path
    if candidate.is_file():
        return candidate
    name = Path(rel_path).name
    for hit in raw_root.rglob(name):
        if hit.is_file():
            return hit
    return None


def build_overlap_queue(
    db: Session,
    *,
    raw_root: Path = VEHIDE_RAW_ROOT,
    split: str | None = "val",
    limit: int = 0,
    min_confidence: float = 0.05,
) -> dict:
    """Scan VehiDE manifest; keep images whose VMMR top-5 overlaps parts catalog."""
    manifest = raw_root / "manifest.csv"
    if not manifest.is_file():
        raise FileNotFoundError(f"Missing VehiDE manifest: {manifest}")

    pairs = catalog_pairs(db)
    items: list[dict] = []

    with manifest.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if split and row.get("split") and row["split"] != split:
                continue
            rel = row.get("path") or ""
            if not rel:
                continue
            img = _resolve_image(raw_root, rel)
            if img is None:
                continue
            guesses = vmmr_classifier.guess_top_k(img, k=5)
            hits = [
                {
                    "make": g.make,
                    "model": g.model,
                    "confidence": round(g.confidence, 4),
                    "class_key": g.class_key,
                }
                for g in guesses
                if (g.make, g.model) in pairs and g.confidence >= min_confidence
            ]
            if not hits:
                continue
            items.append(
                {
                    "image_path": str(img),
                    "image_rel_path": rel,
                    "damage_hint": row.get("label"),
                    "overlap_hits": hits,
                    "top_hit": hits[0],
                }
            )
            if limit > 0 and len(items) >= limit:
                break

    VEHIDE_LABEL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "license_tag": LICENSE_VEHIDE_NC_LAB,
        "source_dataset": "vehide",
        "overlap_criteria": "vmmr_top5 intersect parts_catalog make/model",
        "catalog_pair_count": len(pairs),
        "lab_use_only_notice": LAB_LABEL_NOTICE,
        "items": items,
    }
    OVERLAP_QUEUE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    logger.info("VehiDE overlap queue: %s items -> %s", len(items), OVERLAP_QUEUE_PATH)
    return {"queued": len(items), "path": str(OVERLAP_QUEUE_PATH)}


def import_overlap_queue(db: Session, *, refresh_guess: bool = False) -> dict:
    if not OVERLAP_QUEUE_PATH.is_file():
        return {"imported": 0, "detail": "overlap_queue.json missing; run build script first"}

    payload = json.loads(OVERLAP_QUEUE_PATH.read_text(encoding="utf-8"))
    imported = 0
    skipped = 0

    for item in payload.get("items") or []:
        image_path = item["image_path"]
        exists = db.scalar(
            select(VmmrLabLabel.id).where(VmmrLabLabel.image_path == image_path)
        )
        if exists:
            skipped += 1
            continue

        top = item.get("top_hit") or (item.get("overlap_hits") or [{}])[0]
        row = VmmrLabLabel(
            source_dataset="vehide",
            image_path=image_path,
            image_rel_path=item.get("image_rel_path"),
            damage_hint=item.get("damage_hint"),
            suggested_make=top.get("make"),
            suggested_model=top.get("model"),
            suggested_confidence=top.get("confidence"),
            guess_source="vmmr_local",
            guess_detail="Imported from VehiDE/catalog overlap queue.",
            suggested_alternatives=item.get("overlap_hits"),
            status="pending",
            license_tag=LICENSE_VEHIDE_NC_LAB,
        )
        db.add(row)
        imported += 1

    db.commit()

    if refresh_guess and imported:
        pending = db.scalars(
            select(VmmrLabLabel)
            .where(VmmrLabLabel.status == "pending")
            .order_by(VmmrLabLabel.id.asc())
            .limit(imported)
        ).all()
        for row in pending:
            _apply_guess(db, row)

    return {"imported": imported, "skipped": skipped, "path": str(OVERLAP_QUEUE_PATH)}


def _apply_guess(db: Session, row: VmmrLabLabel) -> None:
    guess = suggest_make_model(Path(row.image_path))
    row.suggested_make = guess.suggested_make
    row.suggested_model = guess.suggested_model
    row.suggested_confidence = guess.suggested_confidence
    row.guess_source = guess.guess_source
    row.guess_detail = guess.guess_detail
    row.suggested_alternatives = [
        {
            "make": guess.suggested_make,
            "model": guess.suggested_model,
            "confidence": guess.suggested_confidence,
        },
        *guess.alternatives,
    ]


def ensure_guess(db: Session, row: VmmrLabLabel) -> VmmrLabLabel:
    if row.suggested_make and row.guess_source:
        return row
    _apply_guess(db, row)
    db.commit()
    db.refresh(row)
    return row


def labeling_stats(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(VmmrLabLabel)) or 0
    pending = (
        db.scalar(
            select(func.count())
            .select_from(VmmrLabLabel)
            .where(VmmrLabLabel.status == "pending")
        )
        or 0
    )
    confirmed = (
        db.scalar(
            select(func.count())
            .select_from(VmmrLabLabel)
            .where(VmmrLabLabel.status == "confirmed")
        )
        or 0
    )
    skipped = (
        db.scalar(
            select(func.count())
            .select_from(VmmrLabLabel)
            .where(VmmrLabLabel.status == "skipped")
        )
        or 0
    )
    return {
        "total": total,
        "pending": pending,
        "confirmed": confirmed,
        "skipped": skipped,
        "source_dataset": "vehide",
        "license_tag": LICENSE_VEHIDE_NC_LAB,
        "lab_use_only_notice": LAB_LABEL_NOTICE,
        "overlap_queue_path": str(OVERLAP_QUEUE_PATH),
        "export_path": str(VEHIDE_LABEL_DIR / "confirmed_labels.jsonl"),
    }
