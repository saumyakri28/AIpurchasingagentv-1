"""Provider-agnostic LLM client: Anthropic + FakeLLM for tests/evals."""

from __future__ import annotations

import json
import time
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.config import get_settings


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class LLMResponse(BaseModel):
    message: LLMMessage
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Return a tool-call turn or a final assistant message (plus token usage)."""
        ...


def _anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for spec in tools or []:
        schema = spec.get("input_schema") or spec.get("parameters") or {"type": "object", "properties": {}}
        converted.append(
            {
                "name": spec["name"],
                "description": spec.get("description") or "",
                "input_schema": schema,
            }
        )
    return converted


def _split_system(messages: list[LLMMessage]) -> tuple[str, list[LLMMessage]]:
    system_parts = [m.content for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return "\n\n".join(system_parts), rest


def to_anthropic_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    """Convert our LLMMessage list (minus system) to Anthropic Messages API shape."""
    _, rest = _split_system(messages)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(rest):
        msg = rest[i]
        if msg.role == "tool":
            blocks: list[dict[str, Any]] = []
            while i < len(rest) and rest[i].role == "tool":
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": rest[i].tool_call_id or "",
                        "content": rest[i].content,
                    }
                )
                i += 1
            out.append({"role": "user", "content": blocks})
            continue
        if msg.role == "assistant":
            content: list[dict[str, Any]] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls or []:
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            out.append({"role": "assistant", "content": content or ""})
        else:
            out.append({"role": "user", "content": msg.content})
        i += 1
    return out


class AnthropicClient:
    """Anthropic Messages API with tool use, retries, token accounting."""

    def __init__(self, api_key: str, model: str, *, max_retries: int = 4, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.tokens_in = 0
        self.tokens_out = 0

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("anthropic package is not installed") from exc

        system, _ = _split_system(messages)
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system or "You are the AI Purchasing Agent.",
            "messages": to_anthropic_messages(messages),
        }
        converted = _anthropic_tools(tools)
        if converted:
            kwargs["tools"] = converted

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = client.messages.create(**kwargs)
                break
            except Exception as exc:  # retry rate limits and transients
                last_error = exc
                name = type(exc).__name__.lower()
                status = getattr(exc, "status_code", None)
                retryable = status in {429, 500, 502, 503, 529} or "rate" in name or "overload" in name
                if not retryable or attempt == self.max_retries - 1:
                    raise
                time.sleep(min(2**attempt, 16))
        else:  # pragma: no cover
            raise last_error or RuntimeError("Anthropic request failed")

        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        self.tokens_in += in_tok
        self.tokens_out += out_tok

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype == "tool_use":
                raw_input = getattr(block, "input", {}) or {}
                if isinstance(raw_input, str):
                    try:
                        raw_input = json.loads(raw_input)
                    except json.JSONDecodeError:
                        raw_input = {"_raw": raw_input}
                tool_calls.append(
                    ToolCall(
                        id=str(getattr(block, "id", "")),
                        name=str(getattr(block, "name", "")),
                        arguments=dict(raw_input),
                    )
                )

        content = "".join(text_parts)
        return LLMResponse(
            message=LLMMessage(role="assistant", content=content, tool_calls=tool_calls or None),
            tool_calls=tool_calls,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )


class FakeLLM:
    """Replays a scripted sequence of tool calls / messages from a fixture."""

    def __init__(self, script: list[LLMResponse | dict[str, Any]] | None = None) -> None:
        self.script = [self._coerce(item) for item in (script or [])]
        self.cursor = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.seen_messages: list[list[LLMMessage]] = []

    @staticmethod
    def _coerce(item: LLMResponse | dict[str, Any]) -> LLMResponse:
        if isinstance(item, LLMResponse):
            return item
        tool_calls = [
            ToolCall(
                id=str(tc.get("id") or f"fake-{i}"),
                name=str(tc["name"]),
                arguments=dict(tc.get("arguments") or tc.get("input") or {}),
            )
            for i, tc in enumerate(item.get("tool_calls") or [])
        ]
        content = item.get("content") or item.get("text") or ""
        if not content and item.get("decision"):
            content = json.dumps(item["decision"])
        return LLMResponse(
            message=LLMMessage(role="assistant", content=content, tool_calls=tool_calls or None),
            tool_calls=tool_calls,
            input_tokens=int(item.get("input_tokens") or 1),
            output_tokens=int(item.get("output_tokens") or 1),
        )

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        del tools
        self.seen_messages.append(list(messages))
        if self.cursor >= len(self.script):
            return LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content=json.dumps(
                        {
                            "decision": "escalate",
                            "final_quantity": None,
                            "confidence": 0.2,
                            "reasoning_summary": "FakeLLM script exhausted. Escalating.",
                            "key_factors": [],
                            "constraints_considered": [],
                            "alternatives_considered": [],
                            "expected_outcome": {},
                            "requires_human_approval": True,
                            "approval_reason": "script exhausted",
                        }
                    ),
                )
            )
        response = self.script[self.cursor]
        self.cursor += 1
        self.tokens_in += response.input_tokens
        self.tokens_out += response.output_tokens
        return response


def build_llm(*, script: list[Any] | None = None) -> LLMClient:
    settings = get_settings()
    if script is not None or settings.llm_provider == "fake":
        return FakeLLM(script or [])
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=real")
    return AnthropicClient(settings.anthropic_api_key, settings.llm_model)
