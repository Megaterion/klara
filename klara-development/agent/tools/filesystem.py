"""
filesystem.py — Local filesystem read/index access for Klara.
Read-only by default; restricted to allowed paths.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from agent.schemas.tool_contracts import ToolResult

logger = logging.getLogger(__name__)

# Default allowed root paths (configurable)
DEFAULT_ALLOWED_ROOTS = [
    str(Path.home()),
    "/app/shared-data",
]
MAX_FILE_BYTES = 65536


class FilesystemAgent:
    def __init__(self, config: dict) -> None:
        self.allowed_roots: list[str] = config.get("filesystem_allowed_roots", DEFAULT_ALLOWED_ROOTS)
        self._user_id = config.get("user_id", "user")

    async def open(self) -> None:
        logger.info("FilesystemAgent ready. Allowed roots: %s", self.allowed_roots)

    async def close(self) -> None:
        pass

    def _is_allowed(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        for root in self.allowed_roots:
            root_path = Path(root).expanduser().resolve()
            if resolved.is_relative_to(root_path):
                return True
        return False

    async def read_file(self, path: str, max_bytes: int = 8192) -> ToolResult:
        """Read a text file. Returns content as string."""
        p = Path(path)
        if not self._is_allowed(p):
            return ToolResult(tool="filesystem.read", success=False, error=f"Path not in allowed roots: {path}")
        if not p.exists():
            return ToolResult(tool="filesystem.read", success=False, error=f"File not found: {path}")
        if not p.is_file():
            return ToolResult(tool="filesystem.read", success=False, error=f"Not a file: {path}")
        try:
            cap = min(max_bytes, MAX_FILE_BYTES)
            content = p.read_bytes()[:cap].decode("utf-8", errors="replace")
            return ToolResult(tool="filesystem.read", success=True, data=content)
        except OSError as exc:
            return ToolResult(tool="filesystem.read", success=False, error=str(exc))

    async def list_dir(self, path: str, recursive: bool = False) -> ToolResult:
        """List directory contents."""
        p = Path(path)
        if not self._is_allowed(p):
            return ToolResult(tool="filesystem.list", success=False, error=f"Path not in allowed roots: {path}")
        if not p.exists() or not p.is_dir():
            return ToolResult(tool="filesystem.list", success=False, error=f"Not a directory: {path}")
        try:
            if recursive:
                entries = [str(f.relative_to(p)) for f in p.rglob("*") if f.is_file()][:200]
            else:
                entries = sorted(os.listdir(p))[:200]
            return ToolResult(tool="filesystem.list", success=True, data=entries)
        except OSError as exc:
            return ToolResult(tool="filesystem.list", success=False, error=str(exc))

    async def file_info(self, path: str) -> ToolResult:
        """Return metadata about a file/directory."""
        p = Path(path)
        if not self._is_allowed(p):
            return ToolResult(tool="filesystem.info", success=False, error=f"Path not in allowed roots: {path}")
        if not p.exists():
            return ToolResult(tool="filesystem.info", success=False, error=f"Not found: {path}")
        stat = p.stat()
        return ToolResult(
            tool="filesystem.info",
            success=True,
            data={
                "path": str(p.resolve()),
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            },
        )
