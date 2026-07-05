"""Persist human-confirmed lab labels to ml-scratch (never live model paths)."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.models.vmmr_lab_label import VmmrLabLabel
from app.services.vmmr.lab_labeling.constants import (
    CONFIRMED_JSONL,
    LAB_LABEL_NOTICE,
    LICENSE_VEHIDE_NC_LAB,
    VEHIDE_LABEL_DIR,
)

logger = logging.getLogger("ai_tribe.vmmr.lab_labeling")


def _ensure_dirs() -> None:
    (VEHIDE_LABEL_DIR / "confirmed_images").mkdir(parents=True, exist_ok=True)
    CONFIRMED_JSONL.parent.mkdir(parents=True, exist_ok=True)


def save_confirmed_label(row: VmmrLabLabel, *, labeled_by: int) -> str | None:
    """Copy image into lab scratch and append JSONL export row."""
    src = Path(row.image_path)
    if not src.is_file():
        logger.warning("Lab label confirm: missing image %s", src)
        return None

    _ensure_dirs()
    dest_dir = VEHIDE_LABEL_DIR / "confirmed_images" / row.source_dataset
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{row.id}_{src.name}"
    shutil.copy2(src, dest)

    record = {
        "id": row.id,
        "source_dataset": row.source_dataset,
        "license_tag": row.license_tag or LICENSE_VEHIDE_NC_LAB,
        "image_path": str(dest),
        "original_image_path": row.image_path,
        "image_rel_path": row.image_rel_path,
        "damage_hint": row.damage_hint,
        "confirmed_make": row.confirmed_make,
        "confirmed_model": row.confirmed_model,
        "suggested_make": row.suggested_make,
        "suggested_model": row.suggested_model,
        "guess_source": row.guess_source,
        "labeled_by": labeled_by,
        "labeled_at": datetime.now(timezone.utc).isoformat(),
        "lab_use_only_notice": LAB_LABEL_NOTICE,
        "live_pipeline_merge": False,
    }
    with CONFIRMED_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(
        "Lab VMMR label confirmed id=%s %s %s -> %s",
        row.id,
        row.confirmed_make,
        row.confirmed_model,
        dest,
    )
    return str(dest)
