"""
schemas/tool_contracts.py – Typed input/output contracts for every sub-agent action.

Using strict schemas prevents the LLM from inventing unknown fields
and gives validators a concrete target.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Smarthome
# ---------------------------------------------------------------------------

class SmarthomeExecuteService(BaseModel):
    action: Literal["execute_service"] = "execute_service"
    domain: str = Field(description="HA domain, e.g. 'light', 'switch', 'climate'")
    service: str = Field(description="HA service, e.g. 'turn_on', 'turn_off', 'set_temperature'")
    entity_id: str = Field(description="Full entity_id, e.g. 'light.wohnzimmer'")
    extra: dict[str, Any] = Field(default_factory=dict, description="Additional service data")


class SmarthomeGetState(BaseModel):
    action: Literal["get_state"] = "get_state"
    entity_id: str = Field(description="Full entity_id to query")


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

class VoiceSpeak(BaseModel):
    action: Literal["speak"] = "speak"
    text: str = Field(description="Text to synthesize and speak aloud")
    language: str = Field(default="de", description="BCP-47 language code")


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------

class FilesystemReadFile(BaseModel):
    action: Literal["read_file"] = "read_file"
    path: str = Field(description="Absolute or relative path to the file")
    max_chars: int = Field(default=8000, description="Maximum characters to read")


class FilesystemWriteFile(BaseModel):
    action: Literal["write_file"] = "write_file"
    path: str = Field(description="Absolute or relative path to write")
    content: str = Field(description="Content to write")
    append: bool = Field(default=False, description="Append instead of overwrite")


class FilesystemListDirectory(BaseModel):
    action: Literal["list_directory"] = "list_directory"
    path: str = Field(description="Directory path to list")


class FilesystemSearchFiles(BaseModel):
    action: Literal["search_files"] = "search_files"
    root: str = Field(description="Root directory for the search")
    pattern: str = Field(description="Glob pattern, e.g. '*.py'")
    max_results: int = Field(default=20)


# ---------------------------------------------------------------------------
# Internet
# ---------------------------------------------------------------------------

class InternetWebSearch(BaseModel):
    action: Literal["web_search"] = "web_search"
    query: str = Field(description="Natural-language search query")
    max_results: int = Field(default=5)


class InternetFetchPage(BaseModel):
    action: Literal["fetch_page"] = "fetch_page"
    url: str = Field(description="URL to fetch and parse")
    max_chars: int = Field(default=8000)


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------

class VisionCaptureAndDescribe(BaseModel):
    action: Literal["capture_and_describe"] = "capture_and_describe"
    camera_index: int = Field(default=0)
