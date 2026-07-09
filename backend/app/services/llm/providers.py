"""Multi-provider LLM HTTP client for BYOK pipeline assist."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.services.llm.constants import LLM_TIMEOUT_SECONDS, PROVIDERS

logger = logging.getLogger("ai_tribe.llm.providers")

DEFAULT_TEXT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.0-flash",
    "grok": "grok-2-1212",
}

DEFAULT_VISION_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.0-flash",
    "grok": "grok-2-vision-1212",
}


class LlmProviderError(RuntimeError):
    """Raised when a provider call fails; message must never include API keys."""


def parse_json_block(text: str) -> dict[str, Any]:
    """Extract and parse a JSON object from plain text or fenced code blocks."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def _validate_provider(provider: str) -> str:
    name = provider.strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    return name


def _image_payload(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    with path.open("rb") as fh:
        b64 = base64.standard_b64encode(fh.read()).decode("ascii")
    return mime, b64


def _safe_error(provider: str, exc: Exception) -> str:
    logger.warning("LLM provider %s call failed: %s", provider, type(exc).__name__)
    return "The provider could not be reached or rejected the request."


def _openai_chat(
    api_key: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return str(data["choices"][0]["message"]["content"])


def _anthropic_chat(
    api_key: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    system: str | None,
    max_tokens: int = 1024,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    parts = data.get("content") or []
    return "".join(str(part.get("text", "")) for part in parts if part.get("type") == "text")


def _gemini_chat(
    api_key: str,
    *,
    model: str,
    parts: list[dict[str, Any]],
    max_tokens: int = 1024,
) -> str:
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = client.post(url, params={"key": api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise LlmProviderError("Gemini returned no candidates")
    content = candidates[0].get("content") or {}
    text_parts = content.get("parts") or []
    return "".join(str(part.get("text", "")) for part in text_parts)


def _grok_chat(
    api_key: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return str(data["choices"][0]["message"]["content"])


def _build_openai_vision_messages(
    prompt: str, image_paths: list[Path], *, system: str | None
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in image_paths:
        mime, b64 = _image_payload(path)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/{mime};base64,{b64}"},
            }
        )
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    return messages


def _build_anthropic_vision_messages(
    prompt: str, image_paths: list[Path]
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in image_paths:
        mime, b64 = _image_payload(path)
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": f"image/{mime}",
                    "data": b64,
                },
            }
        )
    return [{"role": "user", "content": content}]


def _build_gemini_vision_parts(prompt: str, image_paths: list[Path]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for path in image_paths:
        mime, b64 = _image_payload(path)
        parts.append({"inline_data": {"mime_type": f"image/{mime}", "data": b64}})
    return parts


def test_connection(provider: str, api_key: str) -> tuple[bool, str]:
    """Run a minimal API call to verify the key. Never logs or returns the key."""
    name = _validate_provider(provider)
    key = api_key.strip()
    if len(key) < 8:
        return False, "API key is too short."

    try:
        if name == "openai":
            _openai_chat(
                key,
                model=DEFAULT_TEXT_MODELS[name],
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=8,
            )
        elif name == "anthropic":
            _anthropic_chat(
                key,
                model=DEFAULT_TEXT_MODELS[name],
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                system=None,
                max_tokens=8,
            )
        elif name == "gemini":
            _gemini_chat(
                key,
                model=DEFAULT_TEXT_MODELS[name],
                parts=[{"text": "Reply with exactly: OK"}],
                max_tokens=8,
            )
        elif name == "grok":
            _grok_chat(
                key,
                model=DEFAULT_TEXT_MODELS[name],
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=8,
            )
        return True, "Connection successful."
    except httpx.HTTPStatusError:
        return False, "The provider rejected the API key or request."
    except Exception as exc:
        return False, _safe_error(name, exc)


def chat_text(
    provider: str,
    api_key: str,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1024,
) -> str | None:
    """Send a text-only prompt. Returns None on failure."""
    name = _validate_provider(provider)
    key = api_key.strip()
    try:
        if name == "openai":
            messages: list[dict[str, Any]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            return _openai_chat(
                key, model=DEFAULT_TEXT_MODELS[name], messages=messages, max_tokens=max_tokens
            )
        if name == "anthropic":
            return _anthropic_chat(
                key,
                model=DEFAULT_TEXT_MODELS[name],
                messages=[{"role": "user", "content": prompt}],
                system=system,
                max_tokens=max_tokens,
            )
        if name == "gemini":
            parts: list[dict[str, Any]] = []
            if system:
                parts.append({"text": system})
            parts.append({"text": prompt})
            return _gemini_chat(
                key, model=DEFAULT_TEXT_MODELS[name], parts=parts, max_tokens=max_tokens
            )
        if name == "grok":
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            return _grok_chat(
                key, model=DEFAULT_TEXT_MODELS[name], messages=messages, max_tokens=max_tokens
            )
    except Exception as exc:
        logger.warning("chat_text failed for provider %s: %s", name, type(exc).__name__)
        return None
    return None


def chat_vision(
    provider: str,
    api_key: str,
    prompt: str,
    image_paths: list[Path],
    *,
    system: str | None = None,
    max_tokens: int = 1024,
) -> str | None:
    """Send a vision prompt with one or more local images. Returns None on failure."""
    name = _validate_provider(provider)
    key = api_key.strip()
    paths = [Path(p) for p in image_paths if Path(p).is_file()]
    if not paths:
        return None

    try:
        if name == "openai":
            messages = _build_openai_vision_messages(prompt, paths, system=system)
            return _openai_chat(
                key,
                model=DEFAULT_VISION_MODELS[name],
                messages=messages,
                max_tokens=max_tokens,
            )
        if name == "anthropic":
            return _anthropic_chat(
                key,
                model=DEFAULT_VISION_MODELS[name],
                messages=_build_anthropic_vision_messages(prompt, paths),
                system=system,
                max_tokens=max_tokens,
            )
        if name == "gemini":
            return _gemini_chat(
                key,
                model=DEFAULT_VISION_MODELS[name],
                parts=_build_gemini_vision_parts(prompt, paths),
                max_tokens=max_tokens,
            )
        if name == "grok":
            messages = _build_openai_vision_messages(prompt, paths, system=system)
            return _grok_chat(
                key,
                model=DEFAULT_VISION_MODELS[name],
                messages=messages,
                max_tokens=max_tokens,
            )
    except Exception as exc:
        logger.warning("chat_vision failed for provider %s: %s", name, type(exc).__name__)
        return None
    return None
