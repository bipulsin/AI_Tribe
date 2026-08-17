"""Demo policy PDF generation (ReportLab). Not a valid insurance document."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.core.config import get_settings
from app.policy.constants import DEFAULT_PDF_FOOTER, DEFAULT_WATERMARK, LABEL_DEMO_POLICY


def policy_docs_dir() -> Path:
    settings = get_settings()
    path = settings.policy_docs_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pdf_safe(text: str) -> str:
    return (
        str(text)
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2022", "*")
        .replace("\u00b7", "-")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def generate_policy_pdf(
    *,
    output_path: Path,
    policy_reference: str,
    customer_name: str,
    phone: str,
    id_masked: str,
    registration_number: str,
    make: str,
    model: str,
    year: str,
    insurer_name: str,
    package_type: str,
    premium: float,
    issue_on: date,
    expiry_on: date,
    watermark: str = DEFAULT_WATERMARK,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setPageCompression(0)
    width, height = A4

    c.setFillColorRGB(0.92, 0.55, 0.2)
    c.setFont("Helvetica-Bold", 22)
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(32)
    c.drawCentredString(0, 0, _pdf_safe(watermark))
    c.restoreState()

    c.setFillColorRGB(0.75, 0.2, 0.1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, height - 20 * mm, _pdf_safe(watermark))
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, height - 26 * mm, _pdf_safe(LABEL_DEMO_POLICY))

    c.setFillColorRGB(0.05, 0.12, 0.22)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, height - 42 * mm, "AI Tribe - Demo Motor Policy")
    c.setFont("Helvetica", 10)
    y = height - 54 * mm
    lines = [
        f"Policy reference: {policy_reference}",
        f"Customer name: {customer_name}",
        f"Phone: {phone}",
        f"ID (masked): {id_masked}",
        f"Vehicle: {registration_number} - {make} {model} - {year}",
        f"Insurer: {insurer_name}",
        f"Package: {package_type}",
        f"Premium (INR, illustrative): {premium:,.2f}",
        f"Issue date: {issue_on.isoformat()}",
        f"Expiry date: {expiry_on.isoformat()}",
        "source_mode: demo_issuance",
    ]
    for line in lines:
        c.drawString(20 * mm, y, _pdf_safe(line))
        y -= 8 * mm

    c.setFont("Helvetica-Oblique", 8)
    c.setFillColorRGB(0.3, 0.15, 0.05)
    text_obj = c.beginText(20 * mm, 28 * mm)
    text_obj.textLines(DEFAULT_PDF_FOOTER)
    c.drawText(text_obj)
    c.showPage()
    c.save()
    return output_path
