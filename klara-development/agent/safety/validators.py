"""
safety/validators.py – Input/output validators for Klara.

- Validates LLM JSON output against Pydantic schemas.
- Sanitizes web/filesystem content before injecting into prompts.
- Guards against prompt injection from external sources.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

log = logging.getLogger(__name__)

# Patterns that indicate prompt injection attempts in external content
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
]


def validate_assessment(raw_json: str, max_retries: int = 2) -> Any | None:
    """
    Parse and validate a ButlerAssessment from LLM JSON output.

    Returns the validated model or None on failure.
    Import is local to avoid circular imports.
    """
    from ..schemas.assessment import ButlerAssessment  # noqa: PLC0415

    raw = raw_json.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()

    try:
        data = json.loads(raw)
        return ButlerAssessment.model_validate(data)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error in assessment: %s | raw=%.200s", exc, raw)
    except ValidationError as exc:
        log.warning("Schema validation error in assessment: %s", exc)
    return None


def sanitize_external_content(content: str, source: str = "external") -> str:
    """
    Remove or flag potential prompt injection patterns in content from
    web pages, filesystem reads, or Home Assistant descriptions.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            log.warning("Potential prompt injection detected in %s content – sanitizing.", source)
            content = pattern.sub("[REDACTED]", content)
    return content


def sanitize_user_input(text: str) -> str:
    """Light sanitization for direct user input (voice-to-text, etc.)."""
    # Trim excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Cap length
    if len(text) > 2000:
        text = text[:2000] + "…"
    return text


def validate_tool_payload(payload: dict[str, Any], required_keys: list[str]) -> bool:
    """Check that a tool payload contains all required keys."""
    missing = [k for k in required_keys if k not in payload]
    if missing:
        log.warning("Tool payload missing keys: %s", missing)
        return False
    return True
