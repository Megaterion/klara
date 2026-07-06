"""
schemas/assessment.py – Pydantic schemas for structured LLM output.

The LLM is forced to produce a ButlerAssessment JSON object every cycle.
No free-text decisions, no keyword checks – everything flows through
these typed schemas.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SubAgentName(str, Enum):
    smarthome = "smarthome"
    voice = "voice"
    filesystem = "filesystem"
    internet = "internet"
    vision = "vision"


class SubAgentTask(BaseModel):
    """A single task delegated to one of Klara's sub-agents."""

    sub_agent_name: SubAgentName = Field(
        description="Target sub-agent: smarthome, voice, filesystem, internet, vision"
    )
    action: str = Field(
        description="Abstract action the sub-agent should perform (e.g. 'execute_service', 'speak', 'read_file', 'web_search')"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Dynamic JSON parameters for the action",
    )
    priority: int = Field(
        default=2,
        ge=0,
        le=3,
        description="Priority: 0=critical, 1=high, 2=normal, 3=background",
    )


class ButlerAssessment(BaseModel):
    """
    The top-level JSON object Klara returns each reasoning cycle.

    - should_interact=False  → stay silent, no tasks executed.
    - should_interact=True   → tasks list is non-empty and processed in priority order.
    """

    should_interact: bool = Field(
        description="Must Klara proactively engage with the user in this moment?"
    )
    reasoning: str = Field(
        description="Internal logical justification for the decision (written to system log only)"
    )
    tasks: list[SubAgentTask] = Field(
        default_factory=list,
        description="Ordered list of sub-agent tasks to execute",
    )

    model_config = {"use_enum_values": True}
