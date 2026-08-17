"""Unit tests for the policy booking demo module."""

from __future__ import annotations

import random
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pathlib import Path

from app.policy.constants import LABEL_DEMO_QUOTE
from app.policy.documents import generate_policy_pdf
from app.policy.extraction import (
    extract_policy_fields,
    is_valid_aadhaar,
    is_valid_pan,
    is_valid_registration,
    mask_id_number,
    next_collection_step_from_fields,
)
from app.policy.kyc import MockInsurerTaggedProvider
from app.policy.quotes import generate_quotes
from app.policy.vehicle import DemoFallbackProvider, lookup_vehicle


class AuthGateTests(unittest.TestCase):
    def test_policy_is_not_public(self):
        text = Path(__file__).resolve().parents[1].joinpath("app/main.py").read_text()
        start = text.index("PUBLIC_PATHS")
        chunk = text[start : start + 500]
        self.assertNotIn('"/policy"', chunk)


class RegistrationRegexTests(unittest.TestCase):
    def test_accepts_valid_indian_formats(self):
        self.assertTrue(is_valid_registration("MH02AB1234"))
        self.assertTrue(is_valid_registration("DL02CA1234"))
        self.assertTrue(is_valid_registration("mh 02 ab 1234"))

    def test_rejects_invalid(self):
        self.assertFalse(is_valid_registration("MH2AB1234"))
        self.assertFalse(is_valid_registration("1234"))
        self.assertFalse(is_valid_registration("INVALID"))


class IdRegexTests(unittest.TestCase):
    def test_pan(self):
        self.assertTrue(is_valid_pan("ABCDE1234F"))
        self.assertFalse(is_valid_pan("ABCD1234F"))
        self.assertFalse(is_valid_pan("ABCDE12345"))

    def test_aadhaar(self):
        self.assertTrue(is_valid_aadhaar("1234 5678 9012"))
        self.assertTrue(is_valid_aadhaar("123456789012"))
        self.assertFalse(is_valid_aadhaar("12345"))
        self.assertFalse(is_valid_aadhaar("012345678901"))


class ExtractionTests(unittest.TestCase):
    def test_free_text_extracts_reg_and_name(self):
        fields = extract_policy_fields("Book a policy for MH02AB1234 for Amit Sharma")
        self.assertEqual(fields.get("registration_number"), "MH02AB1234")
        self.assertEqual(fields.get("customer_name"), "Amit Sharma")

    def test_mask_id_never_stores_full(self):
        masked = mask_id_number("ABCDE1234F")
        self.assertTrue(masked.endswith("234F"))
        self.assertNotIn("ABCDE", masked)


class StateMachineTests(unittest.TestCase):
    def test_advances_through_required_fields(self):
        fields: dict = {}
        self.assertEqual(next_collection_step_from_fields(fields), "collect_registration_number")
        fields["registration_number"] = "MH02AB1234"
        self.assertEqual(next_collection_step_from_fields(fields), "confirm_vehicle")
        fields["vehicle_confirmed"] = True
        self.assertEqual(next_collection_step_from_fields(fields), "collect_customer_name")
        fields.update(
            {
                "customer_name": "Ada",
                "phone": "9876543210",
                "id_type": "PAN",
                "id_number": "ABCDE1234F",
                "dob": "1990-01-01",
                "gender": "Female",
                "address": "12 Demo Street",
                "pincode": "400001",
                "previous_policy": True,
                "kyc_valid": True,
                "quotes": True,
                "quote_selected": True,
                "issued": True,
            }
        )
        self.assertEqual(next_collection_step_from_fields(fields), "completed")


class FallbackVehicleTests(unittest.TestCase):
    def test_prefix_mapping(self):
        self.assertEqual(DemoFallbackProvider().lookup("MH02AB1234").model, "Swift")
        self.assertEqual(DemoFallbackProvider().lookup("DL1CAA1234").model, "Creta")
        self.assertEqual(DemoFallbackProvider().lookup("KA01AB1234").model, "Innova")
        self.assertEqual(DemoFallbackProvider().lookup("TN09AB1234").model, "Nexon")
        self.assertEqual(DemoFallbackProvider().lookup("GJ01AB1234").model, "Generic Hatchback")

    def test_missing_key_uses_fallback(self):
        result = lookup_vehicle("MH02AB1234", force_fallback=True)
        self.assertEqual(result.source, "demo_fallback")
        self.assertIn("Fallback", result.source_label)


class KycMockTests(unittest.TestCase):
    def test_invalid_then_retry_valid(self):
        provider = MockInsurerTaggedProvider()
        first = provider.validate(
            id_type="PAN",
            id_number="ABCDE1234F",
            attempt_number=1,
            rng=random.Random(0),
        )
        retry = provider.validate(
            id_type="PAN",
            id_number="ABCDE1234F",
            attempt_number=2,
            rng=random.Random(0),
        )
        self.assertTrue(retry.valid)
        self.assertEqual(retry.attempt_number, 2)
        self.assertTrue(first.id_masked.endswith("234F"))
        self.assertNotIn("ABCDE1234F", first.id_masked)


class QuoteTests(unittest.TestCase):
    def test_three_quotes_and_varying_premiums(self):
        swift = generate_quotes(
            year=2021,
            make="Maruti",
            pincode="400001",
            previous_policy=True,
            floors=(8000, 12000, 18000),
            randomized=False,
            seed="a",
        )
        innova = generate_quotes(
            year=2016,
            make="Toyota",
            pincode="560001",
            previous_policy=False,
            floors=(8000, 12000, 18000),
            randomized=False,
            seed="b",
        )
        self.assertEqual(len(swift), 3)
        self.assertEqual(len(innova), 3)
        self.assertTrue(all(q.label == LABEL_DEMO_QUOTE for q in swift))
        self.assertNotEqual(
            [q.premium for q in swift],
            [q.premium for q in innova],
        )


class PdfTests(unittest.TestCase):
    def test_watermark_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.pdf"
            generate_policy_pdf(
                output_path=path,
                policy_reference="DMO-POL-TEST",
                customer_name="Ada",
                phone="9876543210",
                id_masked="****234F",
                registration_number="MH02AB1234",
                make="Maruti",
                model="Swift",
                year="2021",
                insurer_name="Demo Insurer A",
                package_type="Economy",
                premium=9000.0,
                issue_on=date(2026, 8, 17),
                expiry_on=date(2027, 8, 17),
            )
            data = path.read_bytes()
            self.assertTrue(path.is_file())
            self.assertIn(b"DEMO POLICY", data)
            self.assertIn(b"NOT A VALID INSURANCE DOCUMENT", data)
            self.assertNotIn(b"ABCDE1234F", data)


if __name__ == "__main__":
    unittest.main()
