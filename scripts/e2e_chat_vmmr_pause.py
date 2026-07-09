#!/usr/bin/env python3
"""Chat submit + VMMR pause/resume on live stack."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS = os.environ.get("ADMIN_PASS") or (sys.argv[2] if len(sys.argv) > 2 else "")
IMG = Path(sys.argv[3] if len(sys.argv) > 3 else "/tmp/e2e_chat34")


def main() -> int:
    if not PASS:
        print("ADMIN_PASS required")
        return 1
    client = httpx.Client(follow_redirects=True, timeout=120)
    client.get(f"{BASE}/login")
    client.post(f"{BASE}/auth/login", data={"username": "admin", "password": PASS})

    def msg(text: str) -> dict:
        return client.post(f"{BASE}/api/chat/message", json={"text": text}).json()

    files = [
        ("images", (p.name, p.read_bytes(), "image/jpeg"))
        for p in sorted(IMG.glob("*.jpg"))[:4]
    ]
    print(f"images: {len(files)}")
    print("1:", msg("Submit a claim").get("text", "")[:90])
    print("2:", client.post(f"{BASE}/api/chat/upload", files=files).json().get("text", ""))
    print("3:", msg("garage is Chat VMMR Pause Test, accident date 2026-04-01").get("text", ""))
    submit = msg("done")
    print("4:", submit.get("text", ""))
    widgets = [w for w in submit.get("widgets", []) if w.get("type") == "pipeline"]
    if not widgets:
        print("FAIL: no pipeline widget")
        return 2
    claim_id = widgets[0]["claim_id"]
    print(f"claim_id={claim_id}")

    paused = False
    complete = False
    with client.stream("GET", f"{BASE}/api/pipeline/{claim_id}/stream") as resp:
        buf = ""
        deadline = time.time() + 480
        for chunk in resp.iter_text():
            if time.time() > deadline:
                break
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                line = next(
                    (ln[5:] for ln in block.splitlines() if ln.startswith("data:")),
                    None,
                )
                if not line or line == "{}":
                    continue
                payload = json.loads(line)
                if payload.get("stage_key"):
                    print(
                        f"  SSE {payload.get('stage_key')} {payload.get('status')}"
                    )
                if payload.get("awaiting_vehicle_confirmation"):
                    paused = True
                    print("PAUSED awaiting_vehicle_confirmation")
                    break
                if payload.get("pipeline_complete"):
                    complete = True
                    print(
                        "COMPLETE",
                        "halted=",
                        payload.get("halted"),
                        "awaiting=",
                        payload.get("awaiting_vehicle_confirmation"),
                    )
                    break
            if paused or complete:
                break

    if paused:
        r = client.post(
            f"{BASE}/api/pipeline/{claim_id}/confirm-vehicle",
            json={"make": "Toyota", "model": "Innova"},
        )
        print("confirm HTTP", r.status_code)
        with client.stream("GET", f"{BASE}/api/pipeline/{claim_id}/stream") as resp:
            deadline = time.time() + 480
            for chunk in resp.iter_text():
                if time.time() > deadline:
                    break
                if '"pipeline_complete": true' in chunk or '"pipeline_complete":true' in chunk:
                    if '"awaiting_vehicle_confirmation": true' not in chunk:
                        print("RESUME pipeline_complete in stream")
                        break

    summary = client.get(f"{BASE}/api/chat/claims/{claim_id}/summary").json()
    print("summary:\n", summary.get("text", "")[:400])
    return 0 if (paused or complete) else 3


if __name__ == "__main__":
    raise SystemExit(main())
