"""
Strict input/output contracts for all tool calls.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    tool: str = Field(..., description="Tool name, e.g. 'smarthome.get_state'")
    params: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0


# --- Smart Home ---

class HAGetStateParams(BaseModel):
    entity_id: str


class HACallServiceParams(BaseModel):
    domain: str
    service: str
    entity_id: str
    extra: dict[str, Any] = Field(default_factory=dict)


# --- Vision ---

class VisionCaptureParams(BaseModel):
    camera_index: int = 0
    prompt: str = Field(default="Describe what you see in the image briefly.")


# --- Internet ---

class SearchParams(BaseModel):
    query: str
    max_results: int = Field(default=5, le=10)


class FetchURLParams(BaseModel):
    url: str
    max_chars: int = Field(default=2000, le=8000)


# --- Filesystem ---

class ReadFileParams(BaseModel):
    path: str
    max_bytes: int = Field(default=8192, le=65536)


class ListDirParams(BaseModel):
    path: str
    recursive: bool = False


# --- Voice ---

class SpeakParams(BaseModel):
    text: str
    language: Optional[str] = None  # overrides config default
