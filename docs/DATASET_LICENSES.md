# Open damage dataset licenses (CarDD / VehiDE)

**Scope:** AI Tribe insurance **lab / R&D only** on `paperclip-vm` (`/mnt/ml-scratch`).
These datasets are **not** licensed for commercial insurer deployment or live
settlement on `tribe.tradentical.com` without separate written permission from
the rights holders.

Last reviewed: **2026-07-05** (VehiDE terms re-checked; CarDD pre-download gate added).

## Summary

| Dataset | Images | Damage labels | Make/model on damaged photos? | Lab R&D on ml-scratch | Live production POC |
| --- | --- | --- | --- | --- | --- |
| **CarDD** (USTC/CAS) | ~4,000 | 6 classes + instance masks | **No** | OK (NC research, **after PIC form**) | **Not cleared** |
| **VehiDE** (KSE 2023 / Kaggle mirror) | ~13,945 | 8 classes + segmentation | **No** | OK (NC research; **downloaded 2026-07-05**) | **Not cleared** |
| **FGVD** (already in use for VMMR) | ~5,502 scenes | Make/model on **intact** cars | Yes (undamaged) | OK (research) | Weights in app tree |
| **VMMR correction queue** (in-app) | Growing | Manual make/model on **damaged** claims | **Yes** (human-reviewed) | `/mnt/ml-scratch/vmmr_corrections/` | Feeds future retrain only |

## CarDD (Car Damage Detection, USTC)

- **Paper:** Wang et al., IEEE TITS 2023 — [project page](https://cardd-ustc.github.io/)
- **Published license ([CarDD_license.pdf](https://cardd-ustc.github.io/docs/CarDD_license.pdf), PIC Lab / CAS):**
  - CarDD is **sole property of PIC Lab**; user acquires no ownership.
  - Permitted: **statistical and scientific research** (research use encouraged).
  - **Prior consent from PIC Lab required** before access (licensing form + email to `wangxk0624@mail.ustc.edu.cn`).
  - **Commercial use prohibited** without prior PIC Lab authorization (includes testing commercial systems, ads, resale, broadcast).
  - **No redistribution** to third parties without PIC Lab authorization.
  - Must cite the CarDD TITS paper when publishing results.
- **Paper addendum ([CarDD.pdf](https://cardd-ustc.github.io/docs/CarDD.pdf)):** Images sourced from **Flickr and Shutterstock**; researcher accepts full responsibility and may use CarDD **only for non-commercial research and educational purposes**, complying with those platform licenses.
- **GitHub (code + model zoo):** `CarDD-USTC/CarDD-USTC.github.io` — clone for inference tooling; **dataset zip is separate** and requires the form process above.
- **Scratch path:** `/mnt/ml-scratch/cardd/` (layout only until form approved)
- **Pre-download gate (2026-07-05):** **Do not request or download CarDD** until PIC Lab terms are reviewed and `LICENSE_ACK.json` is updated with CarDD-specific acknowledgement. VehiDE was downloaded out of order; CarDD must not repeat that gap.

## VehiDE (Vehicle Damage Detection)

- **Paper:** Huynh et al., KSE 2023 — [DOI 10.1109/KSE59128.2023.10299490](https://doi.org/10.1109/KSE59128.2023.10299490)
- **Extended paper:** Hoang et al., *Journal of Information and Telecommunication* 2025 — [DOI 10.1080/24751839.2024.2367387](https://doi.org/10.1080/24751839.2024.2367387)
- **Authoritative published terms (Huynh / Hoang papers, not the Kaggle tag):**
  - Images under **Flickr and Shutterstock** licenses; **copyright remains with those platforms**.
  - Researcher must **comply with Flickr and Shutterstock terms**.
  - Researcher accepts **full responsibility** for use of VehiDE, restricting it **solely to non-commercial research and educational purposes**.
  - Faces and license plates mosaicked or removed.
- **Kaggle mirror:** `hendrichscullen/vehide-dataset-automatic-vehicle-damage-detection` — tagged **Apache 2.0** by the uploader. That tag **conflicts** with the authors' NC terms above. Treat **author-published terms as authoritative**; the Kaggle label does not grant commercial rights or override Flickr/Shutterstock constraints.
- **Personal / lab research use:** Compatible with AI Tribe's **non-commercial lab R&D** on `paperclip-vm` (`/mnt/ml-scratch`). **Not compatible** with live insurer-facing or commercial settlement use without separate permission.
- **Scratch path:** `/mnt/ml-scratch/vehide/` (populated 2026-07-05; retroactive license review recorded in `docs/DEPLOYMENT.md`)

## Production damage classifier (unchanged)

Live pipeline continues to use **`beingamit99/car_damage_detection`** (Hugging Face).
CarDD/VehiDE are for **offline benchmarking and future segmentation upgrade** only,
behind the same `damage_segmenter.classify_image()` interface.

## Acknowledgement before download

Run `scripts/damage/prepare_damage_datasets.py` on paperclip. It writes
`/mnt/ml-scratch/damage_datasets/LICENSE_ACK.json` — do not populate dataset
directories until a lab operator sets `"acknowledged": true` with name/date, confirming
NC research use only.
