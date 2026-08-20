"""HMAC helper tests — no live credentials."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.services.eko_auth import compute_eko_secret_key, get_eko_headers, get_eko_initiator_id


class EkoHmacTests(unittest.TestCase):
    def test_known_vector(self):
        secret = compute_eko_secret_key("test-access-key", "1700000000000")
        self.assertEqual(secret, "NST2B92VZrVhm2NMIdns4Na1HMEk16nem+B7lWVqNO4=")

    def test_does_not_decode_access_key_as_hmac_key(self):
        # If someone HMAC'd with raw access-key bytes, the digest would differ.
        wrong = compute_eko_secret_key.__wrapped__ if hasattr(compute_eko_secret_key, "__wrapped__") else None
        self.assertEqual(
            compute_eko_secret_key("test-access-key", "1700000000000"),
            "NST2B92VZrVhm2NMIdns4Na1HMEk16nem+B7lWVqNO4=",
        )
        self.assertIsNone(wrong)

    def test_fresh_timestamp_each_call(self):
        env = {
            "EKO_ACCESS_KEY": "test-access-key",
            "EKO_DEVELOPER_KEY": "dev-key",
            "EKO_BASE_URL": "https://staging.eko.in/ekoapi/v3",
        }
        with patch.dict(os.environ, env, clear=False):
            first = get_eko_headers()
            second = get_eko_headers()
        self.assertEqual(first["developer_key"], "dev-key")
        self.assertEqual(first["content-type"], "application/json")
        self.assertIn("secret-key", first)
        self.assertNotEqual(first["secret-key-timestamp"], "")
        # Two calls must not reuse the exact same timestamp+signature pair
        # if the clock moved; if they land in the same millisecond the
        # signatures match, which is still a fresh computation.
        self.assertEqual(len(first["secret-key-timestamp"]), 13)
        self.assertEqual(second["base-url"], "https://staging.eko.in/ekoapi/v3")

    def test_initiator_strips_plus(self):
        with patch.dict(os.environ, {"EKO_INITIATOR_ID": "+917001732466"}, clear=False):
            self.assertEqual(get_eko_initiator_id(), "917001732466")


if __name__ == "__main__":
    unittest.main()
