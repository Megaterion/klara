"""
Pydantic schemas for Klara's butler assessment and sub-agent tasks.
All LLM JSON output is validated against these models.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TaskPriority(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class AgentType(str, Enum):
    VOICE = "voice"
    SMARTHOME = "smarthome"
    VISION = "vision"
    INTERNET = "internet"
    FILESYSTEM = "filesystem"


class SubAgentTask(BaseModel):
    """A single task delegated to a sub-agent."""

    agent: AgentType = Field(..., description="Which sub-agent handles this task")
    action: str = Field(..., description="Action to perform (tool-specific verb)")
    params: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    priority: TaskPriority = Field(default=TaskPriority.NORMAL)
    reason: str = Field(default="", description="Why this task is needed (internal log)")

    @field_validator("action")
    @classmethod
    def action_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("action must not be empty")
        return v.strip()


class ButlerAssessment(BaseModel):
    """
    The structured JSON output Klara produces every cycle.
    The LLM must produce valid JSON matching this schema.
    """

    should_interact: bool = Field(
        ...,
        description="True if Klara should speak/act, False if no action needed",
    )
    spoken_response: Optional[str] = Field(
        default=None,
        description="Text Klara will speak aloud (only when should_interact=True)",
    )
    tasks: list[SubAgentTask] = Field(
        default_factory=list,
        description="Sub-agent tasks to execute in priority order",
    )
    reasoning: str = Field(
        default="",
        description="Internal reasoning / chain of thought (not spoken)",
    )
    memory_note: Optional[str] = Field(
        default=None,
        description="Fact to persist to long-term memory, if any",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Assessment confidence (0-1)",
    )

    @field_validator("spoken_response")
    @classmethod
    def response_required_when_interact(cls, v: Optional[str], info: Any) -> Optional[str]:
        # We can't easily access should_interact in a field validator without model_validator;
        # this check is done in orchestrator instead.
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "should_interact": True,
                "spoken_response": "Chef, die Heizung im Wohnzimmer ist noch an. Soll ich sie ausschalten?",
                "tasks": [
                    {
                        "agent": "smarthome",
                        "action": "get_state",
                        "params": {"entity_id": "climate.wohnzimmer"},
                        "priority": "normal",
                        "reason": "Checking current heating state",
                    }
                ],
                "reasoning": "It's past midnight and heating is still on.",
                "memory_note": "User often forgets heating at night.",
                "confidence": 0.92,
            }
        }
