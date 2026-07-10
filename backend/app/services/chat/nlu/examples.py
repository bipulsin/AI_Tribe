"""Prototype utterances for embedding-based chat intent classification.

Seeded from the rule-based phrases in intent_rules.py (submit/lookup/done) plus
paraphrases and off-topic / general-help examples. These are the "training"
examples for nearest-neighbour classification — not a fine-tuned model.
"""

from __future__ import annotations

from app.services.chat import intent_rules as rules

# Extra paraphrases beyond the literal rule phrases.
_SUBMIT_EXTRA = (
    "I need to file a motor claim",
    "please help me register damage claim",
    "want to lodge a new insurance claim",
    "upload damage photos for a new claim",
    "start a fresh claim with pictures",
    "submit a new claim with image",
    "submit a new claim with photo",
    "I have accident photos to submit",
    "create a claim for my damaged car",
    "register vehicle damage claim",
    "file claim for car accident",
    "open new claim and assess damage",
)

_LOOKUP_EXTRA = (
    "show me claim CLM-2026-000026",
    "what is the status of my claim",
    "look up claim number 26",
    "find claims from Pune",
    "claims at Kochi garage",
    "show claims by surveyor Ramesh",
    "search existing claim for garage",
    "details of claim submitted last week",
    "find my earlier claim",
    "get claim details for Thane workshop",
    "claims related to Ahmedabad",
    "show me an existing claim",
)

_DONE_EXTRA = (
    "that's everything",
    "all set please submit",
    "ready go ahead and assess",
    "finish and submit the claim",
)

_GENERAL_EXTRA = (
    "how does claim assessment work",
    "what photos do I need for a claim",
    "help me with motor claims",
    "what can you do in this chat",
    "explain the estimate process",
    "how many images can I upload",
    "what is a surveyor in a claim",
)

_OFF_TOPIC_EXTRA = (
    "what's the weather in Mumbai today",
    "tell me a joke",
    "who won the cricket match",
    "write me a python function",
    "recipe for pasta",
    "book a flight to Delhi",
    "play some music",
    "what is the capital of France",
    "help me with my homework",
    "stock market tips",
    "translate this to Spanish",
    "how do I reset my wifi router",
)


def _unique(phrases: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for phrase in phrases:
        key = phrase.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(phrase.strip())
    return out


def prototype_examples() -> dict[str, list[str]]:
    """Return intent → example utterances used to build the prototype bank."""
    return {
        "submit_claim": _unique(list(rules._SUBMIT_PHRASES) + list(_SUBMIT_EXTRA)),
        "lookup_claim": _unique(list(rules._LOOKUP_PHRASES) + list(_LOOKUP_EXTRA)),
        "done": _unique(list(rules._DONE_PHRASES) + list(_DONE_EXTRA)),
        "general": _unique(list(_GENERAL_EXTRA)),
        "off_topic": _unique(list(_OFF_TOPIC_EXTRA)),
    }
