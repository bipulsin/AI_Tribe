#!/usr/bin/env python3
"""Prepare ml-scratch layout for CarDD / VehiDE (lab NC research only).

All writes go under /mnt/ml-scratch — never root disk.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRATCH = Path(os.environ.get("DAMAGE_DATA_ROOT", "/mnt/ml-scratch"))
CARDD_ROOT = SCRATCH / "cardd"
VEHIDE_ROOT = SCRATCH / "vehide"
EVAL_ROOT = SCRATCH / "damage_eval"
ACK_PATH = SCRATCH / "damage_datasets" / "LICENSE_ACK.json"

KAGGLE_DATASET = "hendrichscullen/vehide-dataset-automatic-vehicle-damage-detection"


def _disk_report() -> str:
    usage = shutil.disk_usage(SCRATCH)
    gb_free = usage.free / (1024**3)
    return f"{SCRATCH}: {gb_free:.1f} GB free"


def _write_readme(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def ensure_layout() -> None:
    for root in (CARDD_ROOT, VEHIDE_ROOT, EVAL_ROOT, ACK_PATH.parent):
        (root / "raw").mkdir(parents=True, exist_ok=True)
        (root / "README.txt").touch(exist_ok=True)

    _write_readme(
        CARDD_ROOT / "README.txt",
        f"""CarDD scratch area (non-commercial research only)
See docs/DATASET_LICENSES.md

1. Complete the CarDD licensing form: https://cardd-ustc.github.io/
2. Extract the official zip under: {CARDD_ROOT / 'raw'}/
3. Optional code/model zoo:
   git clone https://github.com/CarDD-USTC/CarDD-USTC.github.io.git {CARDD_ROOT / 'code'}

Do NOT commit dataset files to git.
""",
    )

    _write_readme(
        VEHIDE_ROOT / "README.txt",
        f"""VehiDE scratch area (non-commercial research only)
See docs/DATASET_LICENSES.md

Preferred download (requires Kaggle API credentials on this VM):
  kaggle datasets download -d {KAGGLE_DATASET} -p {VEHIDE_ROOT / 'raw'} --unzip

Or manual download from Kaggle and unzip to {VEHIDE_ROOT / 'raw'}/
""",
    )

    if not ACK_PATH.exists():
        ACK_PATH.write_text(
            json.dumps(
                {
                    "purpose": "non_commercial_lab_research_only",
                    "datasets": ["CarDD", "VehiDE"],
                    "acknowledged": False,
                    "acknowledged_by": None,
                    "acknowledged_at": None,
                    "note": "Set acknowledged=true after reading docs/DATASET_LICENSES.md",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def try_kaggle_vehide() -> bool:
    ack = json.loads(ACK_PATH.read_text(encoding="utf-8"))
    if not ack.get("acknowledged"):
        print("SKIP Kaggle download: LICENSE_ACK.json not acknowledged.")
        print(f"Edit {ACK_PATH} and set acknowledged=true after license review.")
        return False

    dest = VEHIDE_ROOT / "raw"
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        print(f"VehiDE raw already populated under {dest}")
        return True

    kaggle_bin = shutil.which("kaggle")
    if not kaggle_bin:
        print("kaggle CLI not installed; VehiDE manual download required.")
        return False

    print(f"Downloading VehiDE via Kaggle to {dest} ...")
    subprocess.run(
        [kaggle_bin, "datasets", "download", "-d", KAGGLE_DATASET, "-p", str(dest), "--unzip"],
        check=False,
    )
    return any(dest.iterdir())


def main() -> int:
    print("=== prepare_damage_datasets ===")
    print(_disk_report())
    if not SCRATCH.exists():
        print(f"ERROR: scratch mount missing: {SCRATCH}", file=sys.stderr)
        return 1

    ensure_layout()
    print(f"Layout ready under {SCRATCH}")
    print(f"  CarDD:   {CARDD_ROOT}")
    print(f"  VehiDE:  {VEHIDE_ROOT}")
    print(f"  Eval:    {EVAL_ROOT}")
    print(f"  License: {ACK_PATH}")

    try_kaggle_vehide()

    manifest_script = Path(__file__).resolve().parent / "build_vehide_manifest.py"
    vehide_raw = VEHIDE_ROOT / "raw"
    if (vehide_raw / "0Train_via_annos.json").is_file() and manifest_script.is_file():
        print("Building VehiDE manifest.csv from VIA JSON ...")
        subprocess.run(
            [sys.executable, str(manifest_script), "--root", str(vehide_raw)],
            check=False,
        )

    print(_disk_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
