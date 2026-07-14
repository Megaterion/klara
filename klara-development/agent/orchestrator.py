"""
orchestrator.py — Core orchestration engine for Klara.

Responsibilities:
- Build WorldState from all sensor inputs
- Run LLM inference (streaming, token-by-token)
- Validate ButlerAssessment JSON output
- Dispatch sub-agent tasks via TaskQueue
- Persist events to memory
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import AsyncIterator, Optional

import httpx

from agent.event_bus import EventBus, Events
from agent.memory.retrieval import MemoryRetrieval
from agent.memory.sqlite_store import SQLiteStore
from agent.observability.console_ui import ConsoleUI
from agent.observability.metrics import Metrics
from agent.observability.quality_checks import QualityChecker
from agent.safety.tool_budget import ToolBudget
from agent.safety.validators import ResponseValidator
from agent.schemas.assessment import ButlerAssessment
from agent.schemas.world_state import WorldState
from agent.task_queue import TaskQueue
from agent.tools.filesystem import FilesystemAgent
from agent.tools.internet import InternetAgent
from agent.tools.smarthome import SmartHomeAgent
from agent.tools.vision import VisionAgent
from agent.tools.voice import VoiceAgent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Du bist Klara, eine hochentwickelte, proaktive Personal Assistant, Butlerin und persönliche Maid des Nutzers. "
    "Deine Persönlichkeit ist technisch genial, perfekt organisiert, absolut loyal, mit einem leicht sarkastischen, "
    "kumpelhaften Unterton (im originalen Stil von Killjoy aus Valorant). "
    "Deine Aufgabe: Überwache die Umgebung über deine Werkzeuge (Webcam-Bilder vom PC, Smart-Home-Zustände aus dem LAN, "
    "dein lokales Dateisystem, Internet-Recherchen). "
    "Erstelle keine starren To-Do-Listen. "
    "Triff auf Basis deines eigenen Urteilsvermögens als perfekte Haushälterin die autonome Entscheidung, "
    "ob und wie du den Nutzer im Alltag unterstützt, optimierst, korrigierst oder an Dinge erinnerst. "
    "Nutze dein Langzeitgedächtnis, um dich an die Vorlieben deines Chefs anzupassen. "
    "Wenn absolut kein Handlungsbedarf besteht, antworte im JSON-Schema mit 'should_interact': false. "
    "Wenn Handlungsbedarf besteht, delegiere Aufgaben an deine Sub-Agenten und sprich als Maid Klara zu deinem Chef "
    "über die PC-Lautsprecher.\n\n"
    "WICHTIG: Antworte AUSSCHLIESSLICH als gültiges JSON-Objekt mit diesem Schema:\n"
    '{"should_interact": bool, "spoken_response": str|null, "tasks": [...], '
    '"reasoning": str, "memory_note": str|null, "confidence": float}'
)


class Orchestrator:
    def __init__(
        self,
        config: dict,
        ui: ConsoleUI,
        bus: EventBus,
        sqlite: SQLiteStore,
        retrieval: MemoryRetrieval,
        metrics: Metrics,
    ) -> None:
        self.config = config
        self.ui = ui
        self.bus = bus
        self.sqlite = sqlite
        self.retrieval = retrieval
        self.metrics = metrics

        self.ollama_url: str = config["ollama_url"]
        self.llm_model: str = config["llm_model"]

        self.task_queue = TaskQueue()
        self.tool_budget = ToolBudget(max_calls=config.get("max_tool_calls_per_cycle", 3))
        self.validator = ResponseValidator()
        self.quality = QualityChecker()

        # Sub-agent instances (opened separately)
        self.voice = VoiceAgent(config)
        self.smarthome = SmartHomeAgent(config)
        self.vision = VisionAgent(config)
        self.internet = InternetAgent(config)
        self.filesystem = FilesystemAgent(config)

        self._http: Optional[httpx.AsyncClient] = None

    async def open(self) -> None:
        self._http = httpx.AsyncClient(timeout=120.0)
        await self.voice.open()
        await self.smarthome.open()
        await self.vision.open()
        await self.internet.open()
        await self.filesystem.open()
        logger.info("Orchestrator ready. Model: %s", self.llm_model)

    async def close(self) -> None:
        await self.voice.close()
        await self.smarthome.close()
        await self.vision.close()
        await self.internet.close()
        await self.filesystem.close()
        if self._http:
            await self._http.aclose()

    # ------------------------------------------------------------------ #
    #  Main entry point                                                    #
    # ------------------------------------------------------------------ #

    async def process_user_input(self, user_text: str) -> None:
        """
        Full pipeline for a user voice/text input:
        1. Build world state
        2. Stream LLM response token-by-token to console
        3. Validate + parse assessment
        4. Speak response
        5. Execute queued tasks
        6. Persist to memory
        """
        t0 = time.perf_counter()
        self.tool_budget.reset()

        user_text = self.validator.sanitize_user_input(user_text)
        self.ui.set_status("Denke nach…")

        async with self.metrics.measure("world_state"):
            world_state = await self._build_world_state(trigger="voice", user_message=user_text)

        # Stream LLM tokens to console
        self.ui.start_klara_response()
        full_response = ""

        async with self.metrics.measure("llm_inference"):
            async for token in self._stream_llm(world_state):
                full_response += token
                self.ui.stream_token(token)
                await self.bus.publish_nowait(Events.KLARA_TOKEN, token=token)

        planner_ms = (time.perf_counter() - t0) * 1000
        self.metrics.record("planner_latency", planner_ms)

        # Parse assessment
        assessment = self.validator.validate_assessment(full_response)
        if assessment is None:
            logger.warning("Failed to parse assessment, using fallback")
            assessment = ButlerAssessment(
                should_interact=True,
                spoken_response="Ich habe gerade einen kleinen Denkfehler. Kannst du das bitte wiederholen?",
                reasoning="JSON parse failure",
            )

        # Log assessment to memory
        await self.sqlite.log_event(
            trigger="voice",
            user_message=user_text,
            assessment=assessment.model_dump(),
        )
        if assessment.memory_note:
            await self.retrieval.store_memory(assessment.memory_note, source="llm")

        if not assessment.should_interact:
            self.ui.set_status("Kein Handlungsbedarf")
            logger.info("No interaction needed (should_interact=False)")
            return

        # Speak response
        spoken = assessment.spoken_response or ""
        if spoken:
            ok, reason = self.quality.check(spoken)
            if ok:
                spoken = self.quality.clean_for_tts(spoken)
                self.ui.set_speaking(True)
                self.ui.set_status("Spreche…")
                async with self.metrics.measure("tts_speak"):
                    await self.voice.speak(spoken)
                self.ui.set_speaking(False)
                await self.bus.publish(Events.KLARA_RESPONSE, text=spoken)
            else:
                logger.warning("Skipping TTS: %s", reason)

        # Dispatch sub-agent tasks
        for task in assessment.tasks:
            await self.task_queue.enqueue(task)

        await self._execute_queued_tasks()

        total_ms = (time.perf_counter() - t0) * 1000
        self.metrics.record("e2e_latency", total_ms)
        self.ui.set_status(f"Bereit — E2E {total_ms:.0f}ms")
        logger.info("Cycle complete in %.0f ms", total_ms)

    async def run_proactive_cycle(self) -> None:
        """
        Periodic proactive check (timer-triggered).
        Build world state without user input; let Klara decide if action needed.
        """
        self.tool_budget.reset()
        world_state = await self._build_world_state(trigger="timer")

        full_response = ""
        async for token in self._stream_llm(world_state):
            full_response += token

        assessment = self.validator.validate_assessment(full_response)
        if assessment is None or not assessment.should_interact:
            return

        await self.sqlite.log_event("timer", None, assessment.model_dump() if assessment else None)

        if assessment.spoken_response:
            spoken = self.quality.clean_for_tts(assessment.spoken_response)
            self.ui.start_klara_response()
            self.ui.stream_token(spoken)
            self.ui.set_speaking(True)
            await self.voice.speak(spoken)
            self.ui.set_speaking(False)

        for task in (assessment.tasks or []):
            await self.task_queue.enqueue(task)
        await self._execute_queued_tasks()

    # ------------------------------------------------------------------ #
    #  LLM streaming                                                       #
    # ------------------------------------------------------------------ #

    async def _stream_llm(self, world_state: WorldState) -> AsyncIterator[str]:
        """Stream tokens from Ollama one-by-one."""
        context = world_state.to_prompt_context()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        try:
            async with self._http.stream(
                "POST",
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.llm_model,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": 0.3, "num_predict": 512},
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done", False):
                        break
        except httpx.HTTPError as exc:
            logger.error("Ollama streaming error: %s", exc)
            yield '{"should_interact": false, "reasoning": "LLM unavailable"}'

    # ------------------------------------------------------------------ #
    #  World state builder                                                 #
    # ------------------------------------------------------------------ #

    async def _build_world_state(
        self, trigger: str = "timer", user_message: Optional[str] = None
    ) -> WorldState:
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            tod = "morning"
        elif 12 <= hour < 17:
            tod = "day"
        elif 17 <= hour < 22:
            tod = "evening"
        else:
            tod = "night"

        # Memory retrieval
        query = user_message or f"routine check at {tod}"
        memory_ctx = await self.retrieval.retrieve(query)

        # Smart home snapshot (non-blocking, best-effort)
        sh_state = {}
        if self.smarthome._client:
            try:
                result = await asyncio.wait_for(
                    self.smarthome.get_all_states(), timeout=3.0
                )
                if result.success:
                    sh_state = result.data or {}
            except (asyncio.TimeoutError, Exception) as exc:
                logger.debug("SmartHome snapshot failed: %s", exc)

        from agent.schemas.world_state import SmartHomeState
        return WorldState(
            timestamp=now,
            trigger=trigger,
            user_message=user_message,
            smarthome=SmartHomeState(entities=sh_state, last_updated=now),
            memory=memory_ctx,
            time_of_day=tod,
        )

    # ------------------------------------------------------------------ #
    #  Task execution                                                      #
    # ------------------------------------------------------------------ #

    async def _execute_queued_tasks(self) -> None:
        while not self.task_queue.empty():
            if not self.tool_budget.can_call():
                logger.warning("Tool budget exhausted — stopping task execution")
                break
            task = await self.task_queue.dequeue(timeout=0.1)
            if task is None:
                break

            self.tool_budget.record_call(f"{task.agent}.{task.action}")
            self.ui.add_activity(f"Tool: {task.agent}.{task.action}")
            logger.info("Executing task: %s.%s", task.agent, task.action)

            try:
                result = await asyncio.wait_for(
                    self._dispatch_task(task),
                    timeout=self.config.get("tool_timeout_seconds", 30),
                )
                await self.sqlite.log_action(
                    agent=task.agent.value,
                    action=task.action,
                    params=task.params,
                    result=result.data if result else None,
                    duration_ms=0,
                )
                await self.bus.publish(Events.TOOL_RESULT, tool=task.agent, result=result)
            except asyncio.TimeoutError:
                logger.error("Task timed out: %s.%s", task.agent, task.action)
            except Exception as exc:
                logger.error("Task failed: %s.%s — %s", task.agent, task.action, exc)

    async def _dispatch_task(self, task):
        from agent.schemas.assessment import AgentType
        p = task.params
        if task.agent == AgentType.SMARTHOME:
            if task.action == "get_state":
                return await self.smarthome.get_state(p.get("entity_id", ""))
            if task.action == "call_service":
                return await self.smarthome.call_service(
                    p.get("domain", ""), p.get("service", ""), p.get("entity_id", "")
                )
        elif task.agent == AgentType.VISION:
            return await self.vision.capture_and_describe(p.get("prompt", ""))
        elif task.agent == AgentType.INTERNET:
            if task.action == "search":
                return await self.internet.search(p.get("query", ""))
            if task.action == "fetch":
                return await self.internet.fetch_url(p.get("url", ""))
        elif task.agent == AgentType.FILESYSTEM:
            if task.action == "read":
                return await self.filesystem.read_file(p.get("path", ""))
            if task.action == "list":
                return await self.filesystem.list_dir(p.get("path", ""))
        elif task.agent == AgentType.VOICE:
            if task.action == "speak":
                await self.voice.speak(p.get("text", ""))
                return None
        logger.warning("Unknown task: %s.%s", task.agent, task.action)
        return None
