#!/usr/bin/env python3
"""Build manifest.csv from VehiDE VIA JSON annotations (lab use only).

VehiDE ships 0Train_via_annos.json / 0Val_via_annos.json with romanized
Vietnamese region class codes. This script resolves image paths under the
Kaggle unzip layout and writes a CSV for eval_damage_classifier.py.

Usage (paperclip-vm):
  python scripts/damage/build_vehide_manifest.py --root /mnt/ml-scratch/vehide/raw
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "damage"))

from dataset_labels import normalize_vehide_code  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _find_image(raw_root: Path, filename: str) -> Path | None:
    """Locate image under common VehiDE unzip paths."""
    direct = raw_root / filename
    if direct.is_file():
        return direct
    nested = [
        raw_root / "image" / "image" / filename,
        raw_root / "image" / filename,
        raw_root / "validation" / "validation" / filename,
        raw_root / "validation" / filename,
        raw_root / "train" / filename,
    ]
    for candidate in nested:
        if candidate.is_file():
            return candidate
    for hit in raw_root.rglob(filename):
        if hit.suffix.lower() in IMAGE_EXTS:
            return hit
    return None


def _image_label(regions: list[dict]) -> str | None:
    votes: Counter[str] = Counter()
    for reg in regions:
        code = reg.get("class") or reg.get("region_attributes", {}).get("damage")
        if not code:
            continue
        norm = normalize_vehide_code(str(code))
        if norm:
            votes[norm] += 1
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def build_manifest(raw_root: Path, out_path: Path) -> dict[str, int]:
    rows: list[dict[str, str]] = []
    stats: Counter[str] = Counter()

    for split, json_name in (("train", "0Train_via_annos.json"), ("val", "0Val_via_annos.json")):
        ann_path = raw_root / json_name
        if not ann_path.is_file():
            print(f"SKIP missing {ann_path}")
            continue
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        missing = 0
        skipped = 0
        for _key, rec in data.items():
            fname = rec.get("filename") or rec.get("name") or _key
            img = _find_image(raw_root, fname)
            if img is None:
                missing += 1
                continue
            label = _image_label(rec.get("regions") or [])
            if not label:
                skipped += 1
                continue
            rel = img.relative_to(raw_root).as_posix()
            rows.append({"path": rel, "label": label, "split": split})
            stats[f"{split}:{label}"] += 1
        print(f"{json_name}: {len(data)} entries, wrote {sum(1 for r in rows if r['split']==split)}, missing={missing}, unmapped={skipped}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["path", "label", "split"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {out_path}")
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build VehiDE manifest.csv from VIA JSON")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/mnt/ml-scratch/vehide/raw"),
        help="VehiDE raw root (contains *via_annos.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output manifest path (default: <root>/manifest.csv)",
    )
    args = parser.parse_args()
    out = args.out or (args.root / "manifest.csv")
    if not args.root.is_dir():
        print(f"ERROR: root missing: {args.root}", file=sys.stderr)
        return 1
    build_manifest(args.root, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
