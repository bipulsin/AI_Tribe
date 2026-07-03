"""EXIF / metadata forensics for claim images."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS

# Software tags commonly left by generative or heavy-edit tools.
SUSPICIOUS_SOFTWARE = (
    "photoshop",
    "gimp",
    "midjourney",
    "stable diffusion",
    "dall·e",
    "dall-e",
    "generative",
    "ai image",
)


@dataclass
class MetadataResult:
    has_exif: bool
    software: str | None
    anomalous: bool
    detail: str


def inspect_metadata(path: Path) -> MetadataResult:
    with Image.open(path) as img:
        exif = img.getexif()

    if not exif:
        # Missing EXIF is common on phone shares and not alone a failure.
        return MetadataResult(
            has_exif=False,
            software=None,
            anomalous=False,
            detail="No EXIF metadata present (common for shared photos).",
        )

    decoded = {TAGS.get(tag, str(tag)): value for tag, value in exif.items()}
    software = decoded.get("Software")
    software_str = str(software) if software else None

    anomalous = False
    if software_str:
        lowered = software_str.lower()
        if any(token in lowered for token in SUSPICIOUS_SOFTWARE):
            anomalous = True
            return MetadataResult(
                has_exif=True,
                software=software_str,
                anomalous=True,
                detail=f"Editing or generative software tag found: {software_str}.",
            )

    return MetadataResult(
        has_exif=True,
        software=software_str,
        anomalous=False,
        detail="Metadata checks passed.",
    )


def inspect_paths(paths: list[Path]) -> tuple[bool, str]:
    if not paths:
        return True, "No images for metadata checks."

    results = [inspect_metadata(path) for path in paths]
    anomalous = [r for r in results if r.anomalous]
    if anomalous:
        return False, anomalous[0].detail
    return True, results[0].detail
