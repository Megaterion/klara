"""
internet.py — Web search and URL fetching.
Whitelist-free but content-limited and injection-guarded.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from agent.schemas.tool_contracts import ToolResult

logger = logging.getLogger(__name__)

# Absolute max chars returned from any web page
MAX_CONTENT_CHARS = 8000
# Domains that are always blocked
BLOCKED_DOMAINS = frozenset(["localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"])


class InternetAgent:
    def __init__(self, config: dict) -> None:
        self._timeout = config.get("tool_timeout_seconds", 30)
        self._client: Optional[httpx.AsyncClient] = None

    async def open(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": "Klara-AI-Assistant/1.0"},
        )
        logger.info("InternetAgent ready")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def search(self, query: str, max_results: int = 5) -> ToolResult:
        """DuckDuckGo text search. Returns list of {title, url, snippet} dicts."""
        from duckduckgo_search import DDGS

        try:
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=min(max_results, 10)))
            return ToolResult(tool="internet.search", success=True, data=results)
        except Exception as exc:
            logger.error("DuckDuckGo search error: %s", exc)
            return ToolResult(tool="internet.search", success=False, error=str(exc))

    async def fetch_url(self, url: str, max_chars: int = 2000) -> ToolResult:
        """Fetch and extract text content from a URL."""
        if not self._client:
            return ToolResult(tool="internet.fetch", success=False, error="Client not initialized")

        from urllib.parse import urlparse
        import ipaddress
        import socket

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            return ToolResult(tool="internet.fetch", success=False, error="Invalid URL")
        if host in BLOCKED_DOMAINS or host.endswith(".local"):
            return ToolResult(tool="internet.fetch", success=False, error="Blocked host")

        try:
            for *_rest, sockaddr in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return ToolResult(tool="internet.fetch", success=False, error="Blocked address")
        except socket.gaierror:
            return ToolResult(tool="internet.fetch", success=False, error="DNS lookup failed")

        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove scripts and styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Limit content
            capped = text[: min(max_chars, MAX_CONTENT_CHARS)]
            return ToolResult(tool="internet.fetch", success=True, data=capped)
        except httpx.HTTPError as exc:
            logger.error("URL fetch failed %s: %s", url, exc)
            return ToolResult(tool="internet.fetch", success=False, error=str(exc))
