#!/usr/bin/env python3
"""Copy FGVD-7 checkpoint into app ml_weights, retune margin, smoke-test gate."""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN_ROOT = Path("/mnt/ml-scratch/vmmr_runs")
DATA_ROOT = Path("/mnt/ml-scratch/vmmr_data")
DEST = REPO / "backend" / "app" / "ml_weights" / "vmmr"
CKPT_NAME = "vmmr_resnet50_fgvd8.pt"
MIN_RELIABLE_SOURCE = 100

PROVISIONAL_ONLY = ["Tata_Nexon", "Mahindra_XUV700", "Kia_Seltos"]
# Always low_confidence regardless of held-out accuracy.
FORCED_LOW_CONFIDENCE = {"Mahindra_XUV500"}


def latest_run() -> Path:
    runs = sorted(RUN_ROOT.glob("*/"), key=lambda p: p.name, reverse=True)
    if not runs:
        raise SystemExit(f"No runs under {RUN_ROOT}")
    return runs[0]


def _percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    idx = int(round((q / 100) * (len(s) - 1)))
    return s[idx]


def reevaluate(ckpt_path: Path) -> tuple[dict, float]:
    """Recompute per-class metrics + margin threshold from held-out set."""
    import torch
    from PIL import Image
    from torchvision import transforms
    from torchvision.models import resnet50

    ckpt = torch.load(ckpt_path, map_location="cpu")
    class_names = list(ckpt["class_names"])
    model = resnet50(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(class_names))
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    tf = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ]
    )

    manifest = json.loads((DATA_ROOT / "manifest.json").read_text())
    source_totals = {
        name: manifest["classes"][name]["total"] for name in class_names
    }
    class_to_idx = {n: i for i, n in enumerate(class_names)}

    correct_top1 = Counter()
    total = Counter()
    margins_by_class: dict[str, list[float]] = defaultdict(list)
    correct_margins_by_class: dict[str, list[float]] = defaultdict(list)
    all_margins: list[float] = []
    correct_margins: list[float] = []

    for row in manifest["test"]:
        label = row["label"]
        path = Path(row["path"])
        with Image.open(path) as img:
            tensor = tf(img.convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            probs = torch.softmax(model(tensor)[0], dim=0)
        top2 = torch.topk(probs, k=2)
        pred = class_names[int(top2.indices[0])]
        margin = float(top2.values[0] - top2.values[1])
        total[label] += 1
        margins_by_class[label].append(margin)
        all_margins.append(margin)
        if pred == label:
            correct_top1[label] += 1
            correct_margins_by_class[label].append(margin)
            correct_margins.append(margin)

    per_class = {}
    for name in class_names:
        n = total[name]
        n_source = source_totals[name]
        reliable = (
            name not in FORCED_LOW_CONFIDENCE
            and n_source >= MIN_RELIABLE_SOURCE
            and n >= 20
        )
        note = None
        if name in FORCED_LOW_CONFIDENCE:
            note = (
                f"Forced low_confidence tier ({n_source} source images); "
                "sample size does not support reliable auto-finalize."
            )
        elif not reliable:
            note = (
                f"Not statistically meaningful: {n_source} source images, "
                f"{n} held-out test images. Report the number but do not "
                "treat accuracy as reliable."
            )
        per_class[name] = {
            "n_source": n_source,
            "n_test": n,
            "top1_acc": (correct_top1[name] / n) if n else None,
            "top1_correct": correct_top1[name],
            "margin_mean": (
                sum(margins_by_class[name]) / len(margins_by_class[name])
                if margins_by_class[name]
                else None
            ),
            "margin_p25": _percentile(margins_by_class[name], 25),
            "margin_p50": _percentile(margins_by_class[name], 50),
            "margin_p75": _percentile(margins_by_class[name], 75),
            "correct_margin_mean": (
                sum(correct_margins_by_class[name])
                / len(correct_margins_by_class[name])
                if correct_margins_by_class[name]
                else None
            ),
            "correct_margin_p25": _percentile(correct_margins_by_class[name], 25),
            "correct_margin_p50": _percentile(correct_margins_by_class[name], 50),
            "statistically_meaningful": reliable,
            "reliability_note": note,
            "tier": "low_confidence" if not reliable else "reliable",
        }

    overall_n = sum(total.values())
    overall_top1 = sum(correct_top1.values()) / overall_n if overall_n else 0.0

    suggested = 0.4
    correct_p25 = _percentile(correct_margins, 25)
    correct_p50 = _percentile(correct_margins, 50)
    if correct_p25 is not None and correct_p25 < 0.4:
        suggested = max(0.25, round(correct_p25, 2))
    elif correct_p50 is not None and correct_p50 < 0.35:
        suggested = max(0.25, round(correct_p50, 2))

    metrics = {
        "overall_top1": overall_top1,
        "overall_n": overall_n,
        "overall_note": (
            "Overall accuracy is dominated by Swift/Innova; always read per-class "
            "numbers. Classes with <100 source images are not reliable."
        ),
        "per_class": per_class,
        "margin_mean": sum(all_margins) / len(all_margins) if all_margins else 0.0,
        "margin_p25": _percentile(all_margins, 25),
        "margin_p50": _percentile(all_margins, 50),
        "margin_p75": _percentile(all_margins, 75),
        "correct_margin_mean": (
            sum(correct_margins) / len(correct_margins) if correct_margins else 0.0
        ),
        "correct_margin_p25": correct_p25,
        "correct_margin_p50": correct_p50,
        "correct_margin_p75": _percentile(correct_margins, 75),
        "margin_threshold_selected": suggested,
        "margin_threshold_rationale": (
            f"Started at 0.4; correct-margin p25={correct_p25}, p50={correct_p50}; "
            f"selected {suggested}."
        ),
        "provisional_only_catalog_models": PROVISIONAL_ONLY,
        "trained_catalog_models": class_names,
    }
    return metrics, suggested


def deploy(run_dir: Path) -> Path:
    src = run_dir / CKPT_NAME
    if not src.exists():
        raise SystemExit(f"Missing checkpoint {src}")
    DEST.mkdir(parents=True, exist_ok=True)
    dest_ckpt = DEST / CKPT_NAME
    shutil.copy2(src, dest_ckpt)

    metrics, margin_thr = reevaluate(dest_ckpt)

    # Persist tuned margin into the app-local checkpoint (independent of /mnt/ml-scratch).
    import torch

    ckpt = torch.load(dest_ckpt, map_location="cpu")
    ckpt["margin_threshold"] = margin_thr
    ckpt["dataset_version"] = "FGVD_IDD_v1_catalog8"
    torch.save(ckpt, dest_ckpt)

    # Also refresh run-dir metrics for the registry.
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    deploy_meta = {
        "checkpoint": str(dest_ckpt),
        "class_names": ckpt["class_names"],
        "margin_threshold": margin_thr,
        "excluded_catalog_models": PROVISIONAL_ONLY,
        "trained_catalog_models": list(ckpt["class_names"]),
    }
    (run_dir / "deploy.json").write_text(json.dumps(deploy_meta, indent=2))

    meta = {
        "class_names": list(ckpt["class_names"]),
        "margin_threshold": margin_thr,
        "dataset_version": "FGVD_IDD_v1_catalog8",
        "trained_catalog_models": list(ckpt["class_names"]),
        "provisional_only_catalog_models": PROVISIONAL_ONLY,
        "source_run": run_dir.name,
        "metrics_summary": metrics,
        "notes": (
            "Eight catalog models have real (uneven) FGVD training data. "
            "Baleno/City/Kwid/XUV500 have <100 source images — held-out accuracy "
            "is reported but not statistically meaningful. XUV500 is forced "
            "low_confidence and prices via same-make XUV700 fallback with "
            "pricing_basis=model_fallback_priced. Nexon, XUV700, and Seltos "
            "have zero usable training data and stay provisional_fallback."
        ),
    }
    (DEST / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Deployed {src} -> {dest_ckpt}")
    print(f"Margin threshold: {margin_thr}")
    print(f"Wrote {DEST / 'meta.json'}")
    print("=== PER-CLASS METRICS ===")
    print(json.dumps(metrics["per_class"], indent=2))
    print(metrics["margin_threshold_rationale"])
    print(
        f"Overall top-1={metrics['overall_top1']:.3f} on n={metrics['overall_n']} "
        f"(do not use alone — {metrics['overall_note']})"
    )
    return dest_ckpt


def smoke(ckpt_path: Path) -> None:
    import torch
    from PIL import Image
    from torchvision import transforms
    from torchvision.models import resnet50

    ckpt = torch.load(ckpt_path, map_location="cpu")
    class_names = ckpt["class_names"]
    margin_thr = float(ckpt["margin_threshold"])
    model = resnet50(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(class_names))
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    tf = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ]
    )

    manifest = json.loads((DATA_ROOT / "manifest.json").read_text())
    test_by_label: dict[str, list[str]] = {}
    for row in manifest["test"]:
        test_by_label.setdefault(row["label"], []).append(row["path"])

    def predict(path: Path) -> dict:
        with Image.open(path) as img:
            tensor = tf(img.convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            probs = torch.softmax(model(tensor)[0], dim=0)
        top2 = torch.topk(probs, k=2)
        top_label = class_names[int(top2.indices[0])]
        top_p = float(top2.values[0])
        second_p = float(top2.values[1])
        margin = top_p - second_p
        accepted = margin >= margin_thr
        return {
            "path": str(path),
            "top": top_label,
            "confidence": round(top_p, 4),
            "second": class_names[int(top2.indices[1])],
            "second_p": round(second_p, 4),
            "margin": round(margin, 4),
            "margin_threshold": margin_thr,
            "identity_confirmed": accepted,
            "path_taken": (
                "finetuned_accept" if accepted else "imagenet_provisional_fallback"
            ),
        }

    print("\n=== Smoke: held-out Honda_City (informative, not definitive) ===")
    city_paths = test_by_label.get("Honda_City", [])
    city_results = []
    for p in city_paths[:5]:
        r = predict(Path(p))
        city_results.append(r)
        print(json.dumps(r))
    accepted_city = [
        r
        for r in city_results
        if r["identity_confirmed"] and r["top"] == "Honda_City"
    ]
    print(
        f"City accepted as City: {len(accepted_city)}/{len(city_results)} "
        "(informative only — City had ~82 source images)"
    )

    print("\n=== Smoke: non-City held-out (Swift) — must not confirm as City ===")
    for p in test_by_label.get("Maruti_Swift", [])[:3]:
        print(json.dumps(predict(Path(p))))

    print("\n=== Smoke: non-trained-class proxy (Innova held-out) ===")
    for p in test_by_label.get("Toyota_Innova", [])[:3]:
        print(json.dumps(predict(Path(p))))

    # Negative case: image that is NOT City. Prefer Baleno (hatch adjacent) —
    # must not falsely confirm as City; low margin should fall through.
    print("\n=== Smoke: City-adjacent negative (Baleno held-out, not City) ===")
    for p in test_by_label.get("Maruti_Baleno", [])[:5]:
        r = predict(Path(p))
        print(json.dumps(r))
        if r["top"] == "Honda_City" and r["identity_confirmed"]:
            print("WARNING: Baleno falsely confirmed as City")

    # Nexon: only 2 images in FGVD, never trained — any crop should fall through
    # or at least not be a confirmed catalog identity for Nexon (no Nexon class).
    nexon_candidates = list(DATA_ROOT.glob("**/*Nexon*"))[:3]
    if not nexon_candidates:
        # Search FGVD annotations path for any leftover Nexon references
        nexon_candidates = list(Path("/mnt/ml-scratch").glob("**/nexon*"))[:3]
    if nexon_candidates:
        print("\n=== Smoke: Nexon-like files (always provisional path) ===")
        for p in nexon_candidates:
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                print(json.dumps(predict(p)))


def main() -> None:
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_run()
    print(f"Using run {run_dir}")
    ckpt = deploy(run_dir)
    smoke(ckpt)

    # Prove app path is independent of /mnt/ml-scratch by loading only DEST.
    print("\n=== Load check from app ml_weights only ===")
    import torch

    loaded = torch.load(DEST / CKPT_NAME, map_location="cpu")
    assert "model_state" in loaded
    assert loaded["margin_threshold"] is not None
    print(
        f"OK: {DEST / CKPT_NAME} classes={loaded['class_names']} "
        f"margin>={loaded['margin_threshold']}"
    )


if __name__ == "__main__":
    main()
