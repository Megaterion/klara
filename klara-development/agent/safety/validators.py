"""
validators.py — Input/output validation utilities.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from pydantic import ValidationError

from agent.schemas.assessment import ButlerAssessment

logger = logging.getLogger(__name__)

# Maximum length of user input accepted (chars)
MAX_USER_INPUT_CHARS = 2000

# Prompt injection keywords to flag (not block — just log)
_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"disregard your system prompt",
    r"you are now",
    r"pretend you are",
    r"new instructions:",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


class ResponseValidator:
    """Validates and sanitizes LLM responses."""

    def validate_assessment(
        self, raw_json: str, retries_left: int = 2
    ) -> Optional[ButlerAssessment]:
        """
        Parse and validate a ButlerAssessment from raw LLM JSON output.
        Returns None if parsing fails after strip attempts.
        """
        # Extract JSON from possible markdown code fences
        cleaned = self._extract_json(raw_json)
        try:
            data = json.loads(cleaned)
            return ButlerAssessment.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Assessment validation failed: %s", exc)
            if retries_left > 0:
                # Try stripping trailing garbage and retry
                stripped = cleaned.rstrip().rstrip(",") + "}"
                return self.validate_assessment(stripped, retries_left - 1)
            return None

    def sanitize_user_input(self, text: str) -> str:
        """Truncate and flag suspicious user input."""
        text = text[:MAX_USER_INPUT_CHARS]
        if _INJECTION_RE.search(text):
            logger.warning("Possible prompt injection detected in user input")
        return text

    def validate_tool_params(self, tool: str, params: dict[str, Any]) -> bool:
        """Basic parameter sanity checks for tool calls."""
        if tool == "smarthome.call_service":
            return bool(params.get("domain") and params.get("service") and params.get("entity_id"))
        if tool == "internet.fetch":
            url = params.get("url", "")
            return url.startswith("http://") or url.startswith("https://")
        if tool == "filesystem.read":
            return bool(params.get("path"))
        return True

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences and find JSON object/array."""
        # Remove ```json ... ``` fences
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        # Find first { ... } block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start: end + 1]
        return text
