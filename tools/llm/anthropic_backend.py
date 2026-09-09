"""``AnthropicBackend`` -- the Anthropic Messages API adapter.

The only adapter that streams natively. Behaviour is specified by
``docs/working/model-backends.md`` sections 4.2-4.6 and the Phase 0b list. The
``anthropic`` import is function-local so ``import tools.llm`` stays cheap and
``tests/test_runner_session.py``'s ``sys.modules`` monkeypatch keeps working.
"""

from __future__ import annotations

import os
import time
from typing import Any, Mapping, Sequence

from tools.llm.base import (
    BackendUnavailableError,
    Capabilities,
    OnText,
    truncation_fault,
)
from tools.llm.types import (
    Message,
    ModelResponse,
    ProtocolFault,
    StopReason,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    Usage,
)

__all__ = ["AnthropicBackend", "ANTHROPIC_MAX_OUTPUT_TOKENS"]

#: What ``tools/runner.py`` passes today, kept so Phase 0c is a no-op change.
ANTHROPIC_MAX_OUTPUT_TOKENS = 128000

_DEFAULT_MODEL = "claude-sonnet-5"

_CAPABILITIES = Capabilities(
    streaming=True,
    parallel_tool_calls=True,
    native_tool_call_ids=True,
    schema_dialect="json_schema",
    supports_union_types=True,
    max_output_tokens=ANTHROPIC_MAX_OUTPUT_TOKENS,
)

#: Anthropic's own stop-reason strings mapped onto the neutral closed set.
#: ``end_turn`` and ``stop_sequence`` both mean "the model finished"; anything
#: not listed maps to ``other``. ``raw_stop_reason`` always keeps the original.
_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicBackend:
    """Adapter over ``anthropic.Anthropic`` with native streaming."""

    def __init__(
        self, *, model: str = _DEFAULT_MODEL, api_key: str | None = None
    ) -> None:
        resolved = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        if not resolved:
            raise BackendUnavailableError(
                "ANTHROPIC_API_KEY", "pass api_key=... or set the variable"
            )
        self._api_key = resolved
        self._model = model
        self.spec = f"anthropic/{model}"
        self.capabilities = _CAPABILITIES

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: object,
        system: str,
        max_tokens: int,
        temperature: float = 0.0,
        on_text: OnText | None = None,
    ) -> ModelResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        rendered = _render_messages(messages)

        start = time.monotonic()
        with client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=rendered,
            temperature=temperature,
        ) as stream:
            streamed: list[str] = []
            for chunk in stream.text_stream:
                streamed.append(chunk)
                if on_text is not None:
                    on_text(chunk)
            final = stream.get_final_message()
        latency_ms = (time.monotonic() - start) * 1000.0

        return _to_model_response(final, "".join(streamed), latency_ms)


# --- rendering -------------------------------------------------------------


def _render_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Neutral history -> Anthropic wire format (section 4.5).

    Assistant turns become content blocks. A ``ToolResultBlock`` becomes a
    ``user`` message carrying a ``tool_result`` block keyed by ``tool_use_id``.
    """

    rendered: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            rendered.append(
                {"role": "assistant", "content": _assistant_content(message.blocks)}
            )
            continue

        text_only = [b for b in message.blocks if isinstance(b, TextBlock)]
        if len(text_only) == len(message.blocks) == 1:
            # Parity with today's runner, which sends the opening user message
            # as a bare string.
            rendered.append({"role": "user", "content": text_only[0].text})
            continue

        rendered.append({"role": "user", "content": _user_content(message.blocks)})
    return rendered


def _assistant_content(blocks: Sequence[Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            if block.text:
                content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolCallBlock):
            content.append(
                {
                    "type": "tool_use",
                    "id": block.call_id,
                    "name": block.name,
                    "input": dict(block.arguments),
                }
            )
    return content


def _user_content(blocks: Sequence[Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            if block.text:
                content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolResultBlock):
            entry: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": block.call_id,
                "content": block.content,
            }
            if block.is_error:
                entry["is_error"] = True
            content.append(entry)
    return content


# --- response parsing ----------------------------------------------------


def _to_model_response(
    final: Any, streamed_text: str, latency_ms: float
) -> ModelResponse:
    raw_stop = getattr(final, "stop_reason", None)
    stop_reason: StopReason = _STOP_REASONS.get(raw_stop or "", "other")

    block_text: list[str] = []
    tool_calls: list[ToolCallBlock] = []
    for block in getattr(final, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            block_text.append(getattr(block, "text", "") or "")
        elif kind == "tool_use":
            tool_calls.append(
                ToolCallBlock(
                    call_id=getattr(block, "id", "") or "",
                    name=getattr(block, "name", "") or "",
                    arguments=_as_mapping(getattr(block, "input", None)),
                )
            )

    faults: list[ProtocolFault] = []
    if stop_reason == "tool_use" and not tool_calls:
        faults.append(
            ProtocolFault(
                type="empty_tool_call",
                detail="stop_reason was tool_use but the content held no tool_use block",
            )
        )
    truncated = truncation_fault(stop_reason, tool_calls)
    if truncated is not None:
        faults.append(truncated)

    return ModelResponse(
        stop_reason=stop_reason,
        text=streamed_text or "".join(block_text),
        tool_calls=tuple(tool_calls),
        usage=_read_usage(final),
        latency_ms=latency_ms,
        raw_stop_reason=raw_stop,
        faults=tuple(faults),
    )


def _as_mapping(value: Any) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _read_usage(final: Any) -> Usage | None:
    raw = getattr(final, "usage", None)
    if raw is None:
        return None

    def field(name: str) -> int | None:
        value = getattr(raw, name, None)
        if value is None and isinstance(raw, Mapping):
            value = raw.get(name)
        return value if isinstance(value, int) else None

    return Usage(
        input_tokens=field("input_tokens"),
        output_tokens=field("output_tokens"),
        cache_read_tokens=field("cache_read_input_tokens"),
        cache_write_tokens=field("cache_creation_input_tokens"),
        reasoning_tokens=None,
    )
