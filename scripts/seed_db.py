#!/usr/bin/env python3
"""Entry point for seeding the database. Run from repo root:

    python scripts/seed_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.seed import run_seed  # noqa: E402


if __name__ == "__main__":
    run_seed()
