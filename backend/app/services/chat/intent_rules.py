"""Rule-based chat intent classification (fallback + example seed source).

Kept as the deterministic fallback when the embedding NLU layer is unavailable
or low-confidence. Example phrases here also seed the MiniLM prototype set.
"""

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
    "thane",
    "noida",
    "coimbatore",
    "vadodara",
    "visakhapatnam",
    "dehradun",
    "lucknow",
    "chandigarh",
    "indore",
    "nashik",
)

# Strong multi-word submit cues.
_SUBMIT_PHRASES = (
    "submit a claim",
    "submit claim",
    "submit a new claim",
    "submit new claim",
    "file a claim",
    "file claim",
    "file a new claim",
    "new claim",
    "register a claim",
    "register claim",
    "register a new claim",
    "create a claim",
    "create claim",
    "lodge a claim",
    "lodge claim",
    "open a claim",
    "start a claim",
    "start claim",
    "i want to claim",
    "damage picture",
    "damage photo",
)

# Single-token / loose cues used with "claim" nearby.
_SUBMIT_KEYWORDS = (
    "submit",
    "register",
    "lodge",
    "file",
    "create",
    "open",
    "start",
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
    "assess",
    "start assessment",
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
        "image",
        "images",
        "photo",
        "photos",
        "picture",
        "pictures",
        "video",
        "new",
    }
)

_LOOKUP_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "ok",
        "yes",
        "no",
        "hi",
        "help",
        "please",
        "claim",
        "claims",
        "from",
        "at",
        "in",
        "on",
        "to",
        "my",
        "me",
        "show",
        "find",
        "get",
        "search",
        "lookup",
        "look",
        "up",
        "details",
        "detail",
        "status",
        "info",
        "about",
        "for",
        "with",
        "by",
        "surveyor",
        "garage",
        "garahe",
        "related",
        "submitted",
        "filed",
        "registered",
        "image",
        "images",
        "photo",
        "photos",
        "picture",
        "pictures",
        "video",
        "new",
        "submit",
        "register",
    }
)

_CLAIM_BY = re.compile(
    r"(?:^|\b)(?:find|show|get|search)?\s*(?:me\s+)?(?:the\s+)?claims?\s+by\s+(?:surveyor\s+)?(.+?)\s*$",
    re.IGNORECASE,
)

_CLAIM_FROM = re.compile(
    r"(?:^|\b)(?:find|show|get|search)?\s*(?:me\s+)?(?:the\s+)?claims?\s+(?:from|at|for|about)\s+(.+?)\s*$",
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
    if is_submit_intent(raw):
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


def is_submit_intent(text: str) -> bool:
    """True when the user wants to file/register a new claim."""
    lower = (text or "").strip().lower()
    if not lower:
        return False

    # Lookup-by-actor must never be treated as submit ("claim submitted by Deepa").
    # Also avoid substring false positives: "submit" inside "submitted".
    if re.search(
        r"\bclaims?\s+(?:submitted|filed|registered|lodged|created)\s+by\b",
        lower,
    ):
        return False
    if re.search(r"\b\w+'s\s+claim\b", lower):
        return False

    if any(phrase in lower for phrase in _SUBMIT_PHRASES):
        return True
    if "claim" in lower and any(
        re.search(rf"\b{re.escape(word)}\b", lower) for word in _SUBMIT_KEYWORDS
    ):
        return True
    if re.search(r"\b(new|fresh)\s+claim\b", lower):
        return True
    if re.search(r"\bregister\b", lower) and "claim" in lower:
        return True
    return False


_CLAIM_BY_ACTOR = re.compile(
    r"(?:^|\b)(?:find|show|get|search|look\s*up)?\s*(?:me\s+)?(?:the\s+)?"
    r"claims?\s+(?:submitted|filed|registered|lodged|created)\s+by\s+(.+?)\s*$",
    re.IGNORECASE,
)

_POSSESSIVE_CLAIM = re.compile(
    r"\b([A-Za-z][A-Za-z.'-]{1,40})'s\s+claims?\b",
    re.IGNORECASE,
)

_VAGUE_SEARCH_TERMS = frozenset(
    {
        "claim",
        "claims",
        "a claim",
        "the claim",
        "my claim",
        "an claim",
        "a claims",
        "the claims",
        "my claims",
    }
)

_MEDIA_ONLY = frozenset(
    {
        "image",
        "images",
        "photo",
        "photos",
        "picture",
        "pictures",
        "video",
        "with",
        "from",
        "at",
        "for",
        "about",
        "of",
        "me",
        "show",
        "the",
        "a",
        "an",
    }
)


def extract_actor_name(text: str) -> str | None:
    """Extract a person name from 'claim submitted by X' / \"X's claim\" phrasings."""
    raw = (text or "").strip()
    if not raw:
        return None
    match = _CLAIM_BY_ACTOR.search(raw)
    if match:
        name = match.group(1).strip(" .,;:")
        if name and name.lower() not in _SINGLE_WORD_SKIP:
            return name[:128]
    match = _POSSESSIVE_CLAIM.search(raw)
    if match:
        return match.group(1).strip()[:128]
    return None


def extract_search_term(text: str) -> str | None:
    """Pull a concrete lookup phrase from natural-language claim queries."""
    raw = (text or "").strip()
    if not raw or is_submit_intent(raw):
        return None

    actor = extract_actor_name(raw)
    if actor:
        return actor

    def _usable(term: str | None) -> str | None:
        if not term:
            return None
        cleaned = term.strip(" .,;:")
        if not cleaned or cleaned.lower() in _SINGLE_WORD_SKIP:
            return None
        if cleaned.lower() in _VAGUE_SEARCH_TERMS:
            return None
        tokens = [t for t in re.split(r"\W+", cleaned) if t]
        if tokens and all(t.lower() in _MEDIA_ONLY or t.lower() == "claim" for t in tokens):
            return None
        return cleaned

    for pattern in (_CLAIM_BY, _CLAIM_FROM, _CLAIM_BY_ACTOR):
        match = pattern.search(raw)
        if match:
            term = _usable(match.group(1))
            if term:
                return term

    lower = raw.lower()
    if extract_claim_reference(raw) or extract_short_claim_number(raw) is not None:
        return None

    # "show me claim" / "show me a claim" — no identifier.
    if re.fullmatch(
        r"(?:please\s+)?(?:show|find|get|search|lookup|look\s+up)\s+(?:me\s+)?"
        r"(?:a\s+|the\s+|my\s+)?claims?",
        lower,
    ):
        return None

    tokens = [t for t in re.split(r"\W+", raw) if t]
    if len(tokens) == 1:
        word = tokens[0]
        if len(word) >= 2 and word.lower() not in _SINGLE_WORD_SKIP:
            if word.lower() in _VAGUE_SEARCH_TERMS:
                return None
            return word

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
        term = _usable(stripped)
        if term:
            return term

    return None


def has_concrete_lookup_identifier(text: str, entities: dict | None = None) -> bool:
    """True when lookup has a real claim ref, person, garage, city, or search name."""
    entities = entities or {}
    if entities.get("claim_reference") or entities.get("claim_suffix"):
        return True
    if entities.get("city_query") or entities.get("garage_name") or entities.get("surveyor_name"):
        return True
    if extract_actor_name(text):
        return True
    term = (entities.get("search_term") or extract_search_term(text) or "").strip().lower()
    if term and term not in _VAGUE_SEARCH_TERMS:
        tokens = [t for t in re.split(r"\W+", term) if t]
        if tokens and not all(
            t.lower() in _MEDIA_ONLY or t.lower() in {"claim", "claims"} for t in tokens
        ):
            return True
    return False


def extract_search_tokens(text: str) -> list[str]:
    """Meaningful words to match across claim, garage, surveyor, vehicle, and estimate."""
    raw = (text or "").strip()
    if not raw or is_submit_intent(raw):
        return []

    term = extract_search_term(raw)
    if term:
        return [
            t
            for t in re.split(r"\W+", term)
            if t and t.lower() not in _LOOKUP_STOP_WORDS and len(t) >= 2
        ]

    return [
        t
        for t in re.split(r"\W+", raw)
        if t and t.lower() not in _LOOKUP_STOP_WORDS and len(t) >= 2
    ]


def should_use_city_garage_list(text: str, *, search_term: str | None) -> bool:
    """Garage pick-list only for explicit location/garage phrasing during lookup."""
    if is_submit_intent(text):
        return False
    if search_term:
        return False
    lower = (text or "").lower()
    city = extract_city_from_text(text)
    if not city:
        return False
    if "garage" in lower or "garahe" in lower:
        return True
    if re.search(r"\b(submitted|filed|registered)\s+(at|in)\b", lower):
        return True
    return False


def _is_explicit_lookup(text: str, entities: dict) -> bool:
    """True only when the user clearly wants to search existing claims."""
    if entities.get("claim_reference") or entities.get("claim_suffix"):
        return True
    if extract_actor_name(text):
        return True
    lower = (text or "").strip().lower()
    if not lower:
        return False
    if any(phrase in lower for phrase in _LOOKUP_PHRASES):
        return True
    if re.search(r"\b(find|show|get|search|lookup|look\s+up)\b", lower) and "claim" in lower:
        return True
    if "claim" in lower and any(
        word in lower for word in ("detail", "status", "existing")
    ):
        return True
    return False


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

    if draft_active and any(phrase in lower for phrase in _DONE_PHRASES):
        return "done", entities

    # Submit must win over lookup — e.g. "submit a new claim with image".
    if is_submit_intent(raw):
        city = extract_city_from_text(raw)
        if city:
            entities["city_query"] = city
        return "submit_claim", entities

    # While collecting a new claim, treat replies (city, garage #, dates, names)
    # as submit continuation — never as a free-text claim search.
    if draft_active:
        city = extract_city_from_text(raw)
        if city:
            entities["city_query"] = city

        ref = extract_claim_reference(raw)
        if ref:
            entities["claim_reference"] = ref
        short_num = extract_short_claim_number(raw)
        if short_num is not None:
            entities["claim_suffix"] = pad_claim_number_suffix(short_num)

        if _is_explicit_lookup(raw, entities):
            return "lookup_claim", entities
        return "submit_claim", entities

    ref = extract_claim_reference(raw)
    if ref:
        entities["claim_reference"] = ref

    short_num = extract_short_claim_number(raw)
    if short_num is not None:
        entities["claim_suffix"] = pad_claim_number_suffix(short_num)

    actor = extract_actor_name(raw)
    if actor:
        entities["search_term"] = actor
        entities["actor_name"] = actor

    search_term = entities.get("search_term") or extract_search_term(raw)
    if search_term:
        entities["search_term"] = search_term

    tokens = extract_search_tokens(raw)
    if tokens:
        entities["search_tokens"] = tokens

    if should_use_city_garage_list(raw, search_term=search_term):
        city = extract_city_from_text(raw)
        if city:
            entities["city_query"] = city

    if (
        ref
        or entities.get("claim_suffix")
        or entities.get("city_query")
        or has_concrete_lookup_identifier(raw, entities)
        or _is_explicit_lookup(raw, entities)
    ):
        return "lookup_claim", entities

    if llm_classify:
        try:
            llm_intent, llm_entities = llm_classify(raw)
            if llm_intent:
                entities.update(llm_entities or {})
                return llm_intent, entities
        except Exception:
            pass

    if any(phrase in lower for phrase in _LOOKUP_PHRASES):
        return "lookup_claim", entities

    if "claim" in lower and any(word in lower for word in ("detail", "status", "find", "show")):
        return "lookup_claim", entities

    return "general", entities


def is_fresh_submit_intent(text: str) -> bool:
    return is_submit_intent(text)


def llm_classify_intent(provider: str, api_key: str, text: str) -> tuple[str | None, dict]:
    from app.services.llm import providers

    prompt = (
        "Classify this insurance-assistant user message. Reply JSON only:\n"
        '{"intent":"submit_claim|lookup_claim|general","claim_reference":null|"CLM-...","garage_name":null|"..."}\n'
        "Use submit_claim for filing/registering/creating a new claim (even if images are mentioned).\n"
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
