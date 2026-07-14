"""API Marketplace catalog constants."""

from __future__ import annotations

# Live APIs that can be subscribed to.
API_CATALOG: list[dict] = [
    {
        "api_name": "submit_claim",
        "title": "Submit Claim",
        "description": (
            "Start a new motor claim with surveyor, claimant, garage, and accident date. "
            "Returns a claim number and a short-lived upload token so photos can be attached next. "
            "Always enabled for every marketplace user."
        ),
        "method": "POST",
        "path": "/api/v1/external/claims/submit",
        "wip": False,
        "always_subscribed": True,
    },
    {
        "api_name": "submit_images",
        "title": "Submit Images",
        "description": (
            "Attach damage photos or a short video to an existing claim. "
            "Use the upload token from Submit Claim, or your API token if you own the claim."
        ),
        "method": "POST",
        "path": "/api/v1/external/claims/{claim_no}/images",
        "wip": False,
        "always_subscribed": False,
    },
    {
        "api_name": "claim_detail",
        "title": "Claim Detail",
        "description": (
            "Look up a claim by number (fuzzy match supported) and get status, intake fields, "
            "image count, and the latest pipeline stage."
        ),
        "method": "GET",
        "path": "/api/v1/external/claims/{claim_ref}",
        "wip": False,
        "always_subscribed": False,
    },
    {
        "api_name": "assessment_detail",
        "title": "Assessment Detail",
        "description": (
            "Read the multi-stage assessment pipeline: deepfake screening, vehicle identity, "
            "damage mapping, fraud checks, and whether work is still in progress."
        ),
        "method": "GET",
        "path": "/api/v1/external/claims/{claim_no}/assessment",
        "wip": False,
        "always_subscribed": False,
    },
    {
        "api_name": "estimation_detail",
        "title": "Estimation Detail",
        "description": (
            "Fetch the survey estimate once pricing is ready: part line items, labour, totals, "
            "and pricing-basis notices (including approximate / fallback catalogue pricing)."
        ),
        "method": "GET",
        "path": "/api/v1/external/claims/{claim_no}/estimate",
        "wip": False,
        "always_subscribed": False,
    },
    {
        "api_name": "policy_details",
        "title": "Get Policy Details",
        "description": (
            "Fetch policy information from the Policy Administration system for a claim "
            "(cover, policy number, status, and related policy attributes). "
            "Coming soon — not available for subscription yet."
        ),
        "method": "GET",
        "path": "/api/v1/external/policy-details/{claim_no}",
        "wip": True,
        "always_subscribed": False,
    },
]

VALIDITY_DAYS = (30, 60, 90, 120, 180, 360)
DEFAULT_VALIDITY_DAYS = 90
HEAD_API = "submit_claim"
CHAINABLE_APIS = (
    "submit_images",
    "claim_detail",
    "assessment_detail",
    "estimation_detail",
)
WIP_APIS = frozenset({"policy_details"})
SUBSCRIBEABLE_APIS = frozenset(
    item["api_name"] for item in API_CATALOG if not item["wip"]
)
ALWAYS_SUBSCRIBED_APIS = frozenset(
    item["api_name"] for item in API_CATALOG if item.get("always_subscribed")
)

API_TITLE_BY_NAME = {item["api_name"]: item["title"] for item in API_CATALOG}
