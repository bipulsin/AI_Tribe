"""Illustrative policy PDF generation (ReportLab). Not a valid insurance document."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
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
        .replace("₹", "INR ")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def _wrap(text: str, width: int = 92) -> list[str]:
    words = _pdf_safe(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


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
    id_type: str | None = None,
    dob: str | None = None,
    gender: str | None = None,
    address: str | None = None,
    pincode: str | None = None,
    fuel_type: str | None = None,
    color: str | None = None,
    owner_name: str | None = None,
    coverage_summary: str | None = None,
    generated_at: datetime | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_path), pagesize=letter)
    c.setPageCompression(0)
    width, height = letter
    margin = 1 * inch
    generated = generated_at or datetime.now(timezone.utc)

    c.setFillColorRGB(0.96, 0.96, 0.97)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setFillColor(Color(0.85, 0.25, 0.08, alpha=0.5))
    c.setFont("Helvetica-Bold", 28)
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(32)
    c.drawCentredString(0, 0, _pdf_safe(watermark))
    c.restoreState()

    c.setFillColorRGB(0.75, 0.2, 0.1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, height - margin, _pdf_safe(watermark))
    c.setFont("Helvetica", 9)
    c.drawString(margin, height - margin - 14, _pdf_safe(LABEL_DEMO_POLICY))

    c.setFillColorRGB(0.05, 0.12, 0.22)
    c.setFont("Helvetica-Bold", 16)
    y = height - margin - 40
    c.drawString(margin, y, "Insurance Policy - AI Tribe")
    y -= 22
    c.setFont("Helvetica", 11)

    sections = [
        (
            "Policy information",
            [
                f"Policy Reference Number: {policy_reference}",
                f"Issue Date: {issue_on.strftime('%d/%m/%Y')}",
                f"Valid Until: {expiry_on.strftime('%d/%m/%Y')}",
                f"Insurer Name: {insurer_name}",
                f"Premium Amount: INR {premium:,.2f}",
                f"Policy Package: {package_type}",
            ],
        ),
        (
            "Customer information",
            [
                f"Customer Name: {customer_name}",
                f"Phone Number: {phone}",
                f"ID Type and Number: {(id_type or 'ID')} {id_masked}",
                f"Date of Birth: {dob or '-'}",
                f"Gender: {gender or '-'}",
                f"Address: {address or '-'}",
                f"Pincode: {pincode or '-'}",
            ],
        ),
        (
            "Vehicle information",
            [
                f"Vehicle Registration Number: {registration_number}",
                f"Make and Model: {make} {model}",
                f"Year of Manufacture: {year}",
                f"Fuel Type: {fuel_type or '-'}",
                f"Color: {color or '-'}",
                f"Owner Name: {owner_name or '-'}",
            ],
        ),
        (
            "Coverage summary",
            _wrap(coverage_summary or "Coverage details are illustrative only."),
        ),
    ]

    for title, lines in sections:
        if y < margin + 80:
            c.showPage()
            y = height - margin
        c.setFont("Helvetica-Bold", 14)
        c.setFillColorRGB(0.05, 0.12, 0.22)
        c.drawString(margin, y, title)
        y -= 16
        c.setFont("Helvetica", 11)
        for line in lines:
            for wrapped in _wrap(line):
                if y < margin + 60:
                    c.showPage()
                    y = height - margin
                    c.setFont("Helvetica", 11)
                c.drawString(margin, y, _pdf_safe(wrapped))
                y -= 14
        y -= 10

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.3, 0.15, 0.05)
    footer_y = 0.7 * inch
    c.drawString(margin, footer_y + 28, f"Generated: {generated.strftime('%d/%m/%Y %H:%M')} UTC")
    text_obj = c.beginText(margin, footer_y + 16)
    text_obj.setFont("Helvetica", 8)
    text_obj.textLines(
        _pdf_safe(
            "This document was generated by AI Tribe for demonstration purposes only. "
            "It does not constitute a valid insurance policy or coverage. "
            "All vehicle and customer information shown are from a simulated booking. "
            "No actual insurance coverage is provided. For real insurance policies, "
            "contact the actual insurance provider. "
        )
        + " "
        + _pdf_safe(DEFAULT_PDF_FOOTER)
    )
    c.drawText(text_obj)
    c.setFont("Helvetica", 8)
    c.drawRightString(width - margin, 0.45 * inch, "Page 1")
    c.showPage()
    c.save()
    return output_path
