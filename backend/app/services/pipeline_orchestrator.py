"""Pipeline orchestrator — stub stages in Milestone 4, real models in Milestone 5."""

from __future__ import annotations

# Stage sequence and user-facing labels (exact strings from the product brief).
PIPELINE_STAGES: list[tuple[str, str]] = [
    ("intake", "Image rendering"),
    ("quality_gate", "Checking image quality"),
    ("deepfake_check", "Deepfake identification in process"),
    ("vehicle_forensics", "Vehicle forensics in process"),
    ("duplicate_check", "Checking for reused images"),
    ("vehicle_id", "Identifying make and model"),
    ("consistency_check", "Confirming all images match the same vehicle"),
    ("damage_detection", "Mapping damage to vehicle parts"),
    ("severity_grading", "Grading damage severity"),
    ("fraud_scoring", "Running fraud intelligence checks"),
    ("parts_matching", "Matching parts to pricing catalogue"),
    ("estimate_ready", "Survey estimate ready"),
]


async def run_pipeline(claim_id: int) -> None:
    """Run the full assessment pipeline for a claim. Implemented in Milestone 4."""
    raise NotImplementedError("Pipeline orchestrator lands in Milestone 4")
