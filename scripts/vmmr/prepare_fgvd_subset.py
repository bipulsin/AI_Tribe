#!/usr/bin/env python3
"""Extract FGVD crops for the 7 catalog classes with usable counts."""

from __future__ import annotations

import json
import random
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from PIL import Image

FGVD_ROOT = Path("/mnt/ml-scratch/fgvd/IDD_FGVD")
OUT_ROOT = Path("/mnt/ml-scratch/vmmr_data")
SEED = 42

# FGVD label -> catalog class key (make_model)
LABEL_MAP = {
    "car_MarutiSuzuki_Swift": "Maruti_Swift",
    "car_MarutiSuzuki_Baleno": "Maruti_Baleno",
    "car_Hyundai_I20": "Hyundai_i20",
    "car_Hyundai_Creta": "Hyundai_Creta",
    "car_Honda_City": "Honda_City",
    "car_Toyota_Innova": "Toyota_Innova",
    "car_Renault_Kwid": "Renault_Kwid",
}

CLASS_ORDER = [
    "Maruti_Swift",
    "Maruti_Baleno",
    "Hyundai_i20",
    "Hyundai_Creta",
    "Honda_City",
    "Toyota_Innova",
    "Renault_Kwid",
]


def crop_box(img: Image.Image, xmin, ymin, xmax, ymax, pad_frac: float = 0.05) -> Image.Image:
    w, h = img.size
    bw, bh = xmax - xmin, ymax - ymin
    pad_x = int(bw * pad_frac)
    pad_y = int(bh * pad_frac)
    left = max(0, xmin - pad_x)
    top = max(0, ymin - pad_y)
    right = min(w, xmax + pad_x)
    bottom = min(h, ymax + pad_y)
    return img.crop((left, top, right, bottom))


def main() -> None:
    random.seed(SEED)
    crops: dict[str, list[Path]] = defaultdict(list)
    out_crops = OUT_ROOT / "crops"
    out_crops.mkdir(parents=True, exist_ok=True)

    for split in ("train", "val", "test"):
        img_dir = FGVD_ROOT / split / "images"
        anno_dir = FGVD_ROOT / split / "annos"
        for xml_path in sorted(anno_dir.glob("*.xml")):
            stem = xml_path.stem
            # images may be .jpg
            img_path = None
            for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
                candidate = img_dir / f"{stem}{ext}"
                if candidate.exists():
                    img_path = candidate
                    break
            if img_path is None:
                continue
            try:
                tree = ET.parse(xml_path)
                img = Image.open(img_path).convert("RGB")
            except Exception:
                continue

            for idx, obj in enumerate(tree.findall("object")):
                name = (obj.findtext("name") or "").strip()
                class_key = LABEL_MAP.get(name)
                if not class_key:
                    continue
                bnd = obj.find("bndbox")
                if bnd is None:
                    continue
                xmin = int(float(bnd.findtext("xmin", "0")))
                ymin = int(float(bnd.findtext("ymin", "0")))
                xmax = int(float(bnd.findtext("xmax", "0")))
                ymax = int(float(bnd.findtext("ymax", "0")))
                if xmax <= xmin or ymax <= ymin:
                    continue
                crop = crop_box(img, xmin, ymin, xmax, ymax)
                if crop.size[0] < 32 or crop.size[1] < 32:
                    continue
                class_dir = out_crops / class_key
                class_dir.mkdir(parents=True, exist_ok=True)
                out_path = class_dir / f"{split}_{stem}_{idx}.jpg"
                crop.save(out_path, quality=90)
                crops[class_key].append(out_path)

    # 80/20 per-class split
    manifest = {"seed": SEED, "classes": {}, "train": [], "test": []}
    for class_key in CLASS_ORDER:
        paths = sorted(crops.get(class_key, []))
        random.shuffle(paths)
        n = len(paths)
        n_test = max(1, int(round(n * 0.2))) if n >= 5 else max(1, n // 5) if n >= 2 else 0
        # ensure at least 1 train if possible
        if n >= 2 and n_test >= n:
            n_test = n - 1
        test_paths = paths[:n_test]
        train_paths = paths[n_test:]
        manifest["classes"][class_key] = {
            "total": n,
            "train": len(train_paths),
            "test": len(test_paths),
            "test_statistically_meaningful": len(test_paths) >= 20,
        }
        for p in train_paths:
            manifest["train"].append({"path": str(p), "label": class_key})
        for p in test_paths:
            manifest["test"].append({"path": str(p), "label": class_key})

    manifest_path = OUT_ROOT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["classes"], indent=2))
    print(f"Wrote {manifest_path}")
    print(f"Train={len(manifest['train'])} Test={len(manifest['test'])}")


if __name__ == "__main__":
    main()
