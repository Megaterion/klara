"""
log_viewer.py — Separate Rich-based log window for Klara.

Tails the Klara log file and displays entries with colored output.

Usage (in a separate terminal):
    cd klara-development/
    python -m agent.observability.log_viewer

Or launched automatically by start.sh via tmux.
"""

from __future__ import annotations

import argparse
import time
from collections import deque
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

LOG_THEME = Theme(
    {
        "log.info": "dim white",
        "log.warning": "yellow",
        "log.error": "bold red",
        "log.debug": "dim cyan",
        "log.critical": "bold red on white",
    }
)

MAX_LINES = 200
REFRESH_RATE = 8  # Hz

DEFAULT_LOG_FILE = "shared-data/logs/klara.log"


def _style_for_line(line: str) -> str:
    upper = line.upper()
    if " CRITICAL " in upper:
        return "log.critical"
    if " ERROR " in upper:
        return "log.error"
    if " WARNING " in upper:
        return "log.warning"
    if " DEBUG " in upper:
        return "log.debug"
    return "log.info"


def _render_panel(lines: deque[str], log_path: Path) -> Panel:
    text = Text()
    for line in lines:
        style = _style_for_line(line)
        text.append(line.rstrip() + "\n", style=style)
    return Panel(
        text,
        title=f"[yellow]📋 KLARA LOGS[/yellow]  [dim]{log_path}[/dim]",
        border_style="yellow",
    )


def _load_existing_lines(file_handle, lines: deque[str]) -> None:
    for line in file_handle:
        lines.append(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Klara log viewer")
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"Path to the log file (default: {DEFAULT_LOG_FILE})",
    )
    args = parser.parse_args()

    log_path = Path(args.log_file)
    console = Console(theme=LOG_THEME)
    lines: deque[str] = deque(maxlen=MAX_LINES)
    lines.append(f"Warte auf Log-Datei: {log_path}")

    current_file = None
    current_inode = None
    last_size = 0

    with Live(
        _render_panel(lines, log_path),
        console=console,
        refresh_per_second=REFRESH_RATE,
        screen=True,
    ) as live:
        while True:
            try:
                stat = log_path.stat()
            except FileNotFoundError:
                if current_file is not None:
                    current_file.close()
                    current_file = None
                    current_inode = None
                    last_size = 0
                lines.append(f"Warte auf Log-Datei: {log_path}")
                live.update(_render_panel(lines, log_path))
                time.sleep(1 / REFRESH_RATE)
                continue

            reopen = (
                current_file is None
                or current_inode != stat.st_ino
                or stat.st_size < last_size
            )
            if reopen:
                if current_file is not None:
                    current_file.close()
                current_file = open(log_path, encoding="utf-8", errors="replace")
                current_inode = stat.st_ino
                last_size = 0
                lines.append(f"Folge Log-Datei: {log_path}")
                _load_existing_lines(current_file, lines)
                last_size = current_file.tell()
                live.update(_render_panel(lines, log_path))
                time.sleep(1 / REFRESH_RATE)
                continue

            updated = False
            while True:
                new_line = current_file.readline()
                if not new_line:
                    break
                lines.append(new_line)
                updated = True

            last_size = current_file.tell()
            if updated:
                live.update(_render_panel(lines, log_path))
            time.sleep(1 / REFRESH_RATE)


if __name__ == "__main__":
    main()
