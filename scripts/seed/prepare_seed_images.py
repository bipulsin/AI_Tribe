#!/usr/bin/env python3
"""Copy a few VMMR/FGVD sample photos into data/seed_images for claim seeding.

Looks under /mnt/ml-scratch/vmmr_data (or SEED_IMAGE_ROOT) and copies up to
two images per class folder into the repo's data/seed_images/<Class>/ tree.
Run on paperclip-vm before rebuilding the app image when ML scratch is available.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEST_ROOT = REPO_ROOT / "data" / "seed_images"

CLASSES = [
    "Maruti_Swift",
    "Toyota_Innova",
    "Hyundai_i20",
    "Honda_City",
    "Maruti_Baleno",
    "Hyundai_Creta",
    "Renault_Kwid",
    "Mahindra_XUV500",
]

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def source_roots() -> list[Path]:
    roots: list[Path] = []
    env = (os.environ.get("SEED_IMAGE_ROOT") or "").strip()
    if env:
        roots.append(Path(env))
    roots.extend(
        [
            Path("/mnt/ml-scratch/vmmr_data/crops"),
            Path("/mnt/ml-scratch/vmmr_data"),
            Path("/mnt/ml-scratch/vmmr_data/train"),
            Path("/mnt/ml-scratch/vmmr_data/val"),
            Path("/mnt/ml-scratch/vmmr_data/test"),
        ]
    )
    return roots


def find_images(class_name: str, limit: int = 2) -> list[Path]:
    found: list[Path] = []
    for root in source_roots():
        if not root.exists():
            continue
        for folder in (
            root / class_name,
            root / "crops" / class_name,
            root / "train" / class_name,
            root / "val" / class_name,
            root / "test" / class_name,
        ):
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in SUFFIXES:
                    found.append(path)
                    if len(found) >= limit:
                        return found
    return found


def main() -> int:
    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing: list[str] = []
    for class_name in CLASSES:
        images = find_images(class_name, limit=2)
        if not images:
            missing.append(class_name)
            continue
        dest_dir = DEST_ROOT / class_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        for path in images:
            dest = dest_dir / path.name
            if dest.exists():
                continue
            shutil.copy2(path, dest)
            copied += 1
            print(f"copied {path} -> {dest}")
    print(f"done: copied={copied}, missing_classes={missing or 'none'}")
    return 0 if not missing else 0


if __name__ == "__main__":
    sys.exit(main())
