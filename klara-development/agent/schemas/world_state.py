"""
schemas/world_state.py – Snapshot of Klara's environment at a given moment.

Assembled by the Orchestrator before each LLM call so the model has
full situational awareness without hard-coded sensor logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SmarthomeState(BaseModel):
    """Raw snapshot from Home Assistant (entities -> state dict)."""

    entities: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryContext(BaseModel):
    """Retrieved memory facts relevant to the current cycle."""

    facts: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    recent_events: list[str] = Field(default_factory=list)


class WorldState(BaseModel):
    """
    Central snapshot passed to the LLM each reasoning cycle.

    The Orchestrator fills this from all available sensors / memory
    retrieval results before calling the planner model.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_input: str | None = Field(
        default=None,
        description="Direct text or voice input from the user (if any)",
    )
    smarthome: SmarthomeState = Field(default_factory=SmarthomeState)
    memory: MemoryContext = Field(default_factory=MemoryContext)
    filesystem_summary: str | None = Field(
        default=None,
        description="Brief summary of recently accessed/indexed local files",
    )
    vision_description: str | None = Field(
        default=None,
        description="Webcam scene description (populated on vision trigger)",
    )
    active_event_type: str = Field(
        default="timer",
        description="What triggered this cycle: 'user_input', 'smarthome_event', 'timer', 'motion'",
    )

    def to_prompt_text(self) -> str:
        """Render the world state as a compact, human-readable prompt section."""
        parts: list[str] = [
            f"[Zeitstempel] {self.timestamp.isoformat()}",
            f"[Trigger] {self.active_event_type}",
        ]
        if self.user_input:
            parts.append(f"[Nutzer-Input] {self.user_input}")
        if self.smarthome.entities:
            parts.append(f"[Smart-Home] {len(self.smarthome.entities)} Entitäten geladen")
        if self.memory.facts:
            parts.append("[Fakten aus Gedächtnis]\n" + "\n".join(f"  • {f}" for f in self.memory.facts))
        if self.memory.preferences:
            parts.append("[Präferenzen]\n" + "\n".join(f"  • {p}" for p in self.memory.preferences))
        if self.filesystem_summary:
            parts.append(f"[Dateisystem] {self.filesystem_summary}")
        if self.vision_description:
            parts.append(f"[Kamera] {self.vision_description}")
        return "\n".join(parts)
