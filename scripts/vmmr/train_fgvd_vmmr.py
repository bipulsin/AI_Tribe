#!/usr/bin/env python3
"""Fine-tune ResNet50 on FGVD 8-class India catalog subset."""

from __future__ import annotations

import json  # noqa: I001
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms
from torchvision.models import ResNet50_Weights, resnet50

DATA_ROOT = Path("/mnt/ml-scratch/vmmr_data")
RUN_ROOT = Path("/mnt/ml-scratch/vmmr_runs")
MANIFEST = DATA_ROOT / "manifest.json"
SEED = 42
BATCH_SIZE = 16
NUM_WORKERS = 2
PHASE1_EPOCHS = 5
PHASE2_EPOCHS = 6
LR_HEAD = 1e-3
LR_FINETUNE = 1e-4
DEVICE = "cpu"

# Stronger augmentation for minority / under-100-image classes
MINORITY = {
    "Renault_Kwid",
    "Honda_City",
    "Hyundai_Creta",
    "Maruti_Baleno",
    "Mahindra_XUV500",
}


class CropDataset(Dataset):
    def __init__(self, rows, class_to_idx, train: bool):
        self.rows = rows
        self.class_to_idx = class_to_idx
        self.train = train
        self.base_tf = transforms.Compose(
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
        self.mild_aug = transforms.Compose(
            [
                transforms.Resize(256),
                transforms.RandomResizedCrop(224, scale=(0.7, 1.0)),
                transforms.RandomHorizontalFlip(),
                transforms.ColorJitter(0.15, 0.15, 0.1, 0.05),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
            ]
        )
        self.strong_aug = transforms.Compose(
            [
                transforms.Resize(256),
                transforms.RandomResizedCrop(224, scale=(0.55, 1.0)),
                transforms.RandomHorizontalFlip(),
                transforms.RandomRotation(15),
                transforms.ColorJitter(0.3, 0.3, 0.2, 0.1),
                transforms.RandomAffine(degrees=0, translate=(0.08, 0.08)),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
            ]
        )

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        label = row["label"]
        img = Image.open(row["path"]).convert("RGB")
        if not self.train:
            tensor = self.base_tf(img)
        elif label in MINORITY:
            tensor = self.strong_aug(img)
        else:
            tensor = self.mild_aug(img)
        return tensor, self.class_to_idx[label], label


# Source-image totals under this count have held-out sets too small to trust.
MIN_RELIABLE_SOURCE_IMAGES = 100


def evaluate(model, loader, class_names, device, source_totals: dict[str, int] | None = None):
    model.eval()
    correct_top1 = Counter()
    correct_top5 = Counter()
    total = Counter()
    margins_by_class = defaultdict(list)
    correct_margins_by_class = defaultdict(list)
    all_margins = []
    correct_margins = []

    with torch.no_grad():
        for images, targets, labels in loader:
            images = images.to(device)
            targets = targets.to(device)
            logits = model(images)
            probs = torch.softmax(logits, dim=1)
            topk = torch.topk(probs, k=min(5, probs.size(1)), dim=1)
            pred1 = topk.indices[:, 0]
            # margin top1 - top2
            if probs.size(1) > 1:
                margins = (topk.values[:, 0] - topk.values[:, 1]).cpu().tolist()
            else:
                margins = topk.values[:, 0].cpu().tolist()

            for i, label in enumerate(labels):
                total[label] += 1
                margin = margins[i]
                margins_by_class[label].append(margin)
                all_margins.append(margin)
                is_correct = pred1[i].item() == targets[i].item()
                if is_correct:
                    correct_top1[label] += 1
                    correct_margins_by_class[label].append(margin)
                    correct_margins.append(margin)
                if targets[i].item() in topk.indices[i].tolist():
                    correct_top5[label] += 1

    source_totals = source_totals or {}
    per_class = {}
    for name in class_names:
        n = total[name]
        n_source = source_totals.get(name, n)
        reliable = n_source >= MIN_RELIABLE_SOURCE_IMAGES and n >= 20
        per_class[name] = {
            "n_source": n_source,
            "n_test": n,
            "top1_acc": (correct_top1[name] / n) if n else None,
            "top5_acc": (correct_top5[name] / n) if n else None,
            "margin_mean": (
                sum(margins_by_class[name]) / len(margins_by_class[name])
                if margins_by_class[name]
                else None
            ),
            "margin_p25": _percentile(margins_by_class[name], 25),
            "margin_p50": _percentile(margins_by_class[name], 50),
            "margin_p75": _percentile(margins_by_class[name], 75),
            "correct_margin_mean": (
                sum(correct_margins_by_class[name]) / len(correct_margins_by_class[name])
                if correct_margins_by_class[name]
                else None
            ),
            "correct_margin_p25": _percentile(correct_margins_by_class[name], 25),
            "correct_margin_p50": _percentile(correct_margins_by_class[name], 50),
            "statistically_meaningful": reliable,
            "reliability_note": (
                None
                if reliable
                else (
                    f"Not statistically meaningful: {n_source} source images, "
                    f"{n} held-out test images. Report the number but do not "
                    "treat accuracy as reliable (especially Kwid-scale sets)."
                )
            ),
        }

    overall_n = sum(total.values())
    overall_top1 = sum(correct_top1.values()) / overall_n if overall_n else 0.0
    overall_top5 = sum(correct_top5.values()) / overall_n if overall_n else 0.0
    return {
        "overall_top1": overall_top1,
        "overall_top5": overall_top5,
        "overall_n": overall_n,
        "overall_note": (
            "Overall accuracy is dominated by Swift/Innova; always read per-class "
            "numbers. Classes with <100 source images are not reliable."
        ),
        "per_class": per_class,
        "all_margins": all_margins,
        "margin_mean": sum(all_margins) / len(all_margins) if all_margins else 0.0,
        "margin_p25": _percentile(all_margins, 25),
        "margin_p50": _percentile(all_margins, 50),
        "margin_p75": _percentile(all_margins, 75),
        "correct_margin_mean": (
            sum(correct_margins) / len(correct_margins) if correct_margins else 0.0
        ),
        "correct_margin_p25": _percentile(correct_margins, 25),
        "correct_margin_p50": _percentile(correct_margins, 50),
        "correct_margin_p75": _percentile(correct_margins, 75),
    }


def _percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    idx = int(round((q / 100) * (len(s) - 1)))
    return s[idx]


def train_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0.0
    n = 0
    for images, targets, _labels in loader:
        images = images.to(device)
        targets = targets.to(device)
        optimizer.zero_grad()
        logits = model(images)
        loss = criterion(logits, targets)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * images.size(0)
        n += images.size(0)
    return total_loss / max(n, 1)


def main() -> None:
    random.seed(SEED)
    torch.manual_seed(SEED)

    manifest = json.loads(MANIFEST.read_text())
    class_names = list(manifest["classes"].keys())
    # preserve CLASS_ORDER from prepare script
    class_names = [
        "Maruti_Swift",
        "Maruti_Baleno",
        "Hyundai_i20",
        "Hyundai_Creta",
        "Honda_City",
        "Toyota_Innova",
        "Renault_Kwid",
        "Mahindra_XUV500",
    ]
    class_to_idx = {n: i for i, n in enumerate(class_names)}

    train_rows = manifest["train"]
    test_rows = manifest["test"]
    print("Train counts:", Counter(r["label"] for r in train_rows))
    print("Test counts:", Counter(r["label"] for r in test_rows))

    train_ds = CropDataset(train_rows, class_to_idx, train=True)
    test_ds = CropDataset(test_rows, class_to_idx, train=False)

    # Inverse-frequency sample weights for oversampling minorities
    train_label_counts = Counter(r["label"] for r in train_rows)
    sample_weights = [
        1.0 / train_label_counts[r["label"]] for r in train_rows
    ]
    sampler = WeightedRandomSampler(
        weights=sample_weights,
        num_samples=len(sample_weights),
        replacement=True,
    )
    train_loader = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        sampler=sampler,
        num_workers=NUM_WORKERS,
    )
    test_loader = DataLoader(
        test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS
    )

    # Class-weighted CE
    counts = torch.tensor(
        [train_label_counts[n] for n in class_names], dtype=torch.float
    )
    class_weights = (1.0 / counts)
    class_weights = class_weights / class_weights.sum() * len(class_names)
    criterion = nn.CrossEntropyLoss(weight=class_weights)

    model = resnet50(weights=ResNet50_Weights.DEFAULT)
    model.fc = nn.Linear(model.fc.in_features, len(class_names))
    model.to(DEVICE)

    # Phase 1: freeze backbone
    for name, param in model.named_parameters():
        param.requires_grad = name.startswith("fc.")
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=LR_HEAD
    )
    print("=== Phase 1: head only ===")
    for epoch in range(1, PHASE1_EPOCHS + 1):
        loss = train_epoch(model, train_loader, criterion, optimizer, DEVICE)
        print(f"  epoch {epoch}/{PHASE1_EPOCHS} loss={loss:.4f}")

    # Phase 2: unfreeze layer4 + fc
    for name, param in model.named_parameters():
        param.requires_grad = name.startswith("fc.") or name.startswith("layer4.")
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=LR_FINETUNE
    )
    print("=== Phase 2: layer4 + head ===")
    for epoch in range(1, PHASE2_EPOCHS + 1):
        loss = train_epoch(model, train_loader, criterion, optimizer, DEVICE)
        print(f"  epoch {epoch}/{PHASE2_EPOCHS} loss={loss:.4f}")

    source_totals = {
        name: manifest["classes"][name]["total"] for name in class_names
    }
    metrics = evaluate(
        model, test_loader, class_names, DEVICE, source_totals=source_totals
    )
    # Margin gate: start at 0.4; tune from held-out margins on *correct* predictions.
    # Prefer keeping 0.4 when correct-margin p25 is at or above it; otherwise lower
    # toward correct-margin p25 (floor 0.25) so we do not reject every minority hit.
    suggested = 0.4
    correct_p25 = metrics.get("correct_margin_p25")
    correct_p50 = metrics.get("correct_margin_p50")
    if correct_p25 is not None and correct_p25 < 0.4:
        suggested = max(0.25, round(correct_p25, 2))
    elif correct_p50 is not None and correct_p50 < 0.35:
        suggested = max(0.25, round(correct_p50, 2))
    metrics["margin_threshold_selected"] = suggested
    metrics["margin_threshold_rationale"] = (
        f"Started at 0.4; correct-margin p25={correct_p25}, p50={correct_p50}; "
        f"selected {suggested}."
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = run_dir / "vmmr_resnet50_fgvd8.pt"
    torch.save(
        {
            "model_state": model.state_dict(),
            "class_names": class_names,
            "margin_threshold": suggested,
            "arch": "resnet50",
            "dataset_version": "FGVD_IDD_v1_catalog8",
        },
        ckpt_path,
    )
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (run_dir / "manifest_classes.json").write_text(
        json.dumps(manifest["classes"], indent=2)
    )

    # Also write deployable copy path hint
    deploy_hint = {
        "checkpoint": str(ckpt_path),
        "class_names": class_names,
        "margin_threshold": suggested,
        "excluded_catalog_models": ["Tata_Nexon", "Mahindra_XUV700", "Kia_Seltos"],
        "trained_catalog_models": class_names,
        "forced_low_confidence": ["Mahindra_XUV500"],
    }
    (run_dir / "deploy.json").write_text(json.dumps(deploy_hint, indent=2))

    print("=== METRICS ===")
    print(json.dumps(metrics, indent=2))
    print(f"Checkpoint: {ckpt_path}")
    print(f"Selected margin threshold: {suggested}")


if __name__ == "__main__":
    main()
