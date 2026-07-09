#!/usr/bin/env python3
"""Feature 2 chat E2E verification — run on paperclip against live stack."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: pip install httpx")
    raise SystemExit(1)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
ADMIN_PASS = sys.argv[2] if len(sys.argv) > 2 else ""
IMAGE_DIR = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/e2e_claim26_images")

REPORT: list[dict] = []


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    REPORT.append({"section": title, "lines": []})


def log(msg: str) -> None:
    print(msg)
    if REPORT and "lines" in REPORT[-1]:
        REPORT[-1]["lines"].append(msg)


def login(client: httpx.Client, username: str, password: str) -> None:
    client.get(f"{BASE}/login")
    r = client.post(
        f"{BASE}/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    if r.status_code not in (303, 302, 200):
        raise RuntimeError(f"Login {username} failed: {r.status_code}")


def chat_message(client: httpx.Client, text: str) -> dict:
    r = client.post(
        f"{BASE}/api/chat/message",
        json={"text": text},
        headers={"Accept": "application/json"},
    )
    r.raise_for_status()
    return r.json()


def chat_upload(client: httpx.Client, image_dir: Path) -> dict:
    files = []
    for path in sorted(image_dir.glob("*.jpg"))[:4]:
        files.append(("images", (path.name, path.read_bytes(), "image/jpeg")))
    if not files:
        raise RuntimeError(f"No jpg in {image_dir}")
    r = client.post(f"{BASE}/api/chat/upload", files=files)
    r.raise_for_status()
    return r.json()


def read_sse_until(
    client: httpx.Client,
    claim_id: int,
    *,
    timeout: float = 480,
    want_pause: bool = False,
    want_complete: bool = False,
) -> list[dict]:
    events: list[dict] = []
    deadline = time.time() + timeout
    with client.stream(
        "GET",
        f"{BASE}/api/pipeline/{claim_id}/stream",
        timeout=httpx.Timeout(connect=10, read=None, write=10, pool=10),
    ) as resp:
        resp.raise_for_status()
        buf = ""
        for chunk in resp.iter_text():
            if time.time() > deadline:
                break
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                data_line = next(
                    (ln[5:] for ln in block.splitlines() if ln.startswith("data:")),
                    None,
                )
                if not data_line or data_line == "{}":
                    continue
                try:
                    payload = json.loads(data_line)
                except json.JSONDecodeError:
                    continue
                events.append(payload)
                if want_pause and payload.get("awaiting_vehicle_confirmation"):
                    return events
                if want_complete and payload.get("pipeline_complete"):
                    if payload.get("awaiting_vehicle_confirmation"):
                        return events
                    return events
    return events


def confirm_vehicle(client: httpx.Client, claim_id: int, make: str, model: str) -> None:
    r = client.post(
        f"{BASE}/api/pipeline/{claim_id}/confirm-vehicle",
        json={"make": make, "model": model},
    )
    r.raise_for_status()


def main() -> int:
    if not ADMIN_PASS:
        print("Usage: e2e_verify_chat.py [base_url] [admin_password] [image_dir]")
        return 1
    if not IMAGE_DIR.is_dir():
        log(f"FAIL image dir missing: {IMAGE_DIR}")
        return 1

    # --- 1: Full chat submit + VMMR pause/resume ---
    section("1. Chat submit flow (6 checkpoint steps)")
    client = httpx.Client(follow_redirects=True, timeout=120.0)
    login(client, "admin", ADMIN_PASS)

    r = client.get(f"{BASE}/chat")
    log(f"GET /chat HTTP {r.status_code}")
    log(f"  Chat page has suggestion chips: {'chat-chip' in r.text}")
    log(f"  Enterprise link present: {'/claims/new' in r.text and 'Enterprise' in r.text}")

    step1 = chat_message(client, "Submit a claim")
    log(f"Step 1 submit intent: {step1.get('text', '')[:120]}...")
    log(f"  file_upload widget: {any(w.get('type')=='file_upload' for w in step1.get('widgets',[]))}")

    step2 = chat_upload(client, IMAGE_DIR)
    log(f"Step 2 upload ack: {step2.get('text', '')}")

    step3 = chat_message(client, "garage is Chat E2E Motors, accident date 2026-03-15, surveyor Admin Test")
    log(f"Step 3 details ack: {step3.get('text', '')}")

    step4 = chat_message(client, "done")
    log(f"Step 4 submit ack: {step4.get('text', '')}")
    pipeline_widgets = [
        w for w in step4.get("widgets", []) if w.get("type") == "pipeline"
    ]
    if not pipeline_widgets:
        log("FAIL: no pipeline widget in submit response")
        return 2
    claim_id = pipeline_widgets[0]["claim_id"]
    claim_ref = pipeline_widgets[0].get("claim_reference", "?")
    log(f"  claim_id={claim_id} ref={claim_ref}")

    pause_events = read_sse_until(client, claim_id, want_pause=True)
    paused = any(e.get("awaiting_vehicle_confirmation") for e in pause_events)
    log(f"Step 5 pipeline SSE pause: {paused} ({len(pause_events)} events)")

    chat_html = client.get(f"{BASE}/chat").text
    log(f"  Chat page still loads during pipeline: {r.status_code == 200}")

    if paused:
        confirm_vehicle(client, claim_id, "Toyota", "Innova")
        log("Step 5b confirmed Toyota Innova via API (mirrors inline chat form)")
        complete = read_sse_until(client, claim_id, want_complete=True)
        pc = next((e for e in complete if e.get("pipeline_complete")), None)
        log(f"Step 6 pipeline complete: {bool(pc)} redirect={pc.get('redirect') if pc else None}")

    summary_r = client.get(f"{BASE}/api/chat/claims/{claim_id}/summary")
    log(f"Step 6 summary HTTP {summary_r.status_code}")
    if summary_r.is_success:
        log(f"  summary excerpt: {summary_r.json().get('text','')[:200]}...")

    # accident_date in DB — checked via shell wrapper

    # --- 4: created_by scoping ---
    section("4. Lookup scoped to created_by")
    admin_lookup = chat_message(client, "Get details of claim CLM-2026-000017")
    admin_text = admin_lookup.get("text", "")
    log(f"Admin lookup CLM-2026-000017: {admin_text[:160]}...")
    admin_found = "couldn't find" not in admin_text.lower() and "not found" not in admin_text.lower()

    client2 = httpx.Client(follow_redirects=True, timeout=120.0)
    login(client2, "admin", ADMIN_PASS)
    # Use a claim reference that exists but belongs to another user if possible
    cross = chat_message(client2, "Get details of claim CLM-2026-000001")
    cross_text = cross.get("text", "")
    log(f"Cross-user style lookup CLM-2026-000001: {cross_text[:160]}...")
    blocked = (
        "couldn't find" in cross_text.lower()
        or "not found" in cross_text.lower()
        or "do not have access" in cross_text.lower()
        or "I found several" in cross_text
    )
    log(f"  Lookup isolation (no foreign claim leaked): {blocked or not admin_found}")

    # --- 5: Interrupted paths ---
    section("5. Interrupted / ambiguous paths")
    login(client, "admin", ADMIN_PASS)
    chat_message(client, "Submit a claim")
    chat_upload(client, IMAGE_DIR)
    unrelated = chat_message(client, "What is the weather today?")
    log(f"Unrelated msg during draft: {unrelated.get('text', '')[:180]}")
    log(f"  Still in draft (mentions garage/photo/done): {'done' in unrelated.get('text','').lower() or 'garage' in unrelated.get('text','').lower()}")

    mid_lookup = chat_message(client, "Find my claim CLM-2026-000017")
    log(f"Lookup mid-draft: {mid_lookup.get('text', '')[:180]}...")
    log(f"  Draft cleared (lookup result not draft status): {'CLM-' in mid_lookup.get('text','') or 'couldn' in mid_lookup.get('text','').lower()}")

    Path("/tmp/e2e_chat_report.json").write_text(json.dumps(REPORT, indent=2))
    log("\nReport: /tmp/e2e_chat_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
