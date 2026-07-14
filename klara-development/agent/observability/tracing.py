"""
tracing.py — Structured JSON logging with file + console sink.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agent.observability.console_ui import ConsoleUI


class KlaraLogHandler(logging.Handler):
    """Forwards log records to the Rich ConsoleUI."""

    def __init__(self, ui: "ConsoleUI") -> None:
        super().__init__()
        self.ui = ui

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname
            if level == "DEBUG":
                self.ui.log_debug(msg)
            elif level == "WARNING":
                self.ui.log_warning(msg)
            elif level == "ERROR":
                self.ui.log_error(msg)
            else:
                self.ui.log_info(msg)
        except Exception:
            pass


class StructuredLogger:
    """Sets up Python logging for structured output."""

    def __init__(self, log_level: str = "INFO", log_file: Optional[str] = None) -> None:
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.log_file = log_file

    def configure(self, ui: Optional["ConsoleUI"] = None) -> None:
        root = logging.getLogger()
        root.setLevel(self.log_level)
        root.handlers.clear()

        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        # File handler with rotation
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                self.log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=3,
                encoding="utf-8",
            )
            fh.setFormatter(formatter)
            root.addHandler(fh)

        # Rich UI handler
        if ui is not None:
            ui_handler = KlaraLogHandler(ui)
            ui_handler.setLevel(self.log_level)
            # Simple format without timestamp (UI shows it)
            ui_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
            root.addHandler(ui_handler)

        # Silence noisy third-party loggers
        for noisy in ["httpx", "chromadb", "urllib3", "sentence_transformers"]:
            logging.getLogger(noisy).setLevel(logging.WARNING)
