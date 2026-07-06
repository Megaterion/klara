"""
orchestrator.py – Core Orchestrator for Klara.

Responsibilities:
1. Build the WorldState from all sensor inputs and memory retrieval.
2. Call the Planner LLM (fast, JSON-only).
3. Optionally call the Responder LLM for richer voice text.
4. Validate the ButlerAssessment.
5. Dispatch tasks to sub-agents via the TaskQueue with budget enforcement.
6. Persist the cycle result to memory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from .event_bus import Event, EventType
from .memory.retrieval import MemoryRetrieval
from .memory.sqlite_store import SQLiteStore
from .observability.metrics import KlaraMetrics, timer as metrics_timer
from .observability.tracing import cycle_trace
from .safety.rate_limiter import RateLimiter
from .safety.tool_budget import ToolBudget
from .safety.validators import sanitize_external_content, validate_assessment
from .schemas.assessment import ButlerAssessment, SubAgentTask
from .schemas.world_state import MemoryContext, SmarthomeState, WorldState
from .task_queue import TaskQueue
from .tools.filesystem import FilesystemTool
from .tools.internet import InternetTool
from .tools.smarthome import SmarthomeTool
from .tools.vision import VisionTool
from .tools.voice import VoiceTool

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        cfg: dict[str, Any],
        sqlite: SQLiteStore,
        retrieval: MemoryRetrieval,
        metrics: KlaraMetrics,
        smarthome: SmarthomeTool,
        voice: VoiceTool,
        filesystem: FilesystemTool,
        vision: VisionTool,
        internet: InternetTool,
    ) -> None:
        self.cfg = cfg
        self.sqlite = sqlite
        self.retrieval = retrieval
        self.metrics = metrics
        self.smarthome = smarthome
        self.voice = voice
        self.filesystem = filesystem
        self.vision = vision
        self.internet = internet

        safety_cfg = cfg.get("safety", {})
        self.tool_budget = ToolBudget(
            max_tool_calls=safety_cfg.get("max_tool_calls_per_cycle", 3),
            tool_timeout_seconds=safety_cfg.get("tool_timeout_seconds", 15.0),
            llm_timeout_seconds=safety_cfg.get("llm_timeout_seconds", 30.0),
        )
        self.rate_limiter = RateLimiter(
            rate=safety_cfg.get("rate_limit_calls_per_minute", 20),
            period=60.0,
        )
        self.task_queue = TaskQueue()
        self.user_id: str = cfg.get("user_id", "master_chef")
        self.max_json_retries: int = safety_cfg.get("max_retries_on_invalid_json", 2)

        self._ollama_url: str = cfg["ollama_url"]
        self._planner_model: str = cfg["llm_planner_model"]
        self._responder_model: str = cfg["llm_responder_model"]
        self._system_prompt: str = cfg.get("butler_system_prompt", "")

    # ------------------------------------------------------------------
    # Main entry point: handle one event
    # ------------------------------------------------------------------

    async def handle_event(self, event: Event) -> None:
        with cycle_trace(user_id=self.user_id, event_type=event.type.value) as trace:
            await self.rate_limiter.acquire("orchestrator_cycle")
            e2e_start = time.monotonic()
            self.metrics.cycles_total.inc()

            # 1. Build WorldState
            world_state = await self._build_world_state(event)

            # 2. Call Planner LLM
            assessment = await self._plan(world_state)
            if assessment is None:
                log.warning("[%s] Planner returned no valid assessment – skipping cycle.", trace.cycle_id)
                return

            if not assessment.should_interact:
                log.debug("[%s] No interaction needed (reasoning: %.80s)", trace.cycle_id, assessment.reasoning)
                return

            self.metrics.cycles_interacted.inc()
            log.info("[%s] Interaction: %d tasks queued.", trace.cycle_id, len(assessment.tasks))

            # 3. Enqueue tasks
            await self.task_queue.enqueue_all(assessment.tasks)

            # 4. Execute tasks
            budget = self.tool_budget.new_cycle()
            event_id = self.sqlite.log_event(
                user_id=self.user_id,
                event_type=event.type.value,
                user_input=event.payload.get("text"),
                reasoning=assessment.reasoning,
            )

            voice_text: str | None = None
            tasks = await self.task_queue.drain()
            for task in tasks:
                if not budget.consume(task.sub_agent_name):
                    log.warning("Budget exhausted – skipping %s/%s", task.sub_agent_name, task.action)
                    break
                result = await self._execute_task(task, budget)
                self.sqlite.log_action(
                    event_id=event_id,
                    sub_agent=task.sub_agent_name,
                    action=task.action,
                    payload=task.payload,
                    result=result,
                    success=result is not None,
                )
                if task.sub_agent_name == "voice" and task.action == "speak":
                    voice_text = task.payload.get("text")

            # 5. Persist cycle to memory
            self.retrieval.store_cycle(
                user_id=self.user_id,
                user_input=event.payload.get("text"),
                response=voice_text or assessment.reasoning,
            )

            e2e_elapsed = time.monotonic() - e2e_start
            self.metrics.e2e_latency.record(e2e_elapsed)
            log.info("[%s] Cycle complete in %.2fs", trace.cycle_id, e2e_elapsed)

    # ------------------------------------------------------------------
    # World State builder
    # ------------------------------------------------------------------

    async def _build_world_state(self, event: Event) -> WorldState:
        mem_query = event.payload.get("text") or event.type.value

        with metrics_timer(self.metrics.memory_retrieval_latency):
            mem_ctx = self.retrieval.retrieve(self.user_id, mem_query)

        if mem_ctx.facts or mem_ctx.preferences:
            self.metrics.memory_hits.inc()
        else:
            self.metrics.memory_misses.inc()

        # Fetch smarthome states (non-blocking, best-effort)
        try:
            raw_states = await asyncio.wait_for(
                self.smarthome.get_all_states(),
                timeout=self.tool_budget.tool_timeout,
            )
            sm_state = SmarthomeState(entities=raw_states)
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("Smarthome state fetch failed: %s", exc)
            sm_state = SmarthomeState()

        return WorldState(
            user_input=event.payload.get("text"),
            smarthome=sm_state,
            memory=mem_ctx,
            active_event_type=event.type.value,
        )

    # ------------------------------------------------------------------
    # Planner LLM
    # ------------------------------------------------------------------

    async def _plan(self, world_state: WorldState) -> ButlerAssessment | None:
        prompt = self._build_planner_prompt(world_state)
        raw: str | None = None

        for attempt in range(1, self.max_json_retries + 2):
            with metrics_timer(self.metrics.planner_latency):
                raw = await self._call_ollama(
                    model=self._planner_model,
                    prompt=prompt,
                    force_json=True,
                    timeout=self.cfg.get("safety", {}).get("llm_timeout_seconds", 30.0),
                )
            if raw is None:
                continue
            assessment = validate_assessment(raw)
            if assessment is not None:
                self.metrics.json_valid.inc()
                return assessment
            self.metrics.json_invalid.inc()
            log.warning("Invalid JSON from planner (attempt %d/%d)", attempt, self.max_json_retries + 1)

        return None

    def _build_planner_prompt(self, world_state: WorldState) -> str:
        return (
            f"{self._system_prompt}\n\n"
            f"=== Aktueller Zustand ===\n"
            f"{world_state.to_prompt_text()}\n\n"
            "=== Anweisung ===\n"
            "Beantworte ausschließlich mit einem gültigen JSON-Objekt im ButlerAssessment-Format:\n"
            '{"should_interact": bool, "reasoning": "...", "tasks": [...]}'
        )

    # ------------------------------------------------------------------
    # Task execution dispatcher
    # ------------------------------------------------------------------

    async def _execute_task(self, task: SubAgentTask, budget: Any) -> Any:
        self.metrics.tool_calls.inc()
        payload = task.payload

        try:
            if task.sub_agent_name == "smarthome":
                return await asyncio.wait_for(
                    self.smarthome.dispatch(task.action, payload),
                    timeout=budget.tool_timeout_seconds,
                )
            if task.sub_agent_name == "voice":
                return await asyncio.wait_for(
                    self.voice.dispatch(task.action, payload),
                    timeout=budget.tool_timeout_seconds,
                )
            if task.sub_agent_name == "filesystem":
                return await asyncio.wait_for(
                    self.filesystem.dispatch(task.action, payload),
                    timeout=budget.tool_timeout_seconds,
                )
            if task.sub_agent_name == "vision":
                return await asyncio.wait_for(
                    self.vision.dispatch(task.action, payload),
                    timeout=budget.tool_timeout_seconds,
                )
            if task.sub_agent_name == "internet":
                return await asyncio.wait_for(
                    self.internet.dispatch(task.action, payload),
                    timeout=budget.tool_timeout_seconds,
                )
            log.warning("Unknown sub-agent: %s", task.sub_agent_name)
            return None
        except asyncio.TimeoutError:
            log.error("Task %s/%s timed out after %.0fs", task.sub_agent_name, task.action, budget.tool_timeout_seconds)
            self.metrics.tool_errors.inc()
            return None
        except Exception as exc:
            log.error("Task %s/%s failed: %s", task.sub_agent_name, task.action, exc)
            self.metrics.tool_errors.inc()
            return None

    # ------------------------------------------------------------------
    # Ollama helper
    # ------------------------------------------------------------------

    async def _call_ollama(
        self,
        model: str,
        prompt: str,
        force_json: bool = False,
        timeout: float = 30.0,
    ) -> str | None:
        url = f"{self._ollama_url.rstrip('/')}/api/generate"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3},
        }
        if force_json:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json().get("response", "").strip()
        except httpx.HTTPStatusError as exc:
            log.error("Ollama HTTP error: %s", exc)
        except asyncio.TimeoutError:
            log.error("Ollama call timed out after %.0fs", timeout)
        except Exception as exc:
            log.error("Ollama call failed: %s", exc)
        return None
