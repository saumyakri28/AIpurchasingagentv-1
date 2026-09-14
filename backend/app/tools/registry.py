"""Tool registry → JSON schemas handed to the LLM.

Every tool is a Pydantic-schema'd callable. Implemented in Prompt 3.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | None = None
    is_write: bool = False

    model_config = {"arbitrary_types_allowed": True}


class ToolRegistry:
    """Maps tool names to handlers and emits OpenAI/Anthropic-style JSON schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def json_schemas(self) -> list[dict[str, Any]]:
        """JSON schema list for the LLM tool-calling API."""
        raise NotImplementedError

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError


registry = ToolRegistry()
