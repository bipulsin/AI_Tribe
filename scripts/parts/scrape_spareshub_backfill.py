#!/usr/bin/env python3
"""Probe spareshub.com for body-part prices missing from boodmo coverage.

robots.txt (spareshub.com, Shopify storefront):
  User-agent: * Allow: /
  Disallow: /cart/, /checkout, /admin, /services, /recommendations/products, …
  Public product/collection HTML and collections.json / products.json are crawlable.
  Agents instructed to use UCP/MCP for cart/checkout (we only read catalogue).

This script only *adds* rows for (make, model, part_name) not already present
with a priced listing. It does not overwrite boodmo.com rows.
"""

from __future__ import annotations

import csv
import json
import ssl
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CSV_PATH = REPO / "data" / "parts_seed" / "india_parts_seed.csv"
REPORT_DIR = REPO / "data" / "parts_seed" / "scrape_reports"
UA = "AI-Tribe-PartsResearch/1.0 (+internal-demo; contact: lab@tradentical.com)"
SOURCE = "spareshub.com"
SOURCED_AT = date.today().isoformat()
RATE_LIMIT_S = 0.8
SSL_CTX = ssl._create_unverified_context()

PART_LABOR = {
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

PART_HINTS = {
    "Front Bumper": ("front bumper", "bumper front", "bumper, front"),
    "Rear Bumper": ("rear bumper", "bumper rear", "bumper, rear"),
    "Front Door": ("front door", "door, front", "door front"),
    "Rear Door": ("rear door", "door, rear", "door rear"),
    "Headlamp": ("headlamp", "headlight", "head lamp", "lamp assy-head"),
    "Tail Lamp": ("tail lamp", "tail light", "rear lamp", "rear comb"),
    "Windshield": ("windshield", "windscreen"),
    "Front Fender": ("front fender", "fender, front", "fender front"),
    "Rear Fender": ("rear fender", "fender, rear", "fender rear"),
    "Side Mirror": ("side mirror", "outside mirror", "rear view mirror", "orvm"),
    "Hood": ("hood", "bonnet"),
    "Trunk Lid": ("trunk", "boot lid", "tail gate", "tailgate"),
    "Tire": ("tyre", "tire"),
    "Front Grill": ("grill", "grille"),
    "Fog Lamp": ("fog lamp", "fog light"),
    "Quarter Panel": ("quarter panel",),
    "Roof Panel": ("roof panel",),
    "Radiator Support": ("radiator support",),
    "Wheel Rim": ("wheel rim", "alloy wheel", "steel wheel", "wheel assy"),
    "Door Handle": ("door handle", "handle assy-door"),
    "Bonnet Hinge": ("bonnet hinge", "hood hinge"),
    "Bumper Bracket": ("bumper bracket",),
    "Indicator Lamp": ("indicator", "side repeater", "turn signal"),
    "Rear Glass": ("rear glass", "rear windshield", "back glass"),
    "Side Skirt": ("side skirt", "sill guard", "side moulding"),
}

# Thin / target models to backfill
TARGETS = {
    "Kia": {
        "Sonet": ("sonet",),
        "Carens": ("carens", "carrens"),
        "Carnival": ("carnival",),
        "Seltos": ("seltos",),
        "Syros": ("syros",),
        "EV6": ("ev6", "ev 6"),
    },
    "MG": {
        "Windsor EV": ("windsor",),
        "Comet EV": ("comet",),
        "Hector": ("hector",),
        "Astor": ("astor",),
        "ZS EV": ("zs ev", "zs-ev", "zsev"),
        "Gloster": ("gloster",),
    },
}

COLLECTION_HANDLES = [
    "kia",
    "kia-sonet",
    "kia-carens",
    "kia-carnival",
    "kia-seltos",
    "kia-syros",
    "kia-ev6",
    "mg-motors",
    "mg-comet-ev",
    "mg-hector",
    "mg-astor",
    "mg-zs-ev",
    "mg-gloster",
    "mg-windsor-ev",
]


def get_json(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def fetch_collection_products(handle: str) -> list[dict]:
    for attempt in range(4):
        try:
            data = get_json(
                f"https://spareshub.com/collections/{handle}/products.json?limit=250"
            )
            return list(data.get("products") or [])
        except urllib.error.HTTPError as exc:
            if exc.code in {503, 429} and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            if exc.code in {404, 503, 429}:
                print(f"  warn: {handle} -> HTTP {exc.code}, treating as empty")
                return []
            raise
    return []


def product_price(product: dict) -> tuple[float | None, str]:
    for variant in product.get("variants") or []:
        try:
            price = float(variant.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            return price, (variant.get("sku") or "").strip()
    return None, ""


def load_existing_keys() -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            keys.add((row["make"], row["model"], row["part_name"]))
    return keys


def count_by_make(make: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["make"] == make:
                counts[row["model"]] += 1
    return dict(counts)


def main() -> None:
    before_kia = count_by_make("Kia")
    before_mg = count_by_make("MG")
    before_total = sum(1 for _ in csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    existing = load_existing_keys()

    products_by_handle: dict[str, dict] = {}
    collection_counts: dict[str, int] = {}
    for handle in COLLECTION_HANDLES:
        products = fetch_collection_products(handle)
        collection_counts[handle] = len(products)
        for product in products:
            products_by_handle[product.get("handle") or id(product)] = product
        print(f"collection {handle}: {len(products)} products")
        time.sleep(RATE_LIMIT_S)

    per_model_found: dict[str, dict[str, list[str]]] = {
        "Kia": defaultdict(list),
        "MG": defaultdict(list),
    }
    new_rows: list[dict] = []

    for make, models in TARGETS.items():
        for model, aliases in models.items():
            for product in products_by_handle.values():
                title = (product.get("title") or "").lower()
                tags = product.get("tags") or []
                if isinstance(tags, str):
                    tags = [tags]
                blob = title + " " + " ".join(t.lower() for t in tags)
                if not any(alias in blob for alias in aliases):
                    continue
                price, sku = product_price(product)
                if price is None:
                    continue
                for part_name, hints in PART_HINTS.items():
                    if not any(hint in blob for hint in hints):
                        continue
                    per_model_found[make][model].append(part_name)
                    key = (make, model, part_name)
                    if key in existing:
                        continue
                    # avoid duplicate adds within this run
                    if any(
                        r["make"] == make
                        and r["model"] == model
                        and r["part_name"] == part_name
                        for r in new_rows
                    ):
                        continue
                    new_rows.append(
                        {
                            "make": make,
                            "model": model,
                            "part_name": part_name,
                            "part_number": sku,
                            "price": f"{price:.2f}",
                            "labor_hours": f"{PART_LABOR.get(part_name, 1.0):.1f}",
                            "currency": "INR",
                            "region": "IN",
                            "source": SOURCE,
                            "sourced_at": SOURCED_AT,
                        }
                    )

    # Deduplicate found part names per model for reporting
    per_model_counts = {
        make: {model: len(set(parts)) for model, parts in models.items()}
        for make, models in per_model_found.items()
    }
    # Ensure all target models appear
    for make, models in TARGETS.items():
        for model in models:
            per_model_counts[make].setdefault(model, 0)

    if new_rows:
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
        with CSV_PATH.open(newline="", encoding="utf-8") as fh:
            existing_rows = list(csv.DictReader(fh))
        existing_rows.extend(new_rows)
        existing_rows.sort(key=lambda r: (r["make"], r["model"], r["part_name"]))
        with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)

    after_kia = count_by_make("Kia")
    after_mg = count_by_make("MG")
    after_total = sum(1 for _ in csv.DictReader(CSV_PATH.open(encoding="utf-8")))

    report = {
        "source": SOURCE,
        "sourced_at": SOURCED_AT,
        "robots_txt": "Allow: / for public catalogue; cart/checkout/admin disallowed",
        "collection_product_counts": collection_counts,
        "body_parts_found_per_model": per_model_counts,
        "new_rows_added": len(new_rows),
        "before": {"Kia": before_kia, "MG": before_mg, "total": before_total},
        "after": {"Kia": after_kia, "MG": after_mg, "total": after_total},
        "note": (
            "SparesHub model collections for Kia/MG body parts are empty; "
            "brand 'kia' collection only has service parts (filters, bearings, "
            "brake pads/discs) outside the body-part set."
        ),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "spareshub_backfill.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
