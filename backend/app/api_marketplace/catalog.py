"""API Marketplace catalog constants."""

from __future__ import annotations

# Live APIs that can be subscribed to.
API_CATALOG: list[dict] = [
    {
        "api_name": "submit_claim",
        "title": "Submit Claim",
        "description": "Create a claim record and receive a short-lived upload token for images.",
        "method": "POST",
        "path": "/api/v1/external/claims/submit",
        "wip": False,
    },
    {
        "api_name": "submit_images",
        "title": "Submit Images (linked)",
        "description": "Upload damage photos/video for a claim using the upload token or your API token.",
        "method": "POST",
        "path": "/api/v1/external/claims/{claim_no}/images",
        "wip": False,
    },
    {
        "api_name": "claim_detail",
        "title": "Claim Detail",
        "description": "Fetch claim status and intake fields (supports fuzzy claim reference match).",
        "method": "GET",
        "path": "/api/v1/external/claims/{claim_ref}",
        "wip": False,
    },
    {
        "api_name": "assessment_detail",
        "title": "Assessment Detail",
        "description": "Per-stage assessment pipeline status and payloads.",
        "method": "GET",
        "path": "/api/v1/external/claims/{claim_no}/assessment",
        "wip": False,
    },
    {
        "api_name": "estimation_detail",
        "title": "Estimation Detail",
        "description": "Survey estimate line items, pricing basis, and totals.",
        "method": "GET",
        "path": "/api/v1/external/claims/{claim_no}/estimate",
        "wip": False,
    },
    {
        "api_name": "police_details",
        "title": "Get Police Details",
        "description": "Police report details linked to a claim.",
        "method": "GET",
        "path": "/api/v1/external/police-details/{claim_no}",
        "wip": True,
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
WIP_APIS = frozenset({"police_details"})
SUBSCRIBEABLE_APIS = frozenset(
    item["api_name"] for item in API_CATALOG if not item["wip"]
)
