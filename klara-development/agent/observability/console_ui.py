"""
console_ui.py — Rich-based live terminal UI for Klara.

Layout:
┌─────────────────────────────────────────┐
│  🤖 KLARA  |  status  |  time           │  ← header
├─────────────────────────────────────────┤
│  🎤 YOU:  <live transcription>          │  ← mic input (cyan)
│  🤖 KLARA: <streaming response>         │  ← Klara response (green)
├─────────────────────────────────────────┤
│  📋 LOGS                                │  ← structured logs (yellow/grey)
└─────────────────────────────────────────┘

All output MUST go through this class — never use print() directly.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Custom color theme
KLARA_THEME = Theme(
    {
        "user": "bold cyan",
        "klara": "bold green",
        "system": "bold yellow",
        "log.info": "dim white",
        "log.warning": "yellow",
        "log.error": "bold red",
        "log.debug": "dim cyan",
        "header": "bold white on dark_blue",
        "status": "bold magenta",
    }
)

MAX_LOG_LINES = 100
REFRESH_RATE = 15  # Hz


class ConsoleUI:
    """
    Singleton-style live terminal UI.
    Thread-safe via internal lock.
    """

    def __init__(self) -> None:
        self._console = Console(theme=KLARA_THEME)
        self._lock = threading.Lock()
        self._live: Optional[Live] = None

        # Current conversation state
        self._transcription: str = ""
        self._transcription_status: str = ""
        self._klara_response: str = ""
        self._status: str = "Bereit"
        self._is_speaking: bool = False

        # Rolling log buffer
        self._logs: deque[tuple[str, str, str]] = deque(maxlen=MAX_LOG_LINES)
        # (level, timestamp, message)

        # Background activity lines
        self._activity: deque[str] = deque(maxlen=10)

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the Rich Live context. Call once at app startup."""
        layout = self._build_layout()
        self._live = Live(
            layout,
            console=self._console,
            refresh_per_second=REFRESH_RATE,
            screen=False,
        )
        self._live.start(refresh=True)

    def stop(self) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()
            self._live = None

    def __enter__(self) -> "ConsoleUI":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    # ------------------------------------------------------------------ #
    #  Public update methods (all thread-safe)                            #
    # ------------------------------------------------------------------ #

    def set_status(self, status: str) -> None:
        with self._lock:
            self._status = status
        self._refresh()

    def set_transcription(self, text: str, status: str = "") -> None:
        """Replace the current live transcription text."""
        with self._lock:
            self._transcription = text
            self._transcription_status = status
        self._refresh()

    def clear_transcription(self) -> None:
        with self._lock:
            self._transcription = ""
            self._transcription_status = ""
        self._refresh()

    def start_klara_response(self) -> None:
        """Clear previous Klara response and start a new streaming one."""
        with self._lock:
            self._klara_response = ""
            self._is_speaking = False
        self._refresh()

    def stream_token(self, token: str) -> None:
        """Append a single LLM token to Klara's response display."""
        with self._lock:
            self._klara_response += token
        self._refresh()

    def set_speaking(self, speaking: bool) -> None:
        with self._lock:
            self._is_speaking = speaking
        self._refresh()

    def add_activity(self, message: str) -> None:
        """Add a background activity line (tool calls, memory lookups)."""
        with self._lock:
            self._activity.append(message)
        self._refresh()

    def log(self, level: str, message: str) -> None:
        """Add a log entry to the log panel."""
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._logs.append((level.upper(), ts, message))
        self._refresh()

    def log_info(self, msg: str) -> None:
        self.log("INFO", msg)

    def log_warning(self, msg: str) -> None:
        self.log("WARNING", msg)

    def log_error(self, msg: str) -> None:
        self.log("ERROR", msg)

    def log_debug(self, msg: str) -> None:
        self.log("DEBUG", msg)

    # ------------------------------------------------------------------ #
    #  Layout construction                                                 #
    # ------------------------------------------------------------------ #

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="logs", size=10),
        )
        layout["body"].split_column(
            Layout(name="user_panel", size=5),
            Layout(name="klara_panel"),
        )
        return layout

    def _render(self) -> Layout:
        layout = self._build_layout()

        # Header
        now = datetime.now().strftime("%H:%M:%S")
        status_icon = "🔊" if self._is_speaking else "💤"
        header_text = Text(justify="center")
        header_text.append("🤖 KLARA ", style="header")
        header_text.append(f"│ {status_icon} {self._status} │ {now}", style="dim white")
        layout["header"].update(Panel(header_text, style="bold"))

        # User transcription panel
        user_text = Text()
        if self._transcription:
            user_text.append("🎤 DU: ", style="user")
            user_text.append(self._transcription, style="cyan")
        elif self._transcription_status:
            user_text.append(self._transcription_status, style="dim cyan")
        else:
            user_text.append("🎤 Mikrofon aktiv — warte auf Sprache…", style="dim cyan")
        layout["user_panel"].update(Panel(user_text, title="[cyan]Mikrofon[/cyan]", border_style="cyan"))

        # Klara response panel
        klara_text = Text()
        if self._klara_response:
            klara_text.append("🤖 KLARA: ", style="klara")
            klara_text.append(self._klara_response, style="green")
            if self._is_speaking:
                klara_text.append(" 🔊", style="bold yellow")
        else:
            klara_text.append("Warte auf Eingabe…", style="dim green")

        # Show recent activity below response
        if self._activity:
            klara_text.append("\n")
            for act in list(self._activity)[-3:]:
                klara_text.append(f"\n  ⚙ {act}", style="dim yellow")

        layout["klara_panel"].update(
            Panel(klara_text, title="[green]Klara[/green]", border_style="green")
        )

        # Log panel
        log_text = Text()
        for level, ts, msg in list(self._logs)[-8:]:
            style_map = {
                "INFO": "log.info",
                "WARNING": "log.warning",
                "ERROR": "log.error",
                "DEBUG": "log.debug",
            }
            style = style_map.get(level, "log.info")
            log_text.append(f"[{ts}] ", style="dim")
            log_text.append(f"{level:7s} ", style=style)
            log_text.append(f"{msg}\n", style="white")
        layout["logs"].update(
            Panel(log_text, title="[yellow]Logs[/yellow]", border_style="yellow")
        )

        return layout

    def _refresh(self) -> None:
        if self._live:
            try:
                self._live.update(self._render())
            except Exception:
                pass  # Never crash on UI update
