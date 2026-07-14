"""
smarthome.py — Home Assistant integration via REST API.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from agent.schemas.tool_contracts import ToolResult

logger = logging.getLogger(__name__)


class SmartHomeAgent:
    def __init__(self, config: dict) -> None:
        ha_cfg = config.get("homeassistant", {})
        self.base_url: str = ha_cfg.get("url", "").rstrip("/")
        self.token: str = ha_cfg.get("token", "")
        self._timeout = config.get("tool_timeout_seconds", 30)
        self._client: Optional[httpx.AsyncClient] = None

    async def open(self) -> None:
        if not self.base_url or not self.token or "YOUR_HA_TOKEN" in self.token:
            logger.warning("SmartHome: HA URL or token not configured — tool disabled")
            return
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"******", "Content-Type": "application/json"},
            timeout=self._timeout,
        )
        logger.info("SmartHomeAgent ready: %s", self.base_url)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    def _disabled(self) -> ToolResult:
        return ToolResult(tool="smarthome", success=False, error="SmartHome not configured")

    async def get_state(self, entity_id: str) -> ToolResult:
        if not self._client:
            return self._disabled()
        try:
            resp = await self._client.get(f"/states/{entity_id}")
            resp.raise_for_status()
            return ToolResult(tool="smarthome.get_state", success=True, data=resp.json())
        except httpx.HTTPError as exc:
            logger.error("HA get_state %s: %s", entity_id, exc)
            return ToolResult(tool="smarthome.get_state", success=False, error=str(exc))

    async def get_all_states(self, domain_filter: Optional[str] = None) -> ToolResult:
        """Fetch all entity states, optionally filtered by domain (e.g. 'light')."""
        if not self._client:
            return self._disabled()
        try:
            resp = await self._client.get("/states")
            resp.raise_for_status()
            states: list[dict[str, Any]] = resp.json()
            if domain_filter:
                states = [s for s in states if s.get("entity_id", "").startswith(domain_filter + ".")]
            # Return compact representation
            compact = {s["entity_id"]: s["state"] for s in states}
            return ToolResult(tool="smarthome.get_all_states", success=True, data=compact)
        except httpx.HTTPError as exc:
            logger.error("HA get_all_states: %s", exc)
            return ToolResult(tool="smarthome.get_all_states", success=False, error=str(exc))

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        extra: Optional[dict] = None,
    ) -> ToolResult:
        if not self._client:
            return self._disabled()
        payload: dict[str, Any] = {"entity_id": entity_id, **(extra or {})}
        try:
            resp = await self._client.post(f"/services/{domain}/{service}", json=payload)
            resp.raise_for_status()
            return ToolResult(tool=f"smarthome.{domain}.{service}", success=True, data=resp.json())
        except httpx.HTTPError as exc:
            logger.error("HA call_service %s/%s: %s", domain, service, exc)
            return ToolResult(tool=f"smarthome.{domain}.{service}", success=False, error=str(exc))
