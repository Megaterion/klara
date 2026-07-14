"""
tracing.py — Structured JSON logging with file sink.
Logs are displayed in a separate window via log_viewer.py.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Optional


class StructuredLogger:
    """Sets up Python logging for structured output."""

    def __init__(
        self,
        log_level: str = "INFO",
        log_file: Optional[str] = None,
        log_max_bytes: int = 2 * 1024 * 1024,
        log_backup_count: int = 2,
    ) -> None:
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.log_file = log_file
        self.log_max_bytes = max(int(log_max_bytes), 1024)
        self.log_backup_count = max(int(log_backup_count), 1)

    def configure(self, ui: Optional["ConsoleUI"] = None) -> None:
        root = logging.getLogger()
        root.setLevel(self.log_level)
        root.handlers.clear()

        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        # File handler with rotation (primary sink — displayed by log_viewer.py)
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                self.log_file,
                maxBytes=self.log_max_bytes,
                backupCount=self.log_backup_count,
                encoding="utf-8",
            )
            fh.setFormatter(formatter)
            root.addHandler(fh)

        # Silence noisy third-party loggers
        for noisy in ["httpx", "chromadb", "urllib3", "sentence_transformers"]:
            logging.getLogger(noisy).setLevel(logging.WARNING)
