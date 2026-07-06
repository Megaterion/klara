"""
tools/filesystem.py – Local filesystem access for Klara's Second Brain.

Klara can read files, list directories, search by glob pattern,
and write notes/logs. Access is sandboxed to allowed root paths.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Paths that Klara must NEVER read or write
_BLOCKED_PATTERNS = [
    "/etc/shadow",
    "/etc/passwd",
    "**/.ssh/**",
    "**/.gnupg/**",
    "**/id_rsa*",
    "**/id_ed25519*",
]


def _is_blocked(path: Path) -> bool:
    path_str = str(path)
    for pattern in _BLOCKED_PATTERNS:
        if fnmatch.fnmatch(path_str, pattern):
            return True
    return False


class FilesystemTool:
    def __init__(
        self,
        allowed_roots: list[str | Path],
        default_notes_dir: str | Path | None = None,
    ) -> None:
        self.allowed_roots = [Path(r).resolve() for r in allowed_roots]
        self.notes_dir = Path(default_notes_dir).resolve() if default_notes_dir else None

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _resolve_and_check(self, path: str | Path) -> Path | None:
        resolved = Path(path).resolve()
        if _is_blocked(resolved):
            log.warning("Filesystem access blocked (security): %s", resolved)
            return None
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        log.warning("Filesystem access outside allowed roots: %s", resolved)
        return None

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def read_file(self, path: str, max_chars: int = 8000) -> str | None:
        safe_path = self._resolve_and_check(path)
        if safe_path is None:
            return None
        if not safe_path.is_file():
            log.warning("read_file: not a file: %s", safe_path)
            return None
        try:
            content = safe_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n[…truncated to {max_chars} chars]"
            return content
        except Exception as exc:
            log.error("read_file error: %s", exc)
            return None

    async def list_directory(self, path: str) -> list[str] | None:
        safe_path = self._resolve_and_check(path)
        if safe_path is None:
            return None
        if not safe_path.is_dir():
            return None
        try:
            entries = sorted(safe_path.iterdir(), key=lambda p: (p.is_file(), p.name))
            return [str(e.relative_to(safe_path)) + ("/" if e.is_dir() else "") for e in entries]
        except Exception as exc:
            log.error("list_directory error: %s", exc)
            return None

    async def search_files(
        self, root: str, pattern: str = "**/*", max_results: int = 20
    ) -> list[str]:
        safe_root = self._resolve_and_check(root)
        if safe_root is None:
            return []
        if not safe_root.is_dir():
            return []
        try:
            results: list[str] = []
            for p in safe_root.glob(pattern):
                if p.is_file() and not _is_blocked(p):
                    results.append(str(p))
                    if len(results) >= max_results:
                        break
            return results
        except Exception as exc:
            log.error("search_files error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def write_file(
        self, path: str, content: str, append: bool = False
    ) -> bool:
        safe_path = self._resolve_and_check(path)
        if safe_path is None:
            return False
        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            safe_path.write_text(content, encoding="utf-8") if not append else \
                safe_path.open("a", encoding="utf-8").write(content)
            log.info("Wrote %d chars to %s (append=%s)", len(content), safe_path, append)
            return True
        except Exception as exc:
            log.error("write_file error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "read_file":
            return await self.read_file(payload["path"], payload.get("max_chars", 8000))
        if action == "write_file":
            return await self.write_file(
                payload["path"], payload["content"], payload.get("append", False)
            )
        if action == "list_directory":
            return await self.list_directory(payload["path"])
        if action == "search_files":
            return await self.search_files(
                payload["root"], payload.get("pattern", "**/*"), payload.get("max_results", 20)
            )
        log.warning("FilesystemTool: unknown action '%s'", action)
        return None
