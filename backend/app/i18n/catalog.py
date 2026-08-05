"""Static UI string catalogs (EN / FR). No runtime LLM translation."""

from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment

LANG_COOKIE = "atr_lang"
SUPPORTED_LANGS = frozenset({"en", "fr"})
DEFAULT_LANG = "en"

_current_lang: ContextVar[str] = ContextVar("current_lang", default=DEFAULT_LANG)

_I18N_DIR = Path(__file__).resolve().parent


@lru_cache
def _load_catalog(lang: str) -> dict[str, str]:
    path = _I18N_DIR / f"{lang}.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def resolve_lang(raw: str | None) -> str:
    """Normalize cookie/header value to a supported language code."""
    code = (raw or DEFAULT_LANG).strip().lower()[:8]
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def set_request_lang(lang: str) -> object:
    return _current_lang.set(resolve_lang(lang))


def reset_request_lang(token: object) -> None:
    _current_lang.reset(token)  # type: ignore[arg-type]


def get_lang() -> str:
    return _current_lang.get()


def translate(key: str, lang: str | None = None, **kwargs: Any) -> str:
    """Return translated string; fall back to English, then the key itself."""
    code = resolve_lang(lang) if lang else get_lang()
    value = _load_catalog(code).get(key)
    if value is None and code != DEFAULT_LANG:
        value = _load_catalog(DEFAULT_LANG).get(key)
    if value is None:
        value = key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value
    return value


def translate_pipeline_stage(stage_key: str, fallback: str = "") -> str:
    key = f"pipeline.stage.{stage_key}"
    result = translate(key)
    return result if result != key else (fallback or stage_key)


def claim_status_label(status_value: str) -> str:
    key = f"claim.status.{status_value}"
    result = translate(key)
    return result if result != key else status_value.replace("_", " ").title()


def js_strings(lang: str | None = None) -> dict[str, str]:
    """Subset of keys passed to client-side scripts."""
    code = resolve_lang(lang) if lang else get_lang()
    catalog = _load_catalog(code)
    en = _load_catalog(DEFAULT_LANG)
    keys = _JS_KEYS
    out: dict[str, str] = {}
    for k in keys:
        out[k] = catalog.get(k) or en.get(k) or k
    return out


def setup_jinja_globals(env: Environment) -> None:
    env.globals["t"] = translate
    env.globals["get_lang"] = get_lang
    env.globals["js_i18n"] = js_strings


# Keys referenced from Alpine/HTMX JS (upload, pipeline, chat chrome errors).
_JS_KEYS: tuple[str, ...] = (
    "upload.images_counter",
    "upload.video_attached",
    "upload.file_error_title",
    "upload.file_too_large",
    "upload.max_images",
    "upload.unsupported_type",
    "upload.preview_video",
    "upload.remove_file",
    "upload.submit_hint",
    "upload.submitting",
    "upload.submit_claim",
    "upload.network_error",
    "upload.submit_failed",
    "chat.server_error",
    "chat.upload_type_error",
    "chat.upload_failed",
    "pipeline.stage.intake",
    "pipeline.stage.quality_gate",
    "pipeline.stage.deepfake_check",
    "pipeline.stage.vehicle_forensics",
    "pipeline.stage.duplicate_check",
    "pipeline.stage.sensor_consistency",
    "pipeline.stage.vehicle_id",
    "pipeline.stage.consistency_check",
    "pipeline.stage.damage_detection",
    "pipeline.stage.severity_grading",
    "pipeline.stage.fraud_scoring",
    "pipeline.stage.parts_matching",
    "pipeline.stage.estimate_ready",
    "pipeline.stage.vehicle_confirmation",
    "pipeline.elapsed",
    "pipeline.connecting",
    "pipeline.assessment_paused",
    "pipeline.send_review",
    "pipeline.sent_review",
    "pipeline.estimate_ready_title",
    "pipeline.estimate_ready_body",
    "pipeline.view_estimate",
    "pipeline.confirm_continue",
    "pipeline.continuing",
    "pipeline.llm_prefill",
    "pipeline.make",
    "pipeline.model",
    "fraud.network_caption_suffix",
    "fraud.expand",
    "fraud.claim_network",
    "fraud.zoom_in",
    "fraud.zoom_out",
    "fraud.close",
    "fraud.no_pattern",
    "marketplace.days",
    "marketplace.expires_in",
    "marketplace.end_finish",
    "marketplace.tooltip_wip_locked",
    "marketplace.tooltip_always_on",
    "marketplace.tooltip_wip_stub",
    "marketplace.msg.token_generated",
    "marketplace.msg.token_revealed",
    "marketplace.msg.token_copied",
    "marketplace.msg.copy_manual",
    "marketplace.msg.token_error",
    "marketplace.msg.reveal_error",
    "marketplace.msg.subscribe_error",
    "marketplace.msg.subscribed",
    "marketplace.msg.unsubscribed",
    "marketplace.msg.connector_saved",
    "marketplace.msg.connector_error",
    "marketplace.msg.chain_saved",
    "marketplace.msg.chain_error",
    "marketplace.msg.chain_deleted",
    "marketplace.msg.chain_delete_error",
    "marketplace.msg.confirm_delete_chain",
)
