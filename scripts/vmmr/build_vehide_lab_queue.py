#!/usr/bin/env python3
"""Build VehiDE × parts-catalog overlap queue for lab VMMR labeling.

Requires ML_MODE=live and VehiDE manifest on ml-scratch. Does not download CarDD.

Usage (paperclip-vm):
  ML_MODE=live python scripts/vmmr/build_vehide_lab_queue.py --split val
  ML_MODE=live python scripts/vmmr/build_vehide_lab_queue.py --split val --import-db
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("ML_MODE", "live")

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.vmmr.lab_labeling.vehide_queue import (  # noqa: E402
    build_overlap_queue,
    import_overlap_queue,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="VehiDE catalog overlap queue for lab labeling")
    parser.add_argument("--split", choices=("train", "val"), default="val")
    parser.add_argument("--limit", type=int, default=0, help="Max images (0=all scanned)")
    parser.add_argument("--import-db", action="store_true", help="Import queue into Postgres")
    args = parser.parse_args()

    get_settings.cache_clear()
    if not get_settings().ml_live:
        print("ERROR: set ML_MODE=live for overlap scan", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        result = build_overlap_queue(db, split=args.split, limit=args.limit)
        print(f"Overlap queue: {result['queued']} items -> {result['path']}")
        if args.import_db:
            imported = import_overlap_queue(db)
            print(f"Imported: {imported}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
