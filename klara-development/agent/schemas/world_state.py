"""
World state snapshot assembled before each LLM inference cycle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SmartHomeState(BaseModel):
    entities: dict[str, Any] = Field(default_factory=dict)
    last_updated: Optional[datetime] = None


class MemoryContext(BaseModel):
    recent_events: list[str] = Field(default_factory=list)
    relevant_facts: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class WorldState(BaseModel):
    """
    Full context snapshot passed to the planner LLM each cycle.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trigger: str = Field(default="timer", description="What triggered this cycle: timer/voice/motion/ha_event")
    user_message: Optional[str] = Field(default=None, description="Spoken input from user, if any")
    smarthome: SmartHomeState = Field(default_factory=SmartHomeState)
    memory: MemoryContext = Field(default_factory=MemoryContext)
    vision_summary: Optional[str] = Field(default=None, description="Short description of current webcam frame")
    time_of_day: str = Field(default="day", description="morning/day/evening/night")
    previous_interaction_minutes_ago: Optional[float] = None

    def to_prompt_context(self) -> str:
        """Render world state as a compact context string for the LLM prompt."""
        lines = [
            f"[Zeitstempel] {self.timestamp.strftime('%Y-%m-%d %H:%M')} ({self.time_of_day})",
            f"[Auslöser] {self.trigger}",
        ]
        if self.user_message:
            lines.append(f"[Nutzernachricht] {self.user_message}")
        if self.smarthome.entities:
            entity_summary = "; ".join(
                f"{k}={v}" for k, v in list(self.smarthome.entities.items())[:10]
            )
            lines.append(f"[SmartHome] {entity_summary}")
        if self.vision_summary:
            lines.append(f"[Kamera] {self.vision_summary}")
        if self.memory.relevant_facts:
            lines.append("[Erinnerungen] " + " | ".join(self.memory.relevant_facts[:5]))
        if self.memory.preferences:
            lines.append("[Präferenzen] " + " | ".join(self.memory.preferences[:5]))
        if self.previous_interaction_minutes_ago is not None:
            lines.append(f"[Letzte Interaktion] vor {self.previous_interaction_minutes_ago:.0f} Minuten")
        return "\n".join(lines)
