#!/usr/bin/env python3
"""Download chat NLU models onto /mnt/ml-scratch (never root disk).

Usage (on paperclip host or inside ai_tribe_app_ml with scratch mounted):

  python scripts/chat_nlu/download_models.py
  python scripts/chat_nlu/download_models.py --root /mnt/ml-scratch/chat_nlu
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _df_avail_gb(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
        return usage.free / (1024**3)
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("CHAT_NLU_ROOT", "/mnt/ml-scratch/chat_nlu")),
    )
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    args = parser.parse_args()
    root: Path = args.root

    scratch = Path("/mnt/ml-scratch")
    if not str(root).startswith(str(scratch)):
        print(f"REFUSING: root must be under {scratch}, got {root}", file=sys.stderr)
        return 2

    free = _df_avail_gb(scratch if scratch.exists() else Path("/"))
    print(f"Free space on target filesystem: {free:.1f} GiB" if free is not None else "Free space: unknown")
    if free is not None and free < args.min_free_gb:
        print(f"STOP: need at least {args.min_free_gb} GiB free", file=sys.stderr)
        return 3

    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    hf_cache = root / "hf_download_cache"
    hf_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_cache)
    os.environ["TRANSFORMERS_CACHE"] = str(hf_cache / "transformers")
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(hf_cache / "sentence_transformers")

    mini_dest = models / "all-MiniLM-L6-v2"
    if (mini_dest / "config.json").is_file():
        print(f"MiniLM already present: {mini_dest}")
    else:
        print("Downloading sentence-transformers/all-MiniLM-L6-v2 …")
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        model.save(str(mini_dest))
        print(f"Saved MiniLM → {mini_dest}")

    spacy_dest = models / "en_core_web_sm"
    if spacy_dest.is_dir() and (spacy_dest / "meta.json").is_file():
        print(f"spaCy already present: {spacy_dest}")
    else:
        print("Downloading spaCy en_core_web_sm wheel from GitHub releases …")
        import urllib.request
        import zipfile

        wheels = root / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        wheel_url = (
            "https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
        )
        wheel_path = wheels / "en_core_web_sm-3.8.0-py3-none-any.whl"
        if not wheel_path.is_file():
            urllib.request.urlretrieve(wheel_url, wheel_path)
        extract_dir = root / "_spacy_extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        with zipfile.ZipFile(wheel_path, "r") as zf:
            zf.extractall(extract_dir)
        candidates = list(extract_dir.glob("en_core_web_sm/en_core_web_sm-*"))
        if not candidates:
            print("ERROR: could not locate spaCy model dir in wheel", file=sys.stderr)
            return 5
        src = candidates[0]
        if spacy_dest.exists():
            shutil.rmtree(spacy_dest)
        shutil.copytree(src, spacy_dest)
        shutil.rmtree(extract_dir, ignore_errors=True)
        print(f"Copied spaCy model → {spacy_dest}")

    free_after = _df_avail_gb(scratch)
    print(
        f"Done. Free space now: {free_after:.1f} GiB"
        if free_after is not None
        else "Done."
    )
    du = subprocess.check_output(["du", "-sh", str(root)], text=True).strip()
    print(f"CHAT_NLU_ROOT size: {du}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
