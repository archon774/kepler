"""``AnthropicBackend`` -- the Anthropic Messages API adapter.

The only adapter that streams natively. Behaviour is specified by
``docs/archive/model-backends.md`` sections 4.2-4.6 and the Phase 0b list. The
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
    OnThinking,
    truncation_fault,
)
from tools.llm.types import (
    Message,
    ModelResponse,
    ProtocolFault,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    Usage,
)

__all__ = [
    "AnthropicBackend",
    "ANTHROPIC_MAX_OUTPUT_TOKENS",
    "ANTHROPIC_MIN_THINKING_BUDGET",
]

#: What the pre-engine loop passed, kept so its extraction was a no-op change.
ANTHROPIC_MAX_OUTPUT_TOKENS = 128000

_DEFAULT_MODEL = "claude-sonnet-5"

#: The provider's floor for ``budget_tokens``. A smaller budget is refused by
#: the API, so it is raised to this rather than sent and rejected.
ANTHROPIC_MIN_THINKING_BUDGET = 1024

_CAPABILITIES = Capabilities(
    streaming=True,
    parallel_tool_calls=True,
    native_tool_call_ids=True,
    schema_dialect="json_schema",
    supports_union_types=True,
    max_output_tokens=ANTHROPIC_MAX_OUTPUT_TOKENS,
    thinking=True,
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


#: Models observed to reject ``temperature``. Learned at runtime rather than
#: hard-coded: newer Anthropic models deprecate the parameter, and a literal
#: model list in this repository would be stale the week after it was written
#: -- the failure mode CLAUDE.md already carries scars from. Module-level so
#: one 400 teaches every later backend instance in the process.
_TEMPERATURE_REJECTED: set[str] = set()

#: The provider's own wording when it refuses the parameter.
_TEMPERATURE_REFUSALS = ("temperature` is deprecated", "temperature is deprecated",
                         "temperature` is not supported", "temperature is not supported")


class AnthropicBackend:
    """Adapter over ``anthropic.Anthropic`` with native streaming."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        thinking_budget: int | None = None,
    ) -> None:
        resolved = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        if not resolved:
            raise BackendUnavailableError(
                "ANTHROPIC_API_KEY", "pass api_key=... or set the variable"
            )
        self._api_key = resolved
        self._model = model
        self._thinking_budget = (
            None
            if thinking_budget is None
            else max(int(thinking_budget), ANTHROPIC_MIN_THINKING_BUDGET)
        )
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
        on_thinking: OnThinking | None = None,
    ) -> ModelResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        rendered = _render_messages(messages)
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "tools": tools,
            "messages": rendered,
        }
        budget = self._budget_for(max_tokens)
        if budget is not None and not _thinking_replayable(rendered):
            budget = None
        if budget is not None:
            request["thinking"] = {"type": "enabled", "budget_tokens": budget}
        elif self._model not in _TEMPERATURE_REJECTED:
            # Extended thinking and an explicit temperature are mutually
            # exclusive at the provider: thinking requires the default. The
            # caller asked for reasoning, so the caller gets the temperature
            # that comes with it -- and ``temperature_supported`` stops
            # claiming a determinism this run does not have.
            request["temperature"] = temperature

        start = time.monotonic()
        try:
            final, streamed = self._stream(client, request, on_text, on_thinking)
        except anthropic.BadRequestError as exc:
            if not _is_temperature_refusal(exc) or "temperature" not in request:
                raise
            # The model refuses the parameter. Drop it, remember, and retry --
            # rather than failing a whole benchmark task over a request field
            # the caller did not choose.
            _TEMPERATURE_REJECTED.add(self._model)
            request.pop("temperature")
            final, streamed = self._stream(client, request, on_text, on_thinking)
        latency_ms = (time.monotonic() - start) * 1000.0

        return _to_model_response(final, "".join(streamed), latency_ms)

    def _budget_for(self, max_tokens: int) -> int | None:
        """The thinking budget this call may actually ask for, if any.

        The provider requires ``max_tokens`` to exceed the budget, and the
        budget to clear its own floor. A caller with a small output ceiling
        therefore gets no reasoning rather than a rejected request: thinking
        is an improvement on the answer, never a precondition for one.
        """

        if self._thinking_budget is None:
            return None
        budget = min(self._thinking_budget, max_tokens - 1)
        return budget if budget >= ANTHROPIC_MIN_THINKING_BUDGET else None

    @property
    def temperature_supported(self) -> bool:
        """Whether this model accepted ``temperature`` on its last call.

        A benchmark claims determinism from temperature 0 (benchmark.md 5.6).
        When the provider refuses the parameter that claim does not hold, and
        a run record that did not say so would overstate its own
        reproducibility.
        """

        return self._thinking_budget is None and self._model not in _TEMPERATURE_REJECTED

    def _stream(
        self,
        client: Any,
        request: dict[str, Any],
        on_text: OnText | None,
        on_thinking: OnThinking | None = None,
    ) -> tuple[Any, list[str]]:
        """Drive one streamed turn, separating reasoning from answer.

        Iterates the SDK's own event stream rather than ``text_stream``, which
        yields answer text only: reasoning arrives as its own event type and
        is invisible from there. Unknown event types are ignored, so an SDK
        that grows a new one does not break a turn.
        """

        streamed: list[str] = []
        with client.messages.stream(**request) as stream:
            for event in stream:
                kind = getattr(event, "type", None)
                if kind == "text":
                    chunk = getattr(event, "text", "") or ""
                    if chunk:
                        streamed.append(chunk)
                        if on_text is not None:
                            on_text(chunk)
                elif kind == "thinking":
                    chunk = getattr(event, "thinking", "") or ""
                    if chunk and on_thinking is not None:
                        on_thinking(chunk)
            return stream.get_final_message(), streamed


# --- rendering -------------------------------------------------------------


def _render_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Neutral history -> Anthropic wire format (section 4.5).

    Assistant turns become content blocks. A ``ToolResultBlock`` becomes a
    ``user`` message carrying a ``tool_result`` block keyed by ``tool_use_id``.

    **Reasoning is replayed for the last assistant turn only.** When thinking
    is enabled the provider requires the thinking blocks of the turn whose
    tool calls are being answered, signature intact, or it refuses the
    request; it discards them from every earlier turn regardless. Sending
    them anyway would put the whole reasoning history of a long session back
    on the wire each turn, to be thrown away at the other end.
    """

    last_assistant = max(
        (index for index, message in enumerate(messages) if message.role == "assistant"),
        default=-1,
    )
    rendered: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.role == "assistant":
            rendered.append(
                {
                    "role": "assistant",
                    "content": _assistant_content(
                        message.blocks, with_thinking=index == last_assistant
                    ),
                }
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


def _thinking_replayable(rendered: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the turn being continued still carries the reasoning it signed.

    With thinking enabled the provider requires the last assistant turn's
    thinking blocks back, signature intact, before the tool results that
    answer it. A session resumed from a manifest that lost them -- or one that
    began with thinking switched off and has it switched on mid-flight --
    cannot produce them, and asking for reasoning on that request fails the
    whole turn. So reasoning is dropped for that one request instead: a turn
    with no visible reasoning is a smaller loss than a turn that errors.
    """

    for entry in reversed(list(rendered)):
        if entry.get("role") != "assistant":
            continue
        content = entry.get("content")
        if not isinstance(content, list):
            return True
        blocks = [block for block in content if isinstance(block, Mapping)]
        if not any(block.get("type") == "tool_use" for block in blocks):
            return True
        return any(
            block.get("type") in {"thinking", "redacted_thinking"} for block in blocks
        )
    return True


def _assistant_content(
    blocks: Sequence[Any], *, with_thinking: bool = False
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    if with_thinking:
        # Thinking leads the turn: the provider requires it before any text or
        # tool_use block. A block with no signature is dropped rather than
        # sent -- an unsigned thinking block is refused, and a refused request
        # costs the whole turn to say what dropping it says for nothing.
        for block in blocks:
            if not isinstance(block, ThinkingBlock) or not block.signature:
                continue
            if block.text:
                content.append(
                    {
                        "type": "thinking",
                        "thinking": block.text,
                        "signature": block.signature,
                    }
                )
            else:
                content.append(
                    {"type": "redacted_thinking", "data": block.signature}
                )
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
    thinking: list[ThinkingBlock] = []
    tool_calls: list[ToolCallBlock] = []
    for block in getattr(final, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            block_text.append(getattr(block, "text", "") or "")
        elif kind == "thinking":
            # Read from the final message rather than accumulated from the
            # deltas: only this copy carries the signature, and a thinking
            # block replayed without its signature is refused.
            thinking.append(
                ThinkingBlock(
                    text=getattr(block, "thinking", "") or "",
                    signature=getattr(block, "signature", "") or "",
                )
            )
        elif kind == "redacted_thinking":
            # Encrypted by the provider and unreadable here, but it still has
            # to survive the round trip, so it is carried as an empty-text
            # block whose signature is the payload.
            thinking.append(
                ThinkingBlock(text="", signature=getattr(block, "data", "") or "")
            )
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
        thinking=tuple(thinking),
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


def _is_temperature_refusal(exc: Exception) -> bool:
    """Whether a 400 is the provider refusing ``temperature``."""

    message = str(exc)
    return any(phrase in message for phrase in _TEMPERATURE_REFUSALS)
