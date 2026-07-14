#!/usr/bin/env python3
"""Daily job: email API token expiry reminders (7d / 1d).

Cron example (paperclip):
  15 6 * * * docker exec ai_tribe_app_ml python /app/scripts/api_marketplace_token_reminders.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.api_marketplace.tokens import process_token_expiry_reminders  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        result = process_token_expiry_reminders(db)
        print(f"token_reminders {result}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
