"""Lab-only VMMR labeling constants and paths."""

from __future__ import annotations

import os
from pathlib import Path

LAB_LABEL_NOTICE = (
    "Lab research only. Labels from VehiDE-derived images are non-commercial "
    "research data and must not be merged into any dataset used to retrain a "
    "model serving the live tribe.tradentical.com pipeline without separately "
    "re-confirming compatibility with VehiDE's terms at that time."
)

VMMR_LABEL_ROOT = Path(
    os.environ.get("VMMR_LABEL_ROOT", "/mnt/ml-scratch/vmmr_labeling")
)
VEHIDE_RAW_ROOT = Path(os.environ.get("VEHIDE_RAW_ROOT", "/mnt/ml-scratch/vehide/raw"))
VEHIDE_LABEL_DIR = VMMR_LABEL_ROOT / "vehide"
OVERLAP_QUEUE_PATH = VEHIDE_LABEL_DIR / "overlap_queue.json"
CONFIRMED_JSONL = VEHIDE_LABEL_DIR / "confirmed_labels.jsonl"

LICENSE_VEHIDE_NC_LAB = "vehide_nc_lab_only"
