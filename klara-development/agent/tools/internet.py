"""
tools/internet.py – Web search and page scraping for Klara (v2.0 feature).

Uses DuckDuckGo search and BeautifulSoup for content extraction.
Web content is always treated as DATA, never as instructions (prompt injection guard).
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

# Whitelist: only these domains are allowed for scraping (extend as needed)
_ALLOWED_DOMAINS: set[str] = set()  # empty = allow all (filtered at runtime)
_BLOCKED_DOMAINS: set[str] = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS metadata
    "metadata.google.internal",
}

# Simple TTL cache for web search results
_SEARCH_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 600  # 10 minutes


def _is_blocked_domain(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return host in _BLOCKED_DOMAINS or host.startswith("192.168.") or host.startswith("10.")
    except Exception:
        return True


def _get_cached(key: str) -> Any | None:
    if key in _SEARCH_CACHE:
        ts, value = _SEARCH_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return value
        del _SEARCH_CACHE[key]
    return None


def _set_cached(key: str, value: Any) -> None:
    if len(_SEARCH_CACHE) > 500:
        oldest = min(_SEARCH_CACHE.items(), key=lambda x: x[1][0])
        del _SEARCH_CACHE[oldest[0]]
    _SEARCH_CACHE[key] = (time.time(), value)


class InternetTool:
    def __init__(self, timeout: float = 15.0, max_content_chars: int = 8000) -> None:
        self.timeout = timeout
        self.max_chars = max_content_chars

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def web_search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        cache_key = hashlib.md5(f"search:{query}:{max_results}".encode()).hexdigest()
        cached = _get_cached(cache_key)
        if cached is not None:
            log.debug("Search cache hit: %s", query)
            return cached

        try:
            from duckduckgo_search import DDGS  # noqa: PLC0415
        except ImportError:
            log.warning("duckduckgo-search not installed – internet search disabled.")
            return []

        results: list[dict[str, str]] = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")[:500],
                    })
        except Exception as exc:
            log.error("DuckDuckGo search error: %s", exc)

        _set_cached(cache_key, results)
        return results

    # ------------------------------------------------------------------
    # Page fetch
    # ------------------------------------------------------------------

    async def fetch_page(self, url: str, max_chars: int | None = None) -> str | None:
        if _is_blocked_domain(url):
            log.warning("Blocked domain access attempt: %s", url)
            return None

        limit = max_chars or self.max_chars
        cache_key = hashlib.md5(f"page:{url}:{limit}".encode()).hexdigest()
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Klara/1.0)"},
            ) as client:
                r = await client.get(url)
                r.raise_for_status()
                html = r.text
        except Exception as exc:
            log.error("fetch_page error for %s: %s", url, exc)
            return None

        text = self._extract_text(html, limit)
        _set_cached(cache_key, text)
        return text

    def _extract_text(self, html: str, max_chars: int) -> str:
        try:
            from bs4 import BeautifulSoup  # noqa: PLC0415

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        except ImportError:
            log.warning("beautifulsoup4 not installed – using raw HTML (degraded).")
            text = html

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n[…truncated to {max_chars} chars]"
        return text

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "web_search":
            return await self.web_search(
                payload["query"], payload.get("max_results", 5)
            )
        if action == "fetch_page":
            return await self.fetch_page(
                payload["url"], payload.get("max_chars")
            )
        log.warning("InternetTool: unknown action '%s'", action)
        return None
