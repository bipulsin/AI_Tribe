#!/usr/bin/env python3
"""Benchmark beingamit99/car_damage_detection on labeled damage images.

Usage (on paperclip, ML_MODE=live):
  python scripts/damage/eval_damage_classifier.py --root /mnt/ml-scratch/vehide/raw
  python scripts/damage/eval_damage_classifier.py --root /mnt/ml-scratch/cardd/raw

Expects images grouped by class folder name OR flat with manifest.csv (path,label).
Writes JSON report under /mnt/ml-scratch/damage_eval/runs/.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "damage"))

os.environ.setdefault("ML_MODE", "live")
os.environ.setdefault(
    "HF_HOME", str(ROOT / "backend" / "app" / "ml_weights" / "huggingface")
)
os.environ.setdefault(
    "TORCH_HOME", str(ROOT / "backend" / "app" / "ml_weights" / "torch")
)

from app.core.config import get_settings  # noqa: E402
from app.services.damage import damage_segmenter  # noqa: E402
from dataset_labels import normalize_label  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _collect_labeled(root: Path, split: str | None = None) -> list[tuple[Path, str]]:
    labeled: list[tuple[Path, str]] = []
    manifest = root / "manifest.csv"
    if manifest.is_file():
        with manifest.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if split and row.get("split") and row["split"] != split:
                    continue
                rel = row.get("path") or row.get("file") or row.get("image")
                label = row.get("label") or row.get("class")
                if not rel or not label:
                    continue
                norm = normalize_label(label)
                if norm:
                    labeled.append((root / rel, norm))
        return labeled

    for class_dir in sorted(root.iterdir()):
        if not class_dir.is_dir():
            continue
        norm = normalize_label(class_dir.name)
        if not norm:
            continue
        for path in class_dir.rglob("*"):
            if path.suffix.lower() in IMAGE_EXTS:
                labeled.append((path, norm))
    return labeled


def _find_image_roots(base: Path) -> list[Path]:
    """Walk common VehiDE/CarDD unpack layouts."""
    candidates = [base]
    for name in ("images", "Images", "train", "test", "val", "data"):
        p = base / name
        if p.is_dir():
            candidates.append(p)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate live damage classifier")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/mnt/ml-scratch/vehide/raw"),
        help="Dataset root (class subfolders or manifest.csv)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max images (0=all)")
    parser.add_argument(
        "--split",
        choices=("train", "val"),
        default=None,
        help="When manifest.csv has a split column, evaluate that subset only",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/mnt/ml-scratch/damage_eval/runs"),
        help="Report output directory",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    if not get_settings().ml_live:
        print("ERROR: ML_MODE must be live", file=sys.stderr)
        return 1

    labeled: list[tuple[Path, str]] = []
    for candidate in _find_image_roots(args.root):
        labeled.extend(_collect_labeled(candidate, split=args.split))

    # De-dupe paths
    seen: set[Path] = set()
    unique: list[tuple[Path, str]] = []
    for path, label in labeled:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        unique.append((path, label))
    labeled = unique

    if args.limit > 0:
        labeled = labeled[: args.limit]

    if not labeled:
        print(f"No labeled images found under {args.root}")
        print("Populate VehiDE/CarDD under ml-scratch or pass --root")
        return 2

    print(f"Evaluating {len(labeled)} images from {args.root}")
    correct = 0
    skipped = 0
    per_class: dict[str, Counter] = defaultdict(Counter)
    examples_wrong: list[dict] = []

    for path, gold in labeled:
        try:
            pred = damage_segmenter.classify_image(path)
        except OSError as exc:
            skipped += 1
            if skipped <= 5:
                print(f"SKIP unreadable {path}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001 — lab harness should finish the run
            skipped += 1
            if skipped <= 5:
                print(f"SKIP error {path}: {exc}", file=sys.stderr)
            continue
        pred_label = pred.damage_type.value
        hit = pred_label == gold
        if hit:
            correct += 1
        else:
            per_class[gold]["wrong"] += 1
            if len(examples_wrong) < 15:
                examples_wrong.append(
                    {
                        "path": str(path),
                        "gold": gold,
                        "pred": pred_label,
                        "confidence": round(pred.confidence, 4),
                        "raw_label": pred.label,
                    }
                )
        per_class[gold]["total"] += 1
        if hit:
            per_class[gold]["correct"] += 1

    acc = correct / (len(labeled) - skipped) if (len(labeled) - skipped) else 0.0
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "model": damage_segmenter.MODEL_ID,
        "dataset_root": str(args.root),
        "split": args.split,
        "n_images": len(labeled),
        "n_skipped": skipped,
        "n_scored": len(labeled) - skipped,
        "top1_accuracy": round(acc, 4),
        "per_class": {
            cls: {
                "total": counts["total"],
                "correct": counts.get("correct", 0),
                "accuracy": round(counts.get("correct", 0) / counts["total"], 4)
                if counts["total"]
                else 0.0,
            }
            for cls, counts in sorted(per_class.items())
        },
        "misclassified_examples": examples_wrong,
        "created_at": ts,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"eval_{args.root.name}_{ts}.json"
    out_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"Top-1 accuracy: {acc:.1%} ({correct}/{len(labeled) - skipped})"
        + (f", skipped {skipped} unreadable" if skipped else "")
    )
    print(f"Report: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
