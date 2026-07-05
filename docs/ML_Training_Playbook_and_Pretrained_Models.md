# Part 2: Pretrained models, GitHub repositories, and the ML training playbook

This is the companion reference to `Cursor_AI_Prompt_AI_Tribe_Workspace.md`. Paste the relevant repo and model sections into Cursor when you reach milestone 5 (wiring real models into the stubbed pipeline stages). Keep this file in the repo under `docs/` once the workspace is created, it is the record of what was pulled from where and why.

Straight answer to your question first: yes, usable pretrained weights exist for two of the four ML-heavy stages (deepfake screening and damage detection), so you do not need to train those from scratch for the POC. Vehicle make-and-model recognition (VMMR) has no strong ready-to-use public checkpoint for a global vehicle mix, that one genuinely needs fine-tuning, scoped realistically below. Vehicle forensics beyond deepfake screening (error level analysis, metadata checks, perceptual hashing) is algorithmic, not model-based, so there is nothing to train there at all, just code to adapt.

## 1. Deepfake and AI-generated image screening, pretrained, ready to use

**Primary recommendation: `prithivMLmods/Deep-Fake-Detector-v2-Model`** on Hugging Face. Vision Transformer (`google/vit-base-patch16-224-in21k` base), fine-tuned for real-versus-fake binary classification, reports 92 percent accuracy on its validation set. Drop-in with the `transformers` pipeline API:

```python
from transformers import pipeline
detector = pipeline("image-classification", model="prithivMLmods/Deep-Fake-Detector-v2-Model")
result = detector("claim_image.jpg")
# [{'label': 'Realism', 'score': 0.97}, {'label': 'Deepfake', 'score': 0.03}]
```

Install: `pip install transformers torch pillow`. First run downloads the weights (roughly 350MB) and caches them locally, so `scripts/download_models.sh` should pre-warm this cache during setup rather than downloading on first request.

Alternates worth knowing about if you want a second opinion signal or better generalisation on vehicle photos specifically (this model was trained mostly on face-forgery style datasets, so validate it against real damaged-car photos and AI-generated car photos before trusting it fully):
- `prithivMLmods/Deep-Fake-Detector-Model` (earlier version, smaller training set)
- `prithivMLmods/Deepfake-Detect-Siglip2` (SigLIP backbone, alternative architecture for ensembling)
- `ashish-001/deepfake-detection-using-ViT` (smaller community model, useful as a cheap second vote)

Practical note: none of these were trained specifically on AI-generated vehicle damage photos, they are general face/scene deepfake classifiers. Treat the pipeline stage as "did this image show AI-generation artefacts" rather than "is this specific damage photo fake," and plan to fine-tune on your own corpus of real versus AI-generated car images once you have one, see the fine-tuning section below.

## 2. Vehicle damage detection and segmentation, pretrained, ready to use

**Primary recommendation: CarDD (`CarDD-USTC/CarDD-USTC.github.io`)**, the closest thing to an industry-grade open resource for this exact task. It is a peer-reviewed dataset (4,000-plus real annotated car damage images, six categories: dent, scratch, crack, glass shatter, lamp broken, tire flat) with a published Model Zoo of pretrained instance-segmentation checkpoints (Mask R-CNN, Cascade Mask R-CNN, GCNet, HTC, DCN, and their own improved DCN+).

```bash
git clone https://github.com/CarDD-USTC/CarDD-USTC.github.io.git cardd_detection
cd cardd_detection/code/CarDD_detection
pip install openmim
mim install mmdet
pip install mmcv==1.7.0
# download the CarDD dataset and pretrained weights from https://cardd-ustc.github.io/
# (registration/request may be required, follow the site's instructions)
python tools/inference.py \
  --img-path=<path_to_claim_images> \
  --save-path=<output_path> \
  --config-file=configs/car_damage/DCN_plus_cfg.py \
  --checkpoint-file=<downloaded_epoch_24.pth>
```

This is a heavier dependency stack (`mmdetection`, `mmcv`, PyTorch 1.7-era pinning per their documented environment) so vendor it into `backend/app/ml_weights/cardd_detection/` as a subfolder rather than trying to force it into the main FastAPI virtual environment; call it as a subprocess or, better, re-export the model to a plain TorchScript or ONNX artifact once during setup so the FastAPI service only needs a lightweight `torch` runtime for inference, not the full `mmdet` toolchain at request time.

**Faster to integrate for the first working demo: `beingamit99/car_damage_detection`** on Hugging Face. A BEiT-based image classifier fine-tuned to six car damage categories, plug-and-play with `transformers`:

```python
from transformers import pipeline
classifier = pipeline("image-classification", model="beingamit99/car_damage_detection")
result = classifier("claim_image.jpg")
```

This gives you a damage-type classification (not pixel-level segmentation) in about three lines, which is enough to drive the "Mapping damage to vehicle parts" and "Grading damage severity" stages for a first working end-to-end demo. Swap in CarDD's segmentation output later for actual part-level localisation once milestone 6 is stable; keeping both wired behind the same `damage_segmenter.py` interface makes that swap contained.

If you want a single, more capable model that gives a written damage description in one call instead of a raw label, `Kakyoin03/car-damage-assessment-llama-vision` (an 11B parameter Llama-3.2-Vision fine-tune) is worth evaluating, but it is far heavier to run than the two options above and likely overkill for a lab POC on the Oracle ARM VM, keep it as a phase-2 option if you later get access to a GPU-backed inference endpoint.

## 3. Vehicle make and model recognition (VMMR), no strong pretrained option, needs fine-tuning

Nothing found in this research is a ready-to-call pretrained VMMR checkpoint covering a realistic global vehicle mix (most public work is US-market weighted). Two usable starting points to fine-tune from rather than train from zero:

- **`faezetta/VMMRdb`** on GitHub: 9,170 classes, 291,752 images spanning 1950 to 2016, the largest open VMMR dataset available. US-market heavy, so India, GCC and African-market models will be under-represented, plan to supplement.
- **`Nada-Baili/Vehicle-Recognition`** on GitHub: merges VMMRdb with the Stanford Cars and CompCars datasets into 2,522 classes and already implements a working detection-plus-recognition pipeline (YOLO for vehicle detection, a ResNet50 classifier for make/model, SORT for tracking), a good reference architecture even where the weights themselves need retraining.

For the POC, the pragmatic path is transfer learning, not training from scratch: take a `timm` ImageNet-pretrained backbone (EfficientNetV2-S or ResNet50 are good size/accuracy tradeoffs for a lab GPU or even CPU-only inference), replace the classification head, and fine-tune on VMMRdb plus whatever claim photos you can add over time. See the training playbook below for the concrete recipe.

## 4. Vehicle forensics building blocks, algorithmic, no training required

These are classical image-forensics techniques, not machine learning models, so there is nothing to train, only libraries to wire in.

- **`idealo/imagededup`** (`pip install imagededup`): production-grade perceptual, difference, wavelet and average hashing plus CNN-based near-duplicate search. Use this directly for the `phash_reuse.py` stage, hash every incoming claim image and check it against the historical claim image corpus stored in Postgres.
- **`aetilius/pHash`**: the underlying C library several perceptual hashing tools are built on, useful if `imagededup`'s Python implementation proves too slow at scale, not needed for the POC.
- **`CodeRafay/Forensic-Image-Analysis-Toolkit`**: a Streamlit reference implementation combining error level analysis, metadata/EXIF forensics, noise-map analysis, JPEG ghost detection, quantisation-table analysis, copy-move detection and PRNU sensor fingerprinting in one place. Do not depend on this repo directly, it is a desktop analyst tool, but lift the ELA and metadata-forensics algorithms out of it into your own `ela.py` and `metadata_forensics.py` service functions, they are well-documented, self-contained image-processing routines (PIL/OpenCV/numpy level), not trained models.
- **VIN decoding**: `Wal33D/nhtsa-vin-decoder` (MIT licensed) wraps the free NHTSA vPIC API (`https://vpic.nhtsa.dot.gov/api/`) and includes an offline WMI (World Manufacturer Identifier) database. The WMI/ISO 3779 structural decode works globally even though NHTSA's deep attribute data is US-market only, use it for the VIN-format validation and manufacturer-identification part of `vehicle_id.py`, not as your only make/model source.

## 5. Seed parts catalogue for the POC

For a working demo you do not need the full Autorox integration yet, seed `data/parts_seed/india_parts_seed.csv` with a small, manually curated set (200 to 500 rows is enough for a demo across 5 to 10 common Indian models: Maruti Swift, Hyundai i20, Tata Nexon, Honda City, Mahindra XUV, etc, covering bumpers, doors, headlamps, windshields, fenders, mirrors) with columns `make, model, part_name, part_number, price_inr, labor_hours`. Wire the real Autorox SparesCatalog API in as a second `parts_matcher` backend behind the same interface once the lab is ready to move past the seed data, this keeps the swap contained to one file.

---

## The ML training playbook

### Principle: use pretrained first, fine-tune only where you must

Of the four ML-heavy stages, deepfake screening and damage classification have workable pretrained models today (section 1 and 2 above). Only VMMR needs real fine-tuning work for this POC. Do not start a training pipeline before confirming the pretrained option genuinely fails on your own sample images, several hours of evaluation against a few dozen real claim photos will tell you that faster than a training run will.

### Step 1: build an evaluation set before touching training code

Collect 50 to 100 real damaged-vehicle photos (your own claim archive if available, or a mix of the CarDD test split and manually sourced images) and hand-label them for whatever you intend to fine-tune. This small labelled set is what tells you whether the pretrained models from sections 1 and 2 are good enough as-is, and it becomes your held-out test set later regardless of what you fine-tune.

### Step 2: VMMR fine-tuning recipe

1. Start from VMMRdb (section 3) as the base training set, add any of your own labelled vehicle photos, weighted higher during training since they represent your actual target distribution (Indian and GCC market vehicles).
2. Use a `timm` pretrained backbone (`efficientnetv2_s` or `resnet50`, both have solid CPU inference speed for a lab demo) rather than training from random initialisation, this is standard transfer learning and will converge in a fraction of the time and data a from-scratch model needs.
3. Freeze the backbone for the first few epochs, train only the new classification head, then unfreeze the last block or two and fine-tune end to end at a lower learning rate, this two-phase approach avoids destroying the pretrained features early on when the new head is still poorly calibrated.
4. Track top-1 and top-5 accuracy separately, top-5 matters more for this application than it sounds: if the model's second guess is right, a human surveyor correcting a single dropdown is a far smaller UX cost than a wrong estimate silently going out.
5. Log every training run's dataset version, hyperparameters, and metrics into a simple Postgres `model_runs` table (run_id, model_name, dataset_version, metrics JSONB, weights_path, created_at) rather than tracking it only in file names, this is the lightest version of a model registry that is still genuinely useful later.

### Step 3: domain-adapting the damage models over time

Both the deepfake detector and the damage classifier are pretrained on datasets that do not perfectly match your real distribution (face-forgery datasets for deepfake, a mostly-Western vehicle mix for CarDD and beingamit99). Do not fine-tune either on day one. Instead, run them as-is against real claim photos as they arrive, log every prediction alongside the eventual human surveyor's verdict (agree, override, and why) into the `damage_detections` and `pipeline_events` tables you already have, and only fine-tune once you have a few hundred of these labelled disagreement cases. That disagreement log is a far more valuable and cheaper-to-collect training set than trying to build a labelled dataset from scratch, and it directly targets the cases where the pretrained model is actually wrong for your market.

**Lab benchmark (paperclip-vm):** CarDD and VehiDE may be staged on `/mnt/ml-scratch` for offline top-1 evaluation of `beingamit99/car_damage_detection` — see `docs/DATASET_LICENSES.md` and `scripts/damage/prepare_damage_datasets.py` + `eval_damage_classifier.py`. Neither dataset is license-cleared for live commercial deployment; the live app keeps the HF classifier until a segmentation upgrade (CarDD model zoo) is separately evaluated.

### Step 4: labelling tooling, if and when you do need to hand-label

Use **Label Studio** (open source, `pip install label-studio`, runs locally) or **CVAT** (Computer Vision Annotation Tool, open source, self-hostable) for any bounding-box or segmentation-mask labelling you end up doing for the damage model. Both integrate cleanly with a local Postgres-backed workflow and neither requires a cloud account.

### Step 5: evaluation discipline

For every model in the pipeline, hold out a fixed test set that is never touched during training or fine-tuning, and report accuracy (and top-5 accuracy for VMMR) against that same set every time you retrain, so numbers are comparable run over run. For the fraud and forensic stages, track false positive rate specifically, not just accuracy, a system that flags too many genuine claims as suspicious will get switched off by frustrated surveyors faster than one that occasionally misses something, and that tradeoff is worth making explicit and tunable (a single risk-threshold config value, not buried in code) rather than fixed.

### Step 6: what to tell a CXO audience about this

Be precise about what is genuinely pretrained-and-verified versus what is fine-tuned-in-progress when you demo this. "Deepfake screening and damage classification run on published, benchmarked models we've validated against our own sample set, vehicle recognition is in active fine-tuning against an Indian-market dataset" is a credible, specific claim a technical buyer will trust. Claiming everything is production-grade when two of five models are pretrained-as-is and one is a work in progress is exactly the kind of overreach that gets a lab build dismissed the moment someone asks a follow-up question.
