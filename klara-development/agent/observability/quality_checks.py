"""
quality_checks.py — Response quality validation.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Minimum spoken response length (chars)
MIN_RESPONSE_CHARS = 10
# Maximum spoken response length before truncation warning
MAX_RESPONSE_CHARS = 2000


class QualityChecker:
    """Checks TTS-bound responses for quality issues."""

    def check(self, text: str) -> tuple[bool, str]:
        """
        Returns (is_ok, reason).
        is_ok=False means the response should be rejected or retried.
        """
        if not text or not text.strip():
            return False, "Empty response"
        if len(text) < MIN_RESPONSE_CHARS:
            return False, f"Response too short ({len(text)} chars)"
        if len(text) > MAX_RESPONSE_CHARS:
            logger.warning("Response truncated from %d to %d chars", len(text), MAX_RESPONSE_CHARS)
        # Check for raw JSON leaking into spoken response
        if text.strip().startswith("{") or text.strip().startswith("["):
            return False, "Response looks like raw JSON — not suitable for speech"
        # Check for markdown artifacts that would sound bad
        bad_patterns = [r"```", r"#{1,6}\s", r"\*\*.*?\*\*"]
        for pattern in bad_patterns:
            if re.search(pattern, text):
                logger.debug("Response contains markdown: stripping before TTS")
                break
        return True, "OK"

    def clean_for_tts(self, text: str) -> str:
        """Strip markdown and other artifacts before sending to TTS."""
        # Strip code fences
        text = re.sub(r"```[a-z]*\n?", "", text)
        # Strip bold/italic markers
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        # Strip markdown headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Strip bullet points (convert to sentences)
        text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
        # Normalize whitespace
        text = re.sub(r"\n{2,}", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()[:MAX_RESPONSE_CHARS]
