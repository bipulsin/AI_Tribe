# Deployment notes

## Status

**Live at https://tribe.tradentical.com** (deployed 2026-07-03/04 on paperclip-vm).

The live deployment runs **`ML_MODE=stub`** (no torch/transformers in the image).
Local development and Milestone 5 live-model verification on the laptop are
separate; host ML caches were removed after the ML_MODE retrofit.

## Local vs live ML

| Path | How | ML_MODE | Dependencies |
| --- | --- | --- | --- |
| Local laptop / default compose | `pip install -r backend/requirements.txt` or `docker compose -p ai_tribe up` | `stub` | No torch / transformers |
| Live models on paperclip-vm | See “Switching to ML_MODE=live” below | `live` | `requirements-ml.txt` |

Never install `requirements-ml.txt` or run `scripts/download_models.sh` on a
developer laptop as the default workflow.

## paperclip-vm access

```bash
ssh paperclip echo connected
# → connected
```

| Field | Value |
| --- | --- |
| Host | `paperclip` |
| HostName | `140.245.14.17` |
| User | `ubuntu` |
| IdentityFile | `~/.ssh/paperclip_key` |

## Live deployment topology

| Item | Value |
| --- | --- |
| Compose project | `ai_tribe` (`docker compose -p ai_tribe`) |
| Directory | `/opt/stack/ai_tribe/` |
| App container | `ai_tribe_app` |
| DB container | `ai_tribe_db` (Postgres 17, **isolated**) |
| App internal port | **8000** (not published on the host) |
| App networks | `ai_tribe_internal` (to reach `db`) **and** external `stack_web` (for Caddy) |
| DB networks | `internal` only — **not** on `stack_web` |
| ML mode | **`stub`** (`Dockerfile`, `requirements.txt` only) |
| Admin auth | `ADMIN_PASSWORD` **required** (`APP_ENV=production`); stored in `/opt/stack/ai_tribe/.env` (mode 600), not in git |

```
                    ┌──────────── stack_web (external) ────────────┐
                    │                                              │
  Internet ──► caddy ──► ai_tribe_app:8000                         │
                    │         │                                    │
                    │         │ internal network only              │
                    │         ▼                                    │
                    │    ai_tribe_db:5432                          │
                    │    (not on stack_web)                        │
                    └──────────────────────────────────────────────┘
```

Caddy does **not** publish the app port; it reaches `ai_tribe_app` by container
name on `stack_web`, same pattern as `paperclip:3100`.

### Caddy

| Item | Value |
| --- | --- |
| Live config | `/opt/stack/caddy/Caddyfile` |
| Backup | `/opt/stack/caddy/Caddyfile.bak.20260703` |
| Validate | `docker exec caddy caddy validate --config /etc/caddy/Caddyfile` |
| Reload | `docker exec caddy caddy reload --config /etc/caddy/Caddyfile` |

Site block added:

```caddy
tribe.tradentical.com {
    reverse_proxy ai_tribe_app:8000
    encode gzip
}
```

### Admin password (live)

- Local dev: still seeds `admin` / `admin` when `ADMIN_PASSWORD` is unset.
- Production (`APP_ENV=production`): **`ADMIN_PASSWORD` is required**; boot fails without it.
- On first boot with `ADMIN_PASSWORD` set, if the admin user still has the seeded
  default password, it is rotated automatically.
- Live secret lives only in `/opt/stack/ai_tribe/.env` (and the compose env).
  Do not commit it.

### Redeploy / update code

```bash
ssh paperclip
cd /opt/stack/ai_tribe
git pull origin main
docker compose -p ai_tribe up -d --build
```

### Switching to ML_MODE=live (when ready)

Build and run the ML image **on the VM** (native ARM), not under laptop emulation:

```bash
cd /opt/stack/ai_tribe
# Ensure ADMIN_PASSWORD remains set in .env / compose
docker compose -p ai_tribe --profile ml up -d --build app_ml
# Then point Caddy at ai_tribe_app_ml:8000 (or replace the app service with Dockerfile.ml)
```

Today the live site uses the stub `app` service only. Bringing up `app_ml` requires
joining it to `stack_web` and updating the Caddy upstream if the container name changes.

## VMMR (FGVD-7 fine-tune)

Training and crops live on the **`/mnt/ml-scratch`** volume only (not root disk).
The app loads weights from **`backend/app/ml_weights/vmmr/`** inside the deploy
tree — that copy is enough to run without `/mnt/ml-scratch` mounted.

| Item | Value |
| --- | --- |
| Dataset | FGVD (IDD) crops, 80/20 per-class held-out |
| Checkpoint | `backend/app/ml_weights/vmmr/vmmr_resnet50_fgvd8.pt` (also in Docker volume `ai_tribe_ml_weights`) |
| Meta / metrics | `backend/app/ml_weights/vmmr/meta.json` |
| Scratch run | `/mnt/ml-scratch/vmmr_runs/20260704T072651Z/` (prior 7-class: `20260703T214155Z`) |
| Accept rule | margin ≥ **0.30** **and** predicted class tier = **reliable** → `identity_confirmed`, `pricing_basis=confirmed` |
| Low-confidence tier (margin OK) | Keep specific guess; `identity_confirmed=false`, vehicle `pricing_basis=needs_confirmation` (surveyor must confirm) |
| Below margin | ImageNet-transfer path, `pricing_basis=provisional_fallback` |
| Same-make catalog miss | Exact model has no catalogue rows → price via **same-make only** substitute (never cross-brand); estimate `pricing_basis=model_fallback_priced`, `fallback_source_model` records the substitute (e.g. XUV500 → XUV700). Loud “Approximate pricing” banner names both vehicles. |
| Both identity + catalog uncertainty | `needs_confirmation` **and** `model_fallback_priced` banners both show — independent signals. |

### Class reliability tiers (on top of margin gate)

| Tier | Classes | Auto-finalize when margin OK? |
| --- | --- | --- |
| **reliable** | Swift, Innova, i20 | Yes (`pricing_basis=confirmed`) |
| **low_confidence** | Creta, Baleno, City, Kwid, **XUV500** (forced) | No — `needs_confirmation` even at high margin |
| **provisional only** | Nexon, XUV700, Seltos | Never (no class in head) |

`needs_confirmation` is distinct from `provisional_fallback`: the model made a
specific catalogue guess, but that class is not trusted enough to skip surveyor
review. `provisional_fallback` means no usable fine-tuned identity (low margin or
untrained class shape).

#### Known residual risk (not fixed by tier gating)

A **real City** (or Baleno/Creta/Kwid) **misclassified as Swift/Innova/i20** still
auto-finalizes, because the *predicted* class is reliable-tier. Tier gating only
blocks auto-trust when the model lands on a low_confidence class; it does not
catch the reverse confusion. That needs more City (and peer) training images, not
a post-hoc gate. Observed example: held-out City crop `test_5091_3.jpg` predicts
Maruti Swift at high margin (~0.84) and remains `pricing_basis=confirmed`.

### Catalog models: trained vs provisional-only

| Catalog model | FGVD source images | Tier / status | Parts catalogue |
| --- | --- | --- | --- |
| Maruti Swift | ~451 | **reliable** | Exact seed rows |
| Toyota Innova | ~500 | **reliable** | Exact seed rows |
| Hyundai i20 | ~123 | **reliable** | Exact seed rows |
| Hyundai Creta | ~107 | **low_confidence** | Exact seed rows |
| Maruti Baleno | ~91 | **low_confidence** | Exact seed rows |
| Honda City | ~84 | **low_confidence** | Exact seed rows |
| Renault Kwid | ~23 | **low_confidence** | Exact seed rows |
| **Mahindra XUV500** | **64** (`car_Mahindra_XUV500`) | **low_confidence** (forced) | **No exact rows** — same-make fallback to **XUV700** with `model_fallback_priced` disclosure |
| Tata Nexon | 2 (unused) | **Provisional only** | Exact seed rows (identity never confirmed) |
| Mahindra XUV700 | 0 | **Provisional only** | Exact seed rows (identity never confirmed from VMMR) |
| Kia Seltos | 0 | **Provisional only** | Exact seed rows |

XUV500 has no Autorox/live pricing integration yet; seed catalogue only has XUV700.
Estimates for identified XUV500 use XUV700 unit prices with an explicit
“Approximate pricing” banner naming both models.

Training used inverse-frequency `WeightedRandomSampler` + class-weighted CE, with
stronger augmentation on Kwid / City / Creta / Baleno.

### Held-out per-class top-1 (run `20260703T214155Z`, margin gate not applied)

Overall top-1 **66.7%** on n=276 is dominated by Swift/Innova — **do not use alone**.

| Class | n_test | top-1 | margin mean / p50 | Reliable? |
| --- | --- | --- | --- | --- |
| Maruti_Swift | 90 | 67.8% | 0.53 / 0.52 | yes |
| Toyota_Innova | 100 | 74.0% | 0.55 / 0.59 | yes |
| Hyundai_i20 | 25 | 68.0% | 0.69 / 0.85 | yes |
| Hyundai_Creta | 21 | 47.6% | 0.43 / 0.39 | weak / small |
| Maruti_Baleno | 18 | 61.1% | 0.60 / 0.54 | **no** (<100 source) |
| Honda_City | 17 | 52.9% | 0.51 / 0.49 | **no** (<100 source) |
| Renault_Kwid | 5 | 40.0% | 0.51 / 0.42 | **no** — near guessing on 5 images |

FGVD-8 held-out (run `20260704T072651Z`): overall top-1 **61.9%** on n=289.
XUV500: **61.5%** on n_test=13 (not meaningful; forced `low_confidence`).
Correct-prediction margin p25≈0.30, p50≈0.68 → **threshold 0.30**.

Smoke (informative): real City crops often accept with high margin; City-adjacent
Baleno crops did not falsely confirm as City; low-margin cases fall through to
provisional ImageNet transfer. City results are informative only (~82 source images).

Retrain / redeploy weights:

```bash
# prepare + train write only under /mnt/ml-scratch
python scripts/vmmr/prepare_fgvd_subset.py
python scripts/vmmr/train_fgvd_vmmr.py
# copy into app tree and retune margin from held-out
python scripts/vmmr/deploy_and_smoke.py
```

### Manual VMMR correction queue (damaged-vehicle retrain path)

When VMMR cannot reliably identify a vehicle (or extensive-damage signals fire),
the pipeline pauses at **`paused_awaiting_vehicle_confirmation`**. The surveyor
enters make/model manually; each correction is logged to **`vmmr_correction_queue`**
with `identity_source=manual_entry` on the vehicle row.

| Item | Value |
| --- | --- |
| Queue table | `vmmr_correction_queue` (claim_id, image_paths, confirmed_make/model, submitted_by, used_in_training) |
| Scratch copies | `/mnt/ml-scratch/vmmr_corrections/<claim_id>/` (never root disk) |
| Admin summary | `GET /api/admin/vmmr-corrections/summary` (admin session only) |
| Retrain trigger | **Manual only** — same as FGVD-8; no automatic retrain at any threshold |

**Scratch directory setup (required on paperclip-vm):** The `app_ml` container runs as
`appuser` (uid **1000**). On first deploy — and after any rebuild that adds the
ml-scratch bind mount — create the corrections root on the **host** with write access
for that uid:

```bash
sudo mkdir -p /mnt/ml-scratch/vmmr_corrections \
  /mnt/ml-scratch/cardd /mnt/ml-scratch/vehide \
  /mnt/ml-scratch/damage_eval /mnt/ml-scratch/damage_datasets
sudo chown -R 1000:1000 /mnt/ml-scratch/vmmr_corrections \
  /mnt/ml-scratch/cardd /mnt/ml-scratch/vehide \
  /mnt/ml-scratch/damage_eval /mnt/ml-scratch/damage_datasets
sudo chmod -R 775 /mnt/ml-scratch/vmmr_corrections \
  /mnt/ml-scratch/cardd /mnt/ml-scratch/vehide \
  /mnt/ml-scratch/damage_eval /mnt/ml-scratch/damage_datasets
docker exec ai_tribe_app_ml test -w /mnt/ml-scratch/vmmr_corrections && echo OK
```

Without this, manual vehicle confirmations still log queue rows in Postgres but
`scratch_image_paths` stays null (Permission denied on copy). Upload originals remain
in `claim_images.image_paths`; scratch copies are the retrain assembly path on
`/mnt/ml-scratch` only.

**Important:** Corrections do **not** update the live model in real time. They
accumulate into a human-reviewed queue for a **deliberate, periodically initiated**
retrain — the only practical path to fine-tune VMMR on **damaged** vehicles, since
FGVD and other public sets label intact cars only.

**Minimum before a meaningful retrain:** use the same bar as the original ML
playbook — roughly **80–150 images per class** (uneven counts are fine, but a
handful of claims does not move held-out accuracy). This is a slow-accumulating
asset, not an instant fix.

**Open-dataset check (2026-07):** CarDD, CDDM, and TQVCD provide damage-type /
component labels on damaged photos but **no make/model labels**. FGVD provides
make/model on **undamaged** traffic-scene crops only. No usable public dataset
combines severe collision imagery with per-image make/model ground truth was
found — the correction queue remains the intended in-production data path.

See **`docs/DATASET_LICENSES.md`** for CarDD/VehiDE non-commercial terms and
scratch paths. Lab prep:

```bash
# on paperclip-vm only — writes under /mnt/ml-scratch
python scripts/damage/prepare_damage_datasets.py
# after LICENSE_ACK.json acknowledged and VehiDE/CarDD extracted:
python scripts/damage/build_vehide_manifest.py --root /mnt/ml-scratch/vehide/raw
python scripts/damage/eval_damage_classifier.py --root /mnt/ml-scratch/vehide/raw --split val
```

**Dataset license record (2026-07-05):** VehiDE author terms confirmed NC research/education only (Flickr/Shutterstock underlying; Kaggle Apache tag overridden) — approved for personal non-commercial lab use on ml-scratch; download predates this check and is now on record. CarDD: PIC Lab terms confirmed NC research with prior consent required — **do not download until licensing form is submitted and acknowledged in LICENSE_ACK.json**.

### Known live-model weaknesses (damage classifier)

Live pipeline uses **`beingamit99/car_damage_detection`** (`damage_segmenter.classify_image()`).
Each image gets a single top-1 damage class, then a hardcoded part via `PART_FOR_DAMAGE`
(e.g. crack → Rear Bumper, scratch → Front Door, dent → Front Bumper).

**VehiDE val benchmark (2026-07-05, 2,161 scored images):** overall top-1 **57.9%**.
Per-class crack recall **2.0% (2/102)** — the model almost never emits `crack` on
VehiDE puncture/crack-labeled images. In production today, true crack damage is
therefore likely mislabeled as dent, scratch, etc., and mapped to the wrong part.
**Crack detection is effectively non-functional per VehiDE benchmark; treat any
`crack` label with skepticism.** No fix in this release — future work should apply
an uncertainty / needs-confirmation pattern at the damage-type level (similar to VMMR).

Benchmark report: `/mnt/ml-scratch/damage_eval/runs/eval_raw_20260705T141711Z.json`

## Co-located stacks (must remain untouched)

| Name | Role |
| --- | --- |
| `caddy`, `paperclip`, `postgres` | Paperclip stack on `stack_web` |
| `twcto-*` | Separate TWCTO compose project |

Never restart `/opt/stack/docker-compose.yml` for AI Tribe changes. Only
`caddy reload` and `docker compose -p ai_tribe ...`.

## DNS

| Check | Result |
| --- | --- |
| VM public IP | `140.245.14.17` |
| `tribe.tradentical.com` | `140.245.14.17` |
| `paperclip.tradentical.com` | `140.245.14.17` |

## ARM image builds

| Image | Dockerfile | Where to build |
| --- | --- | --- |
| Stub app | `Dockerfile` | Built natively on paperclip-vm (done) |
| Live ML | `Dockerfile.ml` | Build natively on paperclip-vm when enabling live ML |

## Rollback (if needed)

```bash
# Restore Caddy
cp /opt/stack/caddy/Caddyfile.bak.20260703 /opt/stack/caddy/Caddyfile
docker exec caddy caddy validate --config /etc/caddy/Caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile

# Remove AI Tribe stack (does not touch Paperclip/TWCTO)
cd /opt/stack/ai_tribe
docker compose -p ai_tribe down
```
