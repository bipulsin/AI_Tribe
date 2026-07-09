"""Lightweight chat intent classification."""

from __future__ import annotations

import re
from typing import Callable

_CLAIM_REF = re.compile(r"\bCLM-\d{4}-\d{1,6}\b", re.IGNORECASE)

_SUBMIT_PHRASES = (
    "submit",
    "file a claim",
    "file claim",
    "new claim",
    "upload",
    "damage picture",
    "damage photo",
    "i want to claim",
)

_LOOKUP_PHRASES = (
    "find my claim",
    "claim status",
    "claim details",
    "get details",
    "look up",
    "lookup",
    "search claim",
    "existing claim",
    "my claim",
)

_DONE_PHRASES = (
    "done",
    "that's all",
    "thats all",
    "finished",
    "submit now",
    "ready to submit",
    "go ahead",
)


def extract_claim_reference(text: str) -> str | None:
    match = _CLAIM_REF.search(text or "")
    if not match:
        return None
    return match.group(0).upper()


def classify_intent(
    text: str,
    *,
    draft_active: bool = False,
    llm_classify: Callable[[str], tuple[str | None, dict]] | None = None,
) -> tuple[str, dict]:
    """Return (intent, entities). Intents: submit_claim, lookup_claim, done, general."""
    raw = (text or "").strip()
    lower = raw.lower()
    entities: dict = {}

    ref = extract_claim_reference(raw)
    if ref:
        entities["claim_reference"] = ref

    if draft_active and any(phrase in lower for phrase in _DONE_PHRASES):
        return "done", entities

    if llm_classify and not draft_active:
        try:
            llm_intent, llm_entities = llm_classify(raw)
            if llm_intent:
                entities.update(llm_entities or {})
                return llm_intent, entities
        except Exception:
            pass

    if not draft_active and any(phrase in lower for phrase in _SUBMIT_PHRASES):
        return "submit_claim", entities

    if ref or any(phrase in lower for phrase in _LOOKUP_PHRASES):
        return "lookup_claim", entities

    if draft_active:
        return "submit_claim", entities

    if "claim" in lower and any(word in lower for word in ("detail", "status", "find", "show")):
        return "lookup_claim", entities

    return "general", entities


def llm_classify_intent(provider: str, api_key: str, text: str) -> tuple[str | None, dict]:
    from app.services.llm import providers

    prompt = (
        "Classify this insurance-assistant user message. Reply JSON only:\n"
        '{"intent":"submit_claim|lookup_claim|general","claim_reference":null|"CLM-...","garage_name":null|"..."}\n'
        f"Message: {text}"
    )
    reply = providers.chat_text(provider, api_key, prompt, max_tokens=120)
    if not reply:
        return None, {}
    try:
        data = providers.parse_json_block(reply)
    except (ValueError, TypeError):
        return None, {}
    intent = str(data.get("intent") or "").strip().lower()
    entities: dict = {}
    if data.get("claim_reference"):
        entities["claim_reference"] = str(data["claim_reference"]).upper()
    if data.get("garage_name"):
        entities["garage_name"] = str(data["garage_name"]).strip()
    if intent not in {"submit_claim", "lookup_claim", "general"}:
        return None, entities
    return intent, entities
