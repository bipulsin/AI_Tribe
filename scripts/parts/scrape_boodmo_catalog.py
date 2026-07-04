#!/usr/bin/env python3
"""Scrape public boodmo.com catalogue prices into india_parts_seed.csv.

robots.txt (boodmo.com): Disallow /v1/, /search/, /catalog/ajax/, …
API used: /api/v1/customer/api/catalog/part/list (allowed — not under /v1/).
Session tokens obtained by loading an allowed /catalog/… page in Chromium.
"""

from __future__ import annotations

import csv
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT_CSV = REPO / "data" / "parts_seed" / "india_parts_seed.csv"
REPORT_DIR = REPO / "data" / "parts_seed" / "scrape_reports"
UA = "AI-Tribe-PartsResearch/1.0 (+internal-demo; contact: lab@tradentical.com)"
SOURCE = "boodmo.com"
SOURCED_AT = date.today().isoformat()
RATE_LIMIT_S = 0.8
SSL_CTX = ssl._create_unverified_context()

# Catalog part name -> (category_id, name_hints for disambiguation)
PART_CATEGORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Front Bumper": ("3786", ("FRONT", "FR BUMPER", "BUMPER, FRONT")),
    "Rear Bumper": ("3790", ("REAR", "RR BUMPER", "BUMPER, REAR")),
    "Front Door": ("3538", ("FRONT DOOR", "DOOR, FRONT", "FR DOOR")),
    "Rear Door": ("3538", ("REAR DOOR", "DOOR, REAR", "RR DOOR")),
    "Headlamp": ("3686", ("HEADLAMP", "HEADLIGHT", "HEAD LAMP")),
    "Tail Lamp": ("3691", ("TAIL", "REAR LAMP", "COMBINATION LAMP")),
    "Windshield": ("4504", ("WINDSHIELD", "WINDSCREEN", "FRONT GLASS")),
    "Front Fender": ("4147", ("FRONT FENDER", "FENDER, FRONT", "FR FENDER")),
    "Rear Fender": ("4147", ("REAR FENDER", "FENDER, REAR", "RR FENDER")),
    "Side Mirror": ("3663", ("MIRROR", "REAR VIEW", "OUTSIDE MIRROR")),
    "Hood": ("3540", ("BONNET", "HOOD")),
    "Trunk Lid": ("3538", ("BOOT", "TRUNK", "TAIL GATE", "TAILGATE", "BACK DOOR")),
    "Tire": ("3623", ("TYRE", "TIRE")),
    "Front Grill": ("4072", ("GRILL", "GRILLE")),
    "Fog Lamp": ("3687", ("FOG",)),
    "Quarter Panel": ("4406", ("QUARTER",)),
    "Roof Panel": ("4407", ("ROOF",)),
    "Radiator Support": ("4383", ("RADIATOR SUPPORT", "RAD SUPPORT")),
    "Wheel Rim": ("4070", ("RIM", "WHEEL")),
    "Door Handle": ("4149", ("HANDLE",)),
    "Bonnet Hinge": ("4819", ("HINGE",)),
    "Bumper Bracket": ("4241", ("BRACKET",)),
    "Indicator Lamp": ("4140", ("INDICATOR", "SIDE LAMP", "TURN")),
    "Rear Glass": ("4505", ("REAR WINDSHIELD", "REAR WINDSCREEN", "BACK GLASS")),
    "Side Skirt": ("4672", ("SILL", "SKIRT", "SIDE BODY")),
}

# Default labour hours from original seed schema
PART_LABOR: dict[str, float] = {
    "Front Bumper": 2.0,
    "Rear Bumper": 2.0,
    "Front Door": 3.5,
    "Rear Door": 3.0,
    "Headlamp": 1.5,
    "Tail Lamp": 1.0,
    "Windshield": 2.5,
    "Front Fender": 2.5,
    "Rear Fender": 2.5,
    "Side Mirror": 0.8,
    "Hood": 3.0,
    "Trunk Lid": 2.5,
    "Tire": 0.5,
    "Front Grill": 1.0,
    "Fog Lamp": 0.8,
    "Quarter Panel": 3.0,
    "Roof Panel": 4.0,
    "Radiator Support": 2.0,
    "Wheel Rim": 1.0,
    "Door Handle": 0.5,
    "Bonnet Hinge": 1.0,
    "Bumper Bracket": 0.5,
    "Indicator Lamp": 0.6,
    "Rear Glass": 2.0,
    "Side Skirt": 1.5,
}

# make -> model -> boodmo modelLine id (numeric)
# None = not listed on boodmo (limited aftermarket)
MAKES: dict[str, dict[str, int | None]] = {
    "Maruti": {
        "Swift": 11299,
        "Baleno": 11921,
        "WagonR": 11302,
        "Dzire": 11290,
        "Brezza": 12019,
        "Ertiga": 11292,
        "Alto K10": 12484,
        "Fronx": 12640,
        "Grand Vitara": 11294,
        "XL6": 12336,
    },
    "Mahindra": {
        "Scorpio-N": 11280,  # listed as Scorpio on boodmo
        "XUV700": 12428,
        "XUV 3XO": 12814,
        "Bolero Neo": 11275,  # Bolero family
        "Thar": 11281,
        "XUV500": 11283,
        "Bolero": 11275,
        "Marazzo": 12296,
    },
    "Hyundai": {
        "Creta": 11253,
        "Venue": 12325,
        "i20": 11248,
        "Grand i10 Nios": 12483,
        "Verna": 11243,
        "Alcazar": 12423,
        "Exter": 12674,
        "Aura": 12375,
        "Tucson": 11249,
    },
    "Kia": {
        "Seltos": 12345,
        "Sonet": 12385,
        "Carens": 12473,
        "Carnival": 12378,
        "Syros": None,  # not on boodmo
        "EV6": 12504,
    },
    "Tata": {
        "Nexon": 12240,
        "Punch": 12437,
        "Tiago": 12017,
        "Altroz": 12357,
        "Harrier": 12306,
        "Safari": 12066,
        "Tigor": 12183,
        "Curvv": 12844,
    },
    "Honda": {
        "City": 11236,
        "Amaze": 11234,
        "Elevate": 12736,
        "Jazz": 11239,
        "WR-V": 12178,
        "Civic": 11237,
    },
    "MG": {
        "Hector": 12333,
        "Astor": 12480,
        "Comet EV": 12660,
        "ZS EV": 12476,
        "Gloster": 12518,
        "Windsor EV": None,  # not on boodmo
    },
    "Toyota": {
        "Innova": 11392,
        "Innova Hycross": None,  # not listed separately from Innova on boodmo
        "Fortuner": 11391,
        "Urban Cruiser Hyryder": 12580,
        "Glanza": 12329,
        "Rumion": 12716,
        "Camry": 11386,
        "Land Cruiser": 11388,  # low-volume; may be thin
    },
}


class BoodmoSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self._pw = None
        self._browser = None
        self._page = None
        self._calls = 0

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        context = self._browser.new_context(user_agent=UA, locale="en-IN")
        self._page = context.new_page()
        self.refresh()

    def refresh(self) -> None:
        assert self._page is not None
        url = "https://boodmo.com/catalog/3786-front_bumper/m11299-maruti-swift/"
        with self._page.expect_response(
            lambda r: "catalog/part/list" in r.url and r.status == 200,
            timeout=90000,
        ) as resp_info:
            self._page.goto(url, wait_until="domcontentloaded", timeout=90000)
        resp = resp_info.value
        headers = dict(resp.request.headers)
        self.headers = {
            k: headers[k]
            for k in headers
            if k.startswith("x-")
            or k in ("accept", "accept-version", "accept-language", "user-agent")
        }
        self.headers["referer"] = "https://boodmo.com/"
        self._calls = 0

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def part_list(self, category_id: str, model_line_id: int, limit: int = 48) -> list[dict]:
        if self._calls >= 40:
            self.refresh()
        params = {
            "sort": "new",
            "page[offset]": "1",
            "page[limit]": str(limit),
            "filter[category]": str(category_id),
            "filter[modelLine]": str(model_line_id),
        }
        api = (
            "https://boodmo.com/api/v1/customer/api/catalog/part/list?"
            + urllib.parse.urlencode(params)
        )
        req = urllib.request.Request(api, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                self.refresh()
                req = urllib.request.Request(api, headers=self.headers)
                with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                    data = json.loads(r.read().decode())
            else:
                raise
        self._calls += 1
        time.sleep(RATE_LIMIT_S)
        return list(data.get("items") or [])


def _pick_item(items: list[dict], hints: tuple[str, ...]) -> dict | None:
    if not items:
        return None
    scored: list[tuple[int, dict]] = []
    for item in items:
        if not item.get("offer") or item["offer"].get("price") in (None, 0):
            continue
        name = (item.get("name") or "").upper()
        score = sum(1 for h in hints if h in name)
        # Prefer OEM/genuine when available
        brand = item.get("brand") or {}
        if brand.get("oem") or brand.get("genuine"):
            score += 2
        scored.append((score, item))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], (x[1].get("offer") or {}).get("price") or 10**12))
    return scored[0][1]


def _price_inr(item: dict) -> float:
    # boodmo stores paise
    paise = (item.get("offer") or {}).get("price") or 0
    return round(float(paise) / 100.0, 2)


def _part_number(item: dict) -> str:
    num = (item.get("number") or "").strip()
    return num.replace("...", "") if num else ""


def scrape_model(session: BoodmoSession, make: str, model: str, model_line_id: int) -> list[dict]:
    rows: list[dict] = []
    for part_name, (cat_id, hints) in PART_CATEGORIES.items():
        try:
            items = session.part_list(cat_id, model_line_id)
        except Exception as exc:
            print(f"    ! {part_name}: fetch error {exc}")
            continue
        item = _pick_item(items, hints)
        if not item:
            continue
        rows.append(
            {
                "make": make,
                "model": model,
                "part_name": part_name,
                "part_number": _part_number(item) or "",
                "price": f"{_price_inr(item):.2f}",
                "labor_hours": f"{PART_LABOR.get(part_name, 1.0):.1f}",
                "currency": "INR",
                "region": "IN",
                "source": SOURCE,
                "sourced_at": SOURCED_AT,
            }
        )
    return rows


def load_seed_rows() -> list[dict]:
    if not OUT_CSV.exists():
        return []
    with OUT_CSV.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(rows: list[dict]) -> None:
    fieldnames = [
        "make",
        "model",
        "part_name",
        "part_number",
        "price",
        "labor_hours",
        "currency",
        "region",
        "source",
        "sourced_at",
    ]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {k: row.get(k, "") for k in fieldnames}
            if not out.get("sourced_at"):
                out["sourced_at"] = (
                    SOURCED_AT if out.get("source") == SOURCE else "2026-07-03"
                )
            writer.writerow(out)


def main(only_makes: set[str] | None = None) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_seed_rows()
    # index existing seed by (make, model, part_name)
    seed_index: dict[tuple[str, str, str], dict] = {}
    for row in existing:
        key = (row["make"], row["model"], row["part_name"])
        seed_index[key] = row

    # When scraping a subset, keep all existing non-target rows intact.
    retained: list[dict] = []
    if only_makes:
        for row in existing:
            if row["make"] not in only_makes:
                retained.append(row)

    all_rows: list[dict] = list(retained)
    limited: list[str] = []
    session = BoodmoSession()
    session.start()
    try:
        for make, models in MAKES.items():
            if only_makes and make not in only_makes:
                continue
            make_rows: list[dict] = []
            print(f"\n=== {make} ===")
            for model, model_line_id in models.items():
                if model_line_id is None:
                    msg = f"{make} {model}: limited aftermarket data available for this model (not listed on boodmo)"
                    print(f"  {msg}")
                    limited.append(msg)
                    continue
                print(f"  scraping {make} {model} (id={model_line_id})…", flush=True)
                rows = scrape_model(session, make, model, model_line_id)
                print(f"  {make} {model}: {len(rows)} parts", flush=True)
                if len(rows) < 5:
                    msg = (
                        f"{make} {model}: limited aftermarket data available for this model "
                        f"({len(rows)} parts found)"
                    )
                    print(f"  !! {msg}")
                    limited.append(msg)
                make_rows.extend(rows)
            print(f"=== {make} TOTAL: {len(make_rows)} rows ===", flush=True)
            (REPORT_DIR / f"{make.lower()}.json").write_text(
                json.dumps(
                    {
                        "make": make,
                        "rows": len(make_rows),
                        "models": {
                            m: sum(1 for r in make_rows if r["model"] == m)
                            for m in models
                        },
                    },
                    indent=2,
                )
            )
            all_rows.extend(make_rows)
    finally:
        session.close()

    # Merge: scraped wins; keep prior seed only for (make,model,part) not scraped
    # within the makes we just scraped.
    scraped_keys = {
        (r["make"], r["model"], r["part_name"])
        for r in all_rows
        if r.get("source") == SOURCE
    }
    kept_seed = 0
    target_makes = only_makes or set(MAKES)
    for key, row in seed_index.items():
        if key in scraped_keys:
            continue
        make, model, _part = key
        if make not in target_makes:
            continue
        if make in MAKES and model in MAKES[make]:
            out = dict(row)
            out.setdefault("sourced_at", "2026-07-03")
            all_rows.append(out)
            kept_seed += 1

    # stable sort
    all_rows.sort(key=lambda r: (r["make"], r["model"], r["part_name"]))
    write_csv(all_rows)

    summary = {
        "sourced_at": SOURCED_AT,
        "source": SOURCE,
        "total_rows": len(all_rows),
        "scraped_rows": len(scraped_keys),
        "kept_seed_rows": kept_seed,
        "limited_aftermarket": limited,
    }
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== FINAL ===")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    import sys

    only = {a for a in sys.argv[1:] if a}
    main(only_makes=only or None)
