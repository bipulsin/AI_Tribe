#!/usr/bin/env python3
"""Step 3 verification for chat NLU — paraphrases, off-topic, ambiguous, draft gates."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure backend imports work when run from repo root or container.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("CHAT_NLU_ROOT", "/mnt/ml-scratch/chat_nlu")
os.environ.setdefault("CHAT_NLU_ENABLED", "true")


CASES = [
    # Submit paraphrases
    ("submit paraphrases", "I need to file a motor claim please", "submit_claim"),
    ("submit paraphrases", "upload damage photos for a new claim", "submit_claim"),
    ("submit paraphrases", "submit a new claim with image", "submit_claim"),
    ("submit paraphrases", "register vehicle damage claim", "submit_claim"),
    # Lookup paraphrases
    ("lookup paraphrases", "what is the status of my claim", "lookup_claim"),
    ("lookup paraphrases", "show me claim CLM-2026-000026", "lookup_claim"),
    ("lookup paraphrases", "find claims from Pune", "lookup_claim"),
    ("lookup paraphrases", "look up claim number 26", "lookup_claim"),
    # Off-topic
    ("off-topic", "what's the weather in Mumbai today", "off_topic"),
    ("off-topic", "tell me a joke", "off_topic"),
    ("off-topic", "write me a python function", "off_topic"),
    # Ambiguous / clarify
    ("ambiguous", "claim", "clarify"),
    ("ambiguous", "maybe something about insurance", "clarify"),
    # Draft gate (city must stay submit)
    ("draft gate", "Thane", "submit_claim", True),
    ("draft gate", "Pune", "submit_claim", True),
    ("draft gate", "find my claim", "lookup_claim", True),
]


def main() -> int:
    from app.services.chat.nlu.service import classify_message
    from app.core.config import get_settings

    settings = get_settings()
    print(f"CHAT_NLU_ENABLED={settings.chat_nlu_enabled}")
    print(f"CHAT_NLU_ROOT={settings.chat_nlu_path}")
    print(f"root exists={settings.chat_nlu_path.exists()}")

    # Warm-up
    t0 = time.time()
    classify_message("submit a claim")
    warm = time.time() - t0
    print(f"warm-up classify: {warm:.2f}s")

    by_cat: dict[str, list[bool]] = {}
    rows = []
    for item in CASES:
        if len(item) == 4:
            cat, text, expect, draft = item
        else:
            cat, text, expect = item
            draft = False
        t1 = time.time()
        result = classify_message(text, draft_active=draft)
        dt = time.time() - t1
        ok = result.intent == expect
        # Ambiguous category: clarify OR general is acceptable honesty.
        if cat == "ambiguous" and result.intent in {"clarify", "general"}:
            ok = True
        # Off-topic: allow clarify if model unsure rather than wrong routing.
        if cat == "off-topic" and result.intent in {"off_topic", "clarify"}:
            ok = True
        by_cat.setdefault(cat, []).append(ok)
        rows.append((ok, cat, text, expect, result.intent, result.source, result.confidence, dt))

    print("\nResults:")
    for ok, cat, text, expect, got, source, conf, dt in rows:
        mark = "OK" if ok else "FAIL"
        print(
            f"  [{mark}] {cat:18} expect={expect:13} got={got:13} "
            f"src={source:10} conf={conf:.2f} {dt*1000:.0f}ms  | {text}"
        )

    print("\nBy category:")
    all_ok = True
    for cat, flags in by_cat.items():
        n_ok = sum(flags)
        print(f"  {cat}: {n_ok}/{len(flags)}")
        if n_ok < len(flags):
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
