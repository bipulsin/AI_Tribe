"""Chat intent classification — embedding NLU with rule-based fallback.

Public API used by the chat handler. Understanding layer only; downstream
routing (submit / lookup handlers) is unchanged.

BYOK policy (chat intent only — does not affect deepfake / VMMR / damage /
estimate assist):
  1. Local MiniLM classifier is the baseline for every user.
  2. Rule-based intent_rules (phrases from recent product work) is always
     available as fallback and hard-gates draft replies / submit keywords.
  3. BYOK LLM is consulted only when both embedding and rules are uncertain;
     it never silently overrides a confident local decision.
"""

from __future__ import annotations

from typing import Callable

from app.services.chat import intent_rules as rules
from app.services.chat.nlu.service import (
    CLARIFY_MESSAGE,
    OFF_TOPIC_REDIRECT,
    classify_message,
)

# Re-export extractors / helpers used elsewhere (handler, draft, garage flows).
extract_claim_reference = rules.extract_claim_reference
extract_short_claim_number = rules.extract_short_claim_number
extract_city_from_text = rules.extract_city_from_text
extract_search_term = rules.extract_search_term
extract_search_tokens = rules.extract_search_tokens
pad_claim_number_suffix = rules.pad_claim_number_suffix
is_submit_intent = rules.is_submit_intent
is_fresh_submit_intent = rules.is_fresh_submit_intent
mentions_garage_or_location = rules.mentions_garage_or_location
should_use_city_garage_list = rules.should_use_city_garage_list
llm_classify_intent = rules.llm_classify_intent


def classify_intent(
    text: str,
    *,
    draft_active: bool = False,
    llm_classify: Callable[[str], tuple[str | None, dict]] | None = None,
) -> tuple[str, dict]:
    """Return (intent, entities).

    Intents: submit_claim, lookup_claim, done, general, off_topic, clarify.
    """
    result = classify_message(
        text,
        draft_active=draft_active,
        llm_classify=llm_classify,
    )
    return result.intent, result.entities


__all__ = [
    "CLARIFY_MESSAGE",
    "OFF_TOPIC_REDIRECT",
    "classify_intent",
    "extract_claim_reference",
    "extract_short_claim_number",
    "extract_city_from_text",
    "extract_search_term",
    "extract_search_tokens",
    "pad_claim_number_suffix",
    "is_submit_intent",
    "is_fresh_submit_intent",
    "mentions_garage_or_location",
    "should_use_city_garage_list",
    "llm_classify_intent",
]
