# Open damage dataset licenses (CarDD / VehiDE)

**Scope:** AI Tribe insurance **lab / R&D only** on `paperclip-vm` (`/mnt/ml-scratch`).
These datasets are **not** licensed for commercial insurer deployment or live
settlement on `tribe.tradentical.com` without separate written permission from
the rights holders.

Last reviewed: **2026-07-05**.

## Summary

| Dataset | Images | Damage labels | Make/model on damaged photos? | Lab R&D on ml-scratch | Live production POC |
| --- | --- | --- | --- | --- | --- |
| **CarDD** (USTC/CAS) | ~4,000 | 6 classes + instance masks | **No** | OK (NC research) | **Not cleared** |
| **VehiDE** (KSE 2023 / Kaggle mirror) | ~13,945 | 8 classes + segmentation | **No** | OK (NC research) | **Not cleared** |
| **FGVD** (already in use for VMMR) | ~5,502 scenes | Make/model on **intact** cars | Yes (undamaged) | OK (research) | Weights in app tree |
| **VMMR correction queue** (in-app) | Growing | Manual make/model on **damaged** claims | **Yes** (human-reviewed) | `/mnt/ml-scratch/vmmr_corrections/` | Feeds future retrain only |

## CarDD (Car Damage Detection, USTC)

- **Paper:** Wang et al., IEEE TITS 2023 — [project page](https://cardd-ustc.github.io/)
- **License:** Non-commercial **research and educational use only**. CAS/PIC Lab
  retains ownership. **Commercial use requires prior written authorization** from
  PIC Lab (testing commercial systems, ads, resale, broadcast, etc.).
- **Underlying images:** Flickr and Shutterstock — user must comply with those
  platform terms.
- **Access:** Sign licensing form and email PIC Lab (`wangxk0624@mail.ustc.edu.cn`)
  per [CarDD_license.pdf](https://cardd-ustc.github.io/docs/CarDD_license.pdf).
- **GitHub (code + model zoo):** `CarDD-USTC/CarDD-USTC.github.io` — clone for
  inference tooling; dataset zip is separate from the form process.
- **Scratch path:** `/mnt/ml-scratch/cardd/` (see `scripts/damage/prepare_damage_datasets.py`)

## VehiDE (Vehicle Damage Detection)

- **Paper:** Huynh et al., KSE 2023 — [DOI 10.1109/KSE59128.2023.10299490](https://doi.org/10.1109/KSE59128.2023.10299490)
- **License (per paper):** Same NC research/education pattern as CarDD; images
  from Flickr/Shutterstock; faces/plates redacted.
- **Kaggle mirror:** `hendrichscullen/vehide-dataset-automatic-vehicle-damage-detection`
  — convenient for lab download; **does not grant commercial rights** beyond the
  authors' NC terms.
- **Scratch path:** `/mnt/ml-scratch/vehide/`

## Production damage classifier (unchanged)

Live pipeline continues to use **`beingamit99/car_damage_detection`** (Hugging Face).
CarDD/VehiDE are for **offline benchmarking and future segmentation upgrade** only,
behind the same `damage_segmenter.classify_image()` interface.

## Acknowledgement before download

Run `scripts/damage/prepare_damage_datasets.py` on paperclip. It writes
`/mnt/ml-scratch/damage_datasets/LICENSE_ACK.json` — do not populate dataset
directories until a lab operator sets `"acknowledged": true` with name/date, confirming
NC research use only.
