# Chat NLU (local intent understanding)

## Purpose

Lightweight **chat message understanding** for AI Tribe: classify whether the user
wants to submit a claim, look up a claim, ask a claims-related question, or is
off-topic — then extract entities (claim ref, city, garage, surveyor, date).

This does **not** replace or touch BYOK for deepfake, VMMR, damage assessment, or
estimate assist. Those pipelines are unchanged.

## Models (on `/mnt/ml-scratch` only)

| Asset | Path |
| --- | --- |
| Root | `/mnt/ml-scratch/chat_nlu` |
| MiniLM | `…/models/all-MiniLM-L6-v2` (~80MB) |
| spaCy small | `…/models/en_core_web_sm` |
| Prototype cache | `…/cache/prototypes.npz` |

Download (checks free space first):

```bash
ssh paperclip
docker exec -u root ai_tribe_app_ml python /app/scripts/chat_nlu/download_models.py
# or on host with venv that has sentence-transformers + spacy
python scripts/chat_nlu/download_models.py
```

## How classification works

1. **Hard gates** from `intent_rules.py` (the phrase/keyword work from recent
   chat fixes): submit keywords, active-draft city/garage replies, claim
   references. These always win so flows like “Thane” during submit never
   become a claim search.
2. **Embedding classifier**: `all-MiniLM-L6-v2` embeds the message and scores
   nearest prototype utterances. Prototypes are seeded from the same rule
   phrases plus paraphrases / off-topic / general-help examples
   (`nlu/examples.py`).
3. **Confidence**: if top score and margin are below thresholds → do not guess.
4. **Rule fallback**: full `intent_rules.classify_intent` when embeddings are
   unavailable or low-confidence.
5. **BYOK (optional, chat only)**: consulted **only** when both embedding and
   rules are uncertain. Never overrides a confident local decision. Unused for
   deepfake / VMMR / damage / estimate.

## Intents returned to the handler

| Intent | Behaviour |
| --- | --- |
| `submit_claim` | Guided submit flow |
| `lookup_claim` | Claim search |
| `done` | Finish in-progress draft |
| `general` | Short claims-help prompt |
| `off_topic` | Polite redirect to claims topics |
| `clarify` | Ask submit vs lookup — no forced guess |

## Env

```bash
CHAT_NLU_ENABLED=true
CHAT_NLU_ROOT=/mnt/ml-scratch/chat_nlu
```

If models are missing, the app stays up and uses **rules only**.

## Verify

```bash
docker exec ai_tribe_app_ml python /app/scripts/chat_nlu/verify_nlu.py
```
