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
import sys
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

    console.print(f"[bold yellow]📋 Klara Log Viewer[/bold yellow] — {log_path}")
    console.print("[dim]Warte auf Log-Datei…[/dim]")

    while not log_path.exists():
        time.sleep(0.5)

    lines: deque[str] = deque(maxlen=MAX_LINES)

    with open(log_path, encoding="utf-8", errors="replace") as f:
        # Read all existing content first
        for line in f:
            lines.append(line)

        with Live(
            _render_panel(lines, log_path),
            console=console,
            refresh_per_second=REFRESH_RATE,
            screen=True,
        ) as live:
            while True:
                new_line = f.readline()
                if new_line:
                    lines.append(new_line)
                    live.update(_render_panel(lines, log_path))
                else:
                    time.sleep(1 / REFRESH_RATE)


if __name__ == "__main__":
    main()
