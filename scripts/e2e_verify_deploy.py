#!/usr/bin/env python3
"""End-to-end verification for Parts A/B/C on deployed AI Tribe."""

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
    sys.exit(1)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
ADMIN_USER = "admin"
ADMIN_PASS = sys.argv[2] if len(sys.argv) > 2 else ""
IMAGE_DIR = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/e2e_claim26_images")
IMAGE_DIR_B = Path(sys.argv[4]) if len(sys.argv) > 4 else IMAGE_DIR

REPORT: list[str] = []


def log(msg: str) -> None:
    print(msg)
    REPORT.append(msg)


def login(client: httpx.Client) -> None:
    r = client.get(f"{BASE}/login")
    r.raise_for_status()
    r = client.post(
        f"{BASE}/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        follow_redirects=False,
    )
    if r.status_code not in (303, 302, 200):
        raise RuntimeError(f"Login failed: {r.status_code} {r.text[:200]}")


def submit_claim(client: httpx.Client, tag: str, image_dir: Path | None = None) -> dict:
    src = image_dir or IMAGE_DIR
    files = []
    for path in sorted(src.glob("*.jpg")):
        files.append(
            ("images", (path.name, path.read_bytes(), "image/jpeg")),
        )
    if not files:
        raise RuntimeError(f"No images in {src}")

    data = {
        "garage_name": f"E2E Garage {tag}",
        "surveyor_name": f"E2E Surveyor {tag}",
    }
    r = client.post(f"{BASE}/claims", data=data, files=files)
    r.raise_for_status()
    return r.json()


def read_sse_until(
    client: httpx.Client,
    claim_id: int,
    *,
    timeout: float = 300,
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
                    if payload.get("redirect") or not payload.get("halted"):
                        return events
                    if payload.get("halted") and not payload.get(
                        "awaiting_vehicle_confirmation"
                    ):
                        return events
    return events


def fetch_processing_bootstrap(client: httpx.Client, claim_id: int) -> dict:
    r = client.get(f"{BASE}/claims/{claim_id}/processing")
    r.raise_for_status()
    m = re.search(
        r'id="pipeline-bootstrap">(\{.*?\})</script>',
        r.text,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError("pipeline-bootstrap not found")
    return json.loads(m.group(1))


def confirm_vehicle(client: httpx.Client, claim_id: int, make: str, model: str) -> dict:
    r = client.post(
        f"{BASE}/api/pipeline/{claim_id}/confirm-vehicle",
        json={"make": make, "model": model},
    )
    r.raise_for_status()
    return r.json()


def fetch_estimate_html(client: httpx.Client, claim_id: int) -> str:
    r = client.get(f"{BASE}/claims/{claim_id}/estimate")
    r.raise_for_status()
    return r.text


def post_manual_prices(
    client: httpx.Client, claim_id: int, prices: list[dict]
) -> dict:
    r = client.post(
        f"{BASE}/api/claims/{claim_id}/estimate/prices",
        json={"prices": prices},
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    if not ADMIN_PASS:
        print("Usage: e2e_verify_deploy.py [base_url] [admin_password] [image_dir]")
        return 1
    if not IMAGE_DIR.is_dir():
        print(f"Image dir missing: {IMAGE_DIR}")
        return 1

    client = httpx.Client(follow_redirects=True, timeout=120.0)
    login(client)
    log(f"OK login as {ADMIN_USER} at {BASE}")

    # --- Part C: check bootstrap on Part A claim shortly after submit ---
    claim = submit_claim(client, "part-a")
    claim_id = claim["claim_id"]
    log(f"Part A submitted claim {claim_id} ({claim['claim_reference']})")

    time.sleep(1.5)
    boot_early = fetch_processing_bootstrap(client, claim_id)
    early_stages = boot_early.get("stages") or []
    log(f"Part C bootstrap stages count (early): {len(early_stages)}")
    if early_stages:
        log(f"  WARN early stages not empty: {[s.get('key') for s in early_stages]}")
    else:
        log("  OK bootstrap starts with empty stages list (replayed from events only)")

    # --- Part A: pause + resume (same claim) ---
    pause_events = read_sse_until(
        client, claim_id, timeout=420, want_pause=True
    )
    pause_hit = any(e.get("awaiting_vehicle_confirmation") for e in pause_events)
    stage_keys = [e.get("stage_key") for e in pause_events if e.get("stage_key")]
    log(f"Part A SSE events: {len(pause_events)}, stage_keys={stage_keys}")
    log(f"Part A paused awaiting confirmation: {pause_hit}")

    boot_paused = fetch_processing_bootstrap(client, claim_id)
    paused_stages = boot_paused.get("stages") or []
    log(f"Part A stages after pause (from events replay): {len(paused_stages)}")
    log(f"  stage keys: {[s.get('key') for s in paused_stages]}")
    log(f"  claimStatus: {boot_paused.get('claimStatus')}")

    proc_html = client.get(f"{BASE}/claims/{claim_id}/processing").text
    inline_form = "vehicle_confirmation" in proc_html and 'id="confirm_make"' in proc_html
    separate_banner = 'x-show="awaitingVehicleConfirmation"' in proc_html and "Confirm vehicle" in proc_html
    log(f"Part A inline confirm form in page: {inline_form}")
    log(f"Part A separate Confirm vehicle banner removed: {not separate_banner}")

    if not pause_hit:
        log("FAIL Part A: pipeline did not pause")
        return 2

    confirm_vehicle(client, claim_id, "Toyota", "Innova")
    log("Part A confirmed Toyota Innova")

    complete_events = read_sse_until(
        client, claim_id, timeout=420, want_complete=True
    )
    redirect = next(
        (e.get("redirect") for e in complete_events if e.get("redirect")),
        None,
    )
    log(f"Part A resume SSE tail: redirect={redirect}")
    log(f"  resumed stage keys: {[e.get('stage_key') for e in complete_events if e.get('stage_key')]}")

    # DB checks via subprocess would need psql - done in shell wrapper
    log(f"Part A claim_id for DB checks: {claim_id}")

    # --- Part B: unpriced catalog lines ---
    claim_b = submit_claim(client, "part-b", IMAGE_DIR_B)
    bid = claim_b["claim_id"]
    log(f"Part B submitted claim {bid} (uses IMAGE_DIR_B env or second dir via argv[4])")
    read_sse_until(client, bid, timeout=420, want_pause=True)
    confirm_vehicle(client, bid, "E2ETest", "NoCatalogVehicle")
    read_sse_until(client, bid, timeout=420, want_complete=True)

    est_html = fetch_estimate_html(client, bid)
    unpriced = "Price not available" in est_html or 'placeholder="Enter ₹"' in est_html
    locked_total = "Enter prices below" in est_html or "Total pending manual prices" in est_html
    log(f"Part B unpriced line UI present: {unpriced}")
    log(f"Part B grand total locked: {locked_total}")

    # Extract first unpriced part from estimate page table - use API rebuild
    # Post manual price for Front Bumper dent if present
    prices = [
        {"part_name": "Front Bumper", "damage_type": "dent", "unit_price": 8500.0},
        {"part_name": "Windshield", "damage_type": "glass_shatter", "unit_price": 12000.0},
        {"part_name": "Headlamp", "damage_type": "lamp_broken", "unit_price": 4500.0},
    ]
    try:
        result = post_manual_prices(client, bid, prices)
        log(f"Part B manual price API ok={result.get('ok')} pricing_complete={result.get('pricing_complete')}")
        log(f"  grand_total after manual: {result.get('grand_total')}")
        manual_items = [
            i for i in (result.get("line_items") or []) if i.get("price_source") == "manual"
        ]
        log(f"  manual line items: {len(manual_items)}")
    except httpx.HTTPStatusError as exc:
        log(f"Part B manual price API error: {exc.response.status_code} {exc.response.text[:300]}")

    est_after = fetch_estimate_html(client, bid)
    manual_label = "(manual)" in est_after
    finalized = "₹" in est_after and "Enter prices below" not in est_after
    log(f"Part B (manual) label in HTML: {manual_label}")
    log(f"Part B estimate shows finalized total: {finalized}")
    log(f"Part B claim_id for DB checks: {bid}")

    Path("/tmp/e2e_report.json").write_text(json.dumps({"report": REPORT}, indent=2))
    log("Report written to /tmp/e2e_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
