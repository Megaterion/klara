"""
tools/smarthome.py – Home Assistant REST/WebSocket integration.

Reads all entity states from the HA REST API and executes services.
Web socket subscriptions for push-based events are handled via the EventBus.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SmarthomeTool:
    def __init__(self, ha_url: str, ha_token: str, timeout: float = 10.0) -> None:
        self.base_url = ha_url.rstrip("/")
        self.timeout = timeout
        self._headers = {
            "Authorization": "Bearer " + ha_token,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # State reading
    # ------------------------------------------------------------------

    async def get_all_states(self) -> dict[str, Any]:
        """Return a dict of entity_id -> state from Home Assistant."""
        url = f"{self.base_url}/states"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url, headers=self._headers)
                r.raise_for_status()
                entities = r.json()
                return {e["entity_id"]: e["state"] for e in entities}
        except httpx.HTTPStatusError as exc:
            log.error("HA get_all_states HTTP error: %s", exc)
        except Exception as exc:
            log.error("HA get_all_states error: %s", exc)
        return {}

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        url = f"{self.base_url}/states/{entity_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url, headers=self._headers)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            log.error("HA get_state(%s) error: %s", entity_id, exc)
        return None

    # ------------------------------------------------------------------
    # Service execution
    # ------------------------------------------------------------------

    async def execute_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        url = f"{self.base_url}/services/{domain}/{service}"
        payload: dict[str, Any] = {"entity_id": entity_id}
        if extra:
            payload.update(extra)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=self._headers, json=payload)
                r.raise_for_status()
                log.info("HA service %s.%s called on %s", domain, service, entity_id)
                return True
        except Exception as exc:
            log.error("HA execute_service error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Entry point for task dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "execute_service":
            return await self.execute_service(
                domain=payload["domain"],
                service=payload["service"],
                entity_id=payload["entity_id"],
                extra=payload.get("extra"),
            )
        if action == "get_state":
            return await self.get_state(payload["entity_id"])
        log.warning("SmarthomeTool: unknown action '%s'", action)
        return None
