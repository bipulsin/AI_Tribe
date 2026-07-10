"""Embedding nearest-neighbour chat intent classifier with rule fallback."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from app.services.chat import intent_rules as rules
from app.services.chat.nlu.embedder import embed_texts, get_embedder
from app.services.chat.nlu.entities import extract_entities
from app.services.chat.nlu.examples import prototype_examples

logger = logging.getLogger("ai_tribe.chat_nlu")

OFF_TOPIC_REDIRECT = (
    "I can help with submitting or looking up claims — let's stick to that. "
    "What would you like to do?"
)

CLARIFY_MESSAGE = (
    "I'm not sure whether you want to **submit a new claim** or **look up an existing one**. "
    "Could you clarify? For example: “Submit a claim” or “Find claim CLM-2026-000026”."
)

LOOKUP_NEED_IDENTIFIER = (
    "Which claim? Give me a claim number, garage name, or surveyor name"
)

# Cosine similarity thresholds for MiniLM prototypes (normalized embeddings).
_MIN_SCORE = 0.38
_MIN_MARGIN = 0.04


@dataclass
class NluResult:
    intent: str
    entities: dict = field(default_factory=dict)
    confidence: float = 0.0
    margin: float = 0.0
    source: str = "rules"  # embedding | rules | byok | hybrid
    scores: dict[str, float] = field(default_factory=dict)


_proto_lock = threading.Lock()
_proto_labels: list[str] | None = None
_proto_matrix: np.ndarray | None = None
_proto_root: Path | None = None


def _nlu_root_from_settings() -> Path:
    from app.core.config import get_settings

    return get_settings().chat_nlu_path


def _ensure_prototypes(root: Path) -> bool:
    global _proto_labels, _proto_matrix, _proto_root
    with _proto_lock:
        if _proto_matrix is not None and _proto_root == root:
            return True
        if get_embedder(root) is None:
            return False

        examples = prototype_examples()
        labels: list[str] = []
        texts: list[str] = []
        for intent, phrases in examples.items():
            for phrase in phrases:
                labels.append(intent)
                texts.append(phrase)

        matrix = embed_texts(root, texts)
        if matrix is None or matrix.size == 0:
            return False

        cache_dir = root / "cache"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                cache_dir / "prototypes.npz",
                matrix=matrix,
                labels=np.array(labels, dtype=object),
            )
        except OSError as exc:
            logger.debug("Could not cache prototypes: %s", exc)

        _proto_labels = labels
        _proto_matrix = matrix
        _proto_root = root
        logger.info(
            "Chat NLU: built %d prototypes across %d intents",
            len(labels),
            len(examples),
        )
        return True


def _score_message(root: Path, text: str) -> tuple[str, float, float, dict[str, float]] | None:
    if not _ensure_prototypes(root):
        return None
    assert _proto_matrix is not None and _proto_labels is not None

    query = embed_texts(root, [text])
    if query is None:
        return None
    sims = (_proto_matrix @ query[0]).astype(np.float32)

    # Best score per intent.
    best: dict[str, float] = {}
    for label, score in zip(_proto_labels, sims.tolist()):
        prev = best.get(label)
        if prev is None or score > prev:
            best[label] = float(score)

    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return None
    top_intent, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = float(top_score - second)
    return top_intent, float(top_score), margin, best


def _confident(score: float, margin: float) -> bool:
    return score >= _MIN_SCORE and margin >= _MIN_MARGIN


def _rules_result(
    text: str,
    *,
    draft_active: bool,
    llm_classify: Callable[[str], tuple[str | None, dict]] | None,
) -> NluResult:
    intent, entities = rules.classify_intent(
        text, draft_active=draft_active, llm_classify=None
    )
    # rules.classify_intent historically returned general for weak matches;
    # do not call BYOK inside rules when we orchestrate it here.
    return NluResult(intent=intent, entities=entities, confidence=1.0, source="rules")


def classify_message(
    text: str,
    *,
    draft_active: bool = False,
    llm_classify: Callable[[str], tuple[str | None, dict]] | None = None,
    root: Path | None = None,
) -> NluResult:
    """Classify chat intent via embeddings, with rule + optional BYOK fallback.

    Policy:
    - Local MiniLM is the baseline for everyone (BYOK not required).
    - Rule-based intent_rules is always available as fallback and for draft gates.
    - BYOK LLM is consulted only when both embedding and rules are uncertain
      (ambiguous / general with no entities) — never for deepfake/VMMR/damage.
    """
    raw = (text or "").strip()
    if not raw:
        return NluResult(intent="clarify", source="rules", confidence=0.0)

    nlu_root = root or _nlu_root_from_settings()
    entities = extract_entities(raw, root=nlu_root)

    # Hard gates from the last few hours of product work — never skip these.
    lower = raw.lower()
    if draft_active and any(phrase in lower for phrase in rules._DONE_PHRASES):
        return NluResult(intent="done", entities=entities, confidence=1.0, source="rules")

    # "claim submitted by X" / "X's claim" is always lookup — before submit keyword gates.
    actor = rules.extract_actor_name(raw)
    if actor:
        entities["actor_name"] = actor
        entities["search_term"] = actor
        return NluResult(
            intent="lookup_claim", entities=entities, confidence=1.0, source="rules"
        )

    if rules.is_submit_intent(raw):
        if entities.get("city_query") is None:
            city = rules.extract_city_from_text(raw)
            if city:
                entities["city_query"] = city
        return NluResult(
            intent="submit_claim", entities=entities, confidence=1.0, source="rules"
        )

    if draft_active:
        if rules._is_explicit_lookup(raw, entities):
            return NluResult(
                intent="lookup_claim", entities=entities, confidence=1.0, source="rules"
            )
        return NluResult(
            intent="submit_claim", entities=entities, confidence=1.0, source="rules"
        )

    # High-precision claim reference / suffix → lookup without needing embeddings.
    if entities.get("claim_reference") or entities.get("claim_suffix"):
        return NluResult(
            intent="lookup_claim", entities=entities, confidence=1.0, source="rules"
        )

    # Bare / vague tokens must not be forced into lookup.
    if re.fullmatch(r"claims?", lower) or lower in {
        "insurance",
        "help",
        "hi",
        "hello",
        "hey",
    }:
        return NluResult(intent="clarify", entities=entities, confidence=0.0, source="rules")

    from app.core.config import get_settings

    settings = get_settings()
    use_embedding = settings.chat_nlu_enabled

    emb: NluResult | None = None
    if use_embedding:
        scored = _score_message(nlu_root, raw)
        if scored is not None:
            intent, score, margin, score_map = scored
            emb = NluResult(
                intent=intent,
                entities=entities,
                confidence=score,
                margin=margin,
                source="embedding",
                scores=score_map,
            )

    def _lookup_anchored(ents: dict) -> bool:
        return rules.has_concrete_lookup_identifier(raw, ents)

    if emb is not None and _confident(emb.confidence, emb.margin):
        # Merge lookup entities when embedding says lookup.
        if emb.intent == "lookup_claim":
            # Explicit lookup phrasing without an identifier still routes as lookup;
            # the handler asks which claim — never invents one.
            if rules._is_explicit_lookup(raw, entities) or _lookup_anchored(entities):
                return emb
            return NluResult(
                intent="clarify",
                entities=entities,
                confidence=emb.confidence,
                margin=emb.margin,
                source="clarify",
                scores=emb.scores,
            )
        elif emb.intent == "submit_claim":
            return emb
        elif emb.intent == "done":
            return emb
        elif emb.intent == "off_topic":
            return emb
        elif emb.intent == "general":
            if _lookup_anchored(entities):
                return NluResult(
                    intent="lookup_claim",
                    entities=entities,
                    confidence=emb.confidence,
                    margin=emb.margin,
                    source="hybrid",
                    scores=emb.scores,
                )
            return emb

    # Low confidence or embedding unavailable → deterministic rules.
    ruled = _rules_result(raw, draft_active=False, llm_classify=None)
    ruled.entities = {**entities, **ruled.entities}

    if ruled.intent in {"submit_claim", "lookup_claim", "done"}:
        if ruled.intent == "lookup_claim":
            if not (
                rules.has_concrete_lookup_identifier(raw, ruled.entities)
                or rules._is_explicit_lookup(raw, ruled.entities)
            ):
                return NluResult(
                    intent="clarify",
                    entities=ruled.entities,
                    confidence=emb.confidence if emb else 0.0,
                    margin=emb.margin if emb else 0.0,
                    source="clarify",
                    scores=emb.scores if emb else {},
                )
        if emb is not None:
            ruled.source = "hybrid"
            ruled.confidence = emb.confidence
            ruled.margin = emb.margin
            ruled.scores = emb.scores
        return ruled

    # Both uncertain → optional BYOK as a last signal, then clarify.
    if llm_classify is not None:
        try:
            llm_intent, llm_entities = llm_classify(raw)
            if llm_intent in {"submit_claim", "lookup_claim"}:
                merged = {**entities, **(llm_entities or {})}
                return NluResult(
                    intent=llm_intent,
                    entities=merged,
                    confidence=0.5,
                    source="byok",
                )
            if llm_intent == "general":
                # Treat BYOK "general" as claims-help only if message mentions claims.
                if "claim" in lower:
                    return NluResult(
                        intent="general",
                        entities={**entities, **(llm_entities or {})},
                        confidence=0.5,
                        source="byok",
                    )
        except Exception:
            pass

    if emb is not None and emb.intent == "off_topic" and emb.confidence >= _MIN_SCORE:
        return emb

    # Ambiguous — ask rather than guess.
    return NluResult(
        intent="clarify",
        entities=entities,
        confidence=emb.confidence if emb else 0.0,
        margin=emb.margin if emb else 0.0,
        source="clarify",
        scores=emb.scores if emb else {},
    )
