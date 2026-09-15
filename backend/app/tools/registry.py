"""Tool registry → JSON schemas handed to the LLM."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.tools.errors import ConstraintRefused, ToolNotFound


class ToolSpec(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., Any]
    is_write: bool = False

    model_config = {"arbitrary_types_allowed": True}


class ToolRegistry:
    """Maps tool names to handlers and emits Anthropic-style JSON schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolNotFound(name)
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def json_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for spec in self._tools.values():
            raw = spec.input_model.model_json_schema()
            schemas.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "is_write": spec.is_write,
                    "input_schema": raw,
                }
            )
        return schemas

    def call(self, name: str, arguments: dict[str, Any], *, db: Session) -> Any:
        spec = self.get(name)
        payload = spec.input_model.model_validate(arguments or {})
        try:
            result = spec.handler(payload, db=db)
            if spec.is_write:
                db.commit()
            return result
        except ConstraintRefused as refused:
            db.rollback()
            return refused.as_dict()
        except Exception:
            db.rollback()
            raise


registry = ToolRegistry()


def tool(name: str, description: str, input_model: type[BaseModel], *, is_write: bool = False):
    """Decorator: register a `(input_model, *, db) -> result` callable."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(
            ToolSpec(
                name=name,
                description=description,
                input_model=input_model,
                handler=fn,
                is_write=is_write,
            )
        )
        return fn

    return decorator
