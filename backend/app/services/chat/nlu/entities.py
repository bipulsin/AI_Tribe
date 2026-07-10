"""Entity extraction for chat NLU (spaCy + high-precision claim/date/city rules)."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.chat import intent_rules as rules

logger = logging.getLogger("ai_tribe.chat_nlu")

_lock = threading.Lock()
_nlp: Any = None
_load_error: str | None = None

_DATE_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
]

_GARAGE_PATTERNS = [
    re.compile(r"garage(?:\s+name)?\s*(?:is|:|-)\s*(.+)", re.IGNORECASE),
    re.compile(r"at\s+(.+?)\s+garage", re.IGNORECASE),
]

_SURVEYOR_PATTERNS = [
    re.compile(r"surveyor(?:\s+name)?\s*(?:is|:|-)\s*(.+)", re.IGNORECASE),
    re.compile(r"surveyor\s+(.+)", re.IGNORECASE),
]


def _resolve_spacy_dir(root: Path) -> Path | None:
    candidates = [
        root / "models" / "en_core_web_sm",
        root / "en_core_web_sm",
    ]
    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    return None


def get_nlp(root: Path):
    global _nlp, _load_error
    with _lock:
        if _nlp is not None:
            return _nlp
        if _load_error is not None:
            return None
        model_dir = _resolve_spacy_dir(root)
        if model_dir is None:
            _load_error = f"spaCy model not found under {root}"
            logger.info("Chat NLU: %s — regex/city entity fallback only", _load_error)
            return None
        try:
            import spacy  # noqa: PLC0415

            _nlp = spacy.load(str(model_dir))
            logger.info("Chat NLU: loaded spaCy from %s", model_dir)
            return _nlp
        except Exception as exc:
            _load_error = str(exc)
            logger.warning("Chat NLU: spaCy load failed (%s)", exc)
            return None


def _clean_tail(value: str) -> str:
    text = value.strip().strip(".,;")
    for stop in (" accident", " date", " surveyor", " and ", " garage"):
        idx = text.lower().find(stop)
        if idx > 0:
            text = text[:idx]
    return text.strip().rstrip(",")


def extract_entities(text: str, *, root: Path | None = None) -> dict:
    """Extract claim/garage/city/surveyor/date entities from a chat message."""
    raw = (text or "").strip()
    entities: dict = {}
    if not raw:
        return entities

    # High-precision structured fields — always from rules/regex.
    ref = rules.extract_claim_reference(raw)
    if ref:
        entities["claim_reference"] = ref

    short = rules.extract_short_claim_number(raw)
    if short is not None:
        entities["claim_suffix"] = rules.pad_claim_number_suffix(short)

    actor = rules.extract_actor_name(raw)
    if actor:
        entities["actor_name"] = actor
        entities["search_term"] = actor

    city = rules.extract_city_from_text(raw)
    if city:
        entities["city_query"] = city

    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw)
        if match:
            entities["accident_date"] = match.group(1)
            break

    for pattern in _GARAGE_PATTERNS:
        match = pattern.search(raw)
        if match:
            entities["garage_name"] = _clean_tail(match.group(1))[:128]
            break

    for pattern in _SURVEYOR_PATTERNS:
        match = pattern.search(raw)
        if match:
            entities["surveyor_name"] = _clean_tail(match.group(1))[:128]
            break

    # spaCy soft signals (do not override high-precision fields).
    if root is not None:
        nlp = get_nlp(root)
        if nlp is not None:
            try:
                doc = nlp(raw)
                if "city_query" not in entities:
                    for ent in doc.ents:
                        if ent.label_ in {"GPE", "LOC"}:
                            city_hit = rules.extract_city_from_text(ent.text)
                            if city_hit:
                                entities["city_query"] = city_hit
                                break
                if "surveyor_name" not in entities:
                    for ent in doc.ents:
                        if ent.label_ == "PERSON":
                            entities["surveyor_name"] = ent.text.strip()[:128]
                            break
                if "accident_date" not in entities:
                    for ent in doc.ents:
                        if ent.label_ == "DATE":
                            # Keep only parseable calendar-like dates.
                            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
                                try:
                                    datetime.strptime(ent.text.strip()[:32], fmt)
                                    entities["accident_date"] = ent.text.strip()[:32]
                                    break
                                except ValueError:
                                    continue
                            if "accident_date" in entities:
                                break
            except Exception as exc:
                logger.debug("spaCy entity pass failed: %s", exc)

    # Lookup search term/tokens from rules (still useful for routing).
    # Skip for bare city replies — those are submit-flow answers, not search queries.
    city_only = bool(entities.get("city_query")) and len(raw.split()) <= 2
    if not rules.is_submit_intent(raw) and not city_only:
        term = rules.extract_search_term(raw)
        if term:
            entities["search_term"] = term
        tokens = rules.extract_search_tokens(raw)
        if tokens:
            entities["search_tokens"] = tokens
        if rules.should_use_city_garage_list(raw, search_term=term):
            city2 = rules.extract_city_from_text(raw)
            if city2:
                entities["city_query"] = city2

    return entities
