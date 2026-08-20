"""EKO Platform Services request authentication (HMAC secret-key).

Every EKO call needs four headers: developer_key, secret-key,
secret-key-timestamp, and content-type. The secret-key is computed
fresh per request. Do not reuse a timestamp.

EKO warns: base64-encode the access key and use that *string* as the
HMAC key. Do not base64-decode it back to raw bytes first.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Dict


def compute_eko_secret_key(access_key: str, timestamp: str) -> str:
    """HMAC-SHA256(timestamp, key=base64(access_key)), then base64 the digest.

    Example (dummy values, not live credentials)::

        compute_eko_secret_key("test-access-key", "1700000000000")
        # -> "NST2B92VZrVhm2NMIdns4Na1HMEk16nem+B7lWVqNO4="
    """
    # 1. Access key as UTF-8 bytes, then base64 *string* (do not decode back).
    encoded_key = base64.b64encode(access_key.encode("utf-8")).decode("ascii")
    # 2. HMAC-SHA256: message = timestamp string, key = encoded_key string.
    digest = hmac.new(
        encoded_key.encode("utf-8"),
        timestamp.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    # 3. Base64-encode the raw HMAC digest -> secret-key header.
    return base64.b64encode(digest).decode("ascii")


def get_eko_initiator_id() -> str:
    """Initiator mobile with a leading plus stripped (EKO body wants digits)."""
    raw = (os.getenv("EKO_INITIATOR_ID") or "").strip()
    return raw.lstrip("+").replace(" ", "")


def get_eko_headers() -> Dict[str, str]:
    """Build EKO auth headers plus base-url from the process environment.

    Reads ``EKO_ACCESS_KEY`` (fallback ``EKO_VEHICLE_API_KEY``),
    ``EKO_DEVELOPER_KEY``, and ``EKO_BASE_URL``. Generates a fresh
    millisecond timestamp on every call.

    Example return (values truncated)::

        {
            "developer_key": "<from env>",
            "secret-key": "<base64 hmac>",
            "secret-key-timestamp": "1725446782123",
            "content-type": "application/json",
            "base-url": "https://staging.eko.in/ekoapi/v3",
        }

    Raises:
        RuntimeError: if access key or developer key is missing.
    """
    access_key = (os.getenv("EKO_ACCESS_KEY") or os.getenv("EKO_VEHICLE_API_KEY") or "").strip()
    developer_key = (os.getenv("EKO_DEVELOPER_KEY") or "").strip()
    base_url = (os.getenv("EKO_BASE_URL") or "https://staging.eko.in/ekoapi/v3").strip()
    if not access_key:
        raise RuntimeError("EKO_ACCESS_KEY is not configured")
    if not developer_key:
        raise RuntimeError("EKO_DEVELOPER_KEY is not configured")

    timestamp = str(int(time.time() * 1000))
    secret_key = compute_eko_secret_key(access_key, timestamp)
    return {
        "developer_key": developer_key,
        "secret-key": secret_key,
        "secret-key-timestamp": timestamp,
        "content-type": "application/json",
        "base-url": base_url.rstrip("/"),
    }
