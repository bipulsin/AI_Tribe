"""Lightweight chat intent classification."""

from __future__ import annotations

import re
from typing import Callable

_CLAIM_REF = re.compile(r"\bCLM-\d{4}-\d{1,6}\b", re.IGNORECASE)

_SHORT_CLAIM_NUM = re.compile(
    r"(?:claim\s*(?:no|number|#)?|no\.?)\s*[:\s]*(\d{1,6})\b",
    re.IGNORECASE,
)

_CLAIM_TRAILING_NUM = re.compile(
    r"\bclaim\b.*?\b(\d{1,6})\b",
    re.IGNORECASE,
)

_KOCHI_ALIASES = ("kochi", "cochi", "cochin")

_KNOWN_CITIES = (
    "pune",
    "ahmedabad",
    "mumbai",
    "delhi",
    "bangalore",
    "bengaluru",
    "chennai",
    "hyderabad",
    "kolkata",
    "jaipur",
    "surat",
    "nagpur",
)

_SUBMIT_PHRASES = (
    "submit a claim",
    "submit claim",
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

_SINGLE_WORD_SKIP = frozenset(
    {
        "a",
        "an",
        "the",
        "ok",
        "yes",
        "no",
        "hi",
        "help",
        "thanks",
        "thank",
        "please",
    }
)

_CLAIM_BY = re.compile(
    r"(?:^|\b)(?:find|show|get|search)?\s*(?:me\s+)?(?:the\s+)?claims?\s+by\s+(?:surveyor\s+)?(.+?)\s*$",
    re.IGNORECASE,
)

_CLAIM_FROM = re.compile(
    r"(?:^|\b)(?:find|show|get|search)?\s*(?:me\s+)?(?:the\s+)?claims?\s+(?:from|at|for|with|about)\s+(.+?)\s*$",
    re.IGNORECASE,
)


def extract_claim_reference(text: str) -> str | None:
    match = _CLAIM_REF.search(text or "")
    if not match:
        return None
    return match.group(0).upper()


def pad_claim_number_suffix(digits: str) -> str:
    """Pad with three leading zeros before the numeric part (26 → 00026, 6 → 0006)."""
    n = int((digits or "").strip())
    return f"000{n}"


def extract_short_claim_number(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    match = _SHORT_CLAIM_NUM.search(raw)
    if match:
        return match.group(1)
    if "claim" in raw.lower():
        trailing = _CLAIM_TRAILING_NUM.search(raw)
        if trailing:
            return trailing.group(1)
    return None


def extract_city_from_text(text: str) -> str | None:
    lower = (text or "").lower()
    if not lower:
        return None
    if any(alias in lower for alias in _KOCHI_ALIASES):
        return "kochi"
    for city in _KNOWN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", lower):
            return city
    return None


def mentions_garage_or_location(text: str) -> bool:
    lower = (text or "").lower()
    if any(word in lower for word in ("garage", "garahe", "workshop", "body shop")):
        return True
    if re.search(r"\b(submitted|filed|registered)\s+(at|in)\b", lower):
        return True
    if re.search(r"\bclaim\b.*\b(at|in|from)\b", lower):
        return True
    return False


def extract_search_term(text: str) -> str | None:
    """Pull a concrete lookup phrase from natural-language claim queries."""
    raw = (text or "").strip()
    if not raw:
        return None

    for pattern in (_CLAIM_BY, _CLAIM_FROM):
        match = pattern.search(raw)
        if match:
            term = match.group(1).strip(" .,;:")
            if term and term.lower() not in _SINGLE_WORD_SKIP:
                return term

    lower = raw.lower()
    if extract_claim_reference(raw) or extract_short_claim_number(raw) is not None:
        return None
    if extract_city_from_text(raw) and (
        mentions_garage_or_location(raw) or "claim" in lower
    ):
        return None

    tokens = [t for t in re.split(r"\W+", raw) if t]
    if len(tokens) == 1:
        word = tokens[0]
        if len(word) >= 2 and word.lower() not in _SINGLE_WORD_SKIP:
            return word

    # Drop leading filler when the message is a short free-text lookup.
    stripped = raw
    for prefix in (
        r"^(?:please\s+)?(?:find|show|get|search|lookup|look\s+up)\s+(?:me\s+)?",
        r"^(?:the\s+)?claims?\s+(?:details?|status|info)\s+(?:for|of|about)?\s*",
        r"^claims?\s+",
    ):
        stripped = re.sub(prefix, "", stripped, flags=re.IGNORECASE).strip()
    if (
        stripped
        and stripped.lower() != lower
        and len(stripped) >= 2
        and len(stripped.split()) <= 6
    ):
        return stripped.strip(" .,;:")

    return None


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

    short_num = extract_short_claim_number(raw)
    if short_num is not None:
        entities["claim_suffix"] = pad_claim_number_suffix(short_num)

    city = extract_city_from_text(raw)
    if city and (mentions_garage_or_location(raw) or "claim" in lower):
        entities["city_query"] = city

    search_term = extract_search_term(raw)
    if search_term:
        entities["search_term"] = search_term

    if draft_active and any(phrase in lower for phrase in _DONE_PHRASES):
        return "done", entities

    if ref or entities.get("claim_suffix") or entities.get("city_query"):
        return "lookup_claim", entities

    if entities.get("search_term"):
        return "lookup_claim", entities

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

    if any(phrase in lower for phrase in _LOOKUP_PHRASES):
        return "lookup_claim", entities

    if draft_active:
        return "submit_claim", entities

    if "claim" in lower and any(word in lower for word in ("detail", "status", "find", "show")):
        return "lookup_claim", entities

    return "general", entities


def is_fresh_submit_intent(text: str) -> bool:
    lower = (text or "").strip().lower()
    return any(phrase in lower for phrase in _SUBMIT_PHRASES)


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
