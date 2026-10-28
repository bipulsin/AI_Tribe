"""Unit tests for usability report detail formatting helpers."""

from __future__ import annotations

from app.services.usage_logging import (
    extract_metadata,
    format_data_entered,
    format_search_params,
    page_module_label,
)
from app.services.usage_report_service import _shape_detail_event


def test_extract_metadata_captures_claim_and_search_params():
    meta = extract_metadata(
        "/claims/42/estimate",
        [("q", "FOO-1"), ("token", "secret-value")],
    )
    assert meta is not None
    assert meta["claim_id"] == 42
    assert meta["search_params"]["q"] == "FOO-1"
    assert meta["search_params"]["token"] == "[redacted]"


def test_page_module_and_data_entered_formatting():
    assert page_module_label(
        feature_area="form_ui",
        event_type="claim_view",
        endpoint_or_route="GET /claims/42",
    ) == "Claims form · claim view"

    entered = format_data_entered(
        {
            "claim_id": 42,
            "status": "submitted",
            "source": "claims",
            "search_params": {"q": "x"},
        }
    )
    assert entered == "claim_id=42, status=submitted"
    assert format_search_params({"search_params": {"q": "x", "page": "2"}}) == "q=x, page=2"
    assert format_search_params({"claim_no": "C-9"}) == "claim_no=C-9"
    assert format_data_entered(None) is None
    assert format_search_params({}) is None


def test_shape_detail_event_adds_display_columns():
    shaped = _shape_detail_event(
        {
            "id": 1,
            "event_type": "lookup_claim",
            "feature_area": "form_ui",
            "endpoint_or_route": "GET /api/claims/search",
            "occurred_at": "2026-10-28T10:00:00+00:00",
            "ip_address": "203.0.113.10",
            "metadata": {
                "search_params": {"q": "ABC"},
                "claim_id": 7,
            },
            "source": "usage_events",
        }
    )
    assert shaped["page_module"] == "Claims form · lookup claim"
    assert shaped["data_entered"] == "claim_id=7"
    assert shaped["search_params"] == "q=ABC"
    assert shaped["ip_address"] == "203.0.113.10"
