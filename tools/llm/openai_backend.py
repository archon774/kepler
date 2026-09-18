"""``OpenAIBackend`` -- OpenAI Chat Completions over raw ``httpx``, and any
OpenAI-compatible endpoint.

Sections 4.2-4.5 of ``docs/archive/model-backends.md``. Non-streaming: the
capability flag is off and ``on_text`` is called once with the finished text.
Tool-call arguments arrive as a JSON *string* and are parsed; a parse failure
is a ``malformed_arguments_json`` fault with the call dropped, never an
exception.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping, Sequence

from tools.llm.base import (
    BackendUnavailableError,
    BaseHTTPBackend,
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

__all__ = ["OpenAIBackend", "OPENAI_DEFAULT_BASE_URL", "OPENAI_MAX_OUTPUT_TOKENS"]

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENAI_MAX_OUTPUT_TOKENS = 16384

_CAPABILITIES = Capabilities(
    streaming=False,
    parallel_tool_calls=True,
    native_tool_call_ids=True,
    schema_dialect="openai_function",
    supports_union_types=True,
    max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
    thinking=True,
)

#: OpenAI's ``finish_reason`` strings mapped onto the neutral closed set.
_FINISH_REASONS: dict[str, StopReason] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}


class OpenAIBackend(BaseHTTPBackend):
    """Adapter over the Chat Completions endpoint."""

    _DEFAULT_BASE_URL = OPENAI_DEFAULT_BASE_URL
    _CHAT_PATH = "/chat/completions"

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: Any = None,
    ) -> None:
        resolved_base = (base_url or self._DEFAULT_BASE_URL).rstrip("/")
        on_default_host = resolved_base == self._DEFAULT_BASE_URL.rstrip("/")
        if not api_key and on_default_host:
            raise BackendUnavailableError(
                self._missing_key_variable(),
                "pass api_key=... or set the variable",
            )
        super().__init__(
            base_url=resolved_base, api_key=api_key, transport=transport
        )
        self._model = model
        self.spec = f"{self._provider()}/{model}"
        self.capabilities = _CAPABILITIES

    # Hooks the Ollama subclass overrides.
    def _provider(self) -> str:
        return "openai"

    def _missing_key_variable(self) -> str:
        return "OPENAI_API_KEY"

    def _auth_headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._api_key}"}

    def _token_limit_param(self) -> str:
        # api.openai.com deprecated `max_tokens` and rejects it outright for
        # the reasoning models, so send `max_completion_tokens` there. Every
        # OpenAI-*compatible* server (behind a non-default base URL, Ollama
        # included) is kept on `max_tokens`, which they all accept.
        if self._base_url == OPENAI_DEFAULT_BASE_URL.rstrip("/"):
            return "max_completion_tokens"
        return "max_tokens"

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
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": _render_messages(messages, system),
            self._token_limit_param(): max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = list(tools)

        start = time.monotonic()
        data = self._post_json(self._CHAT_PATH, payload)
        latency_ms = (time.monotonic() - start) * 1000.0

        response = _to_model_response(data, latency_ms)
        # Not streamed: this adapter posts once and reads the finished answer,
        # so both hooks fire at the end. A caller gets the same content in the
        # same order, one chunk later than a streaming provider would give it.
        if on_thinking is not None:
            for block in response.thinking:
                if block.text:
                    on_thinking(block.text)
        if on_text is not None and response.text:
            on_text(response.text)
        return response


# --- rendering (section 4.5) --------------------------------------


def _render_messages(
    messages: Sequence[Message], system: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        if message.role == "assistant":
            out.append(_assistant_message(message.blocks))
            continue

        for block in message.blocks:
            if isinstance(block, ToolResultBlock):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.call_id,
                        "content": block.content,
                    }
                )
        text = "".join(
            block.text for block in message.blocks if isinstance(block, TextBlock)
        )
        if text:
            out.append({"role": "user", "content": text})
    return out


def _assistant_message(blocks: Sequence[Any]) -> dict[str, Any]:
    text = "".join(b.text for b in blocks if isinstance(b, TextBlock))
    tool_calls = [b for b in blocks if isinstance(b, ToolCallBlock)]
    entry: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments)),
                },
            }
            for call in tool_calls
        ]
    return entry


# --- response parsing --------------------------------------------


def _to_model_response(data: Mapping[str, Any], latency_ms: float) -> ModelResponse:
    choices = data.get("choices") or [{}]
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    raw_finish = choice.get("finish_reason")
    stop_reason: StopReason = _FINISH_REASONS.get(raw_finish or "", "other")

    faults: list[ProtocolFault] = []
    tool_calls: list[ToolCallBlock] = []
    for entry in message.get("tool_calls") or []:
        function = entry.get("function") or {}
        name = function.get("name") or ""
        raw_args = function.get("arguments")
        parsed = _parse_arguments(raw_args)
        if parsed is None:
            faults.append(
                ProtocolFault(
                    type="malformed_arguments_json",
                    detail=f"arguments for {name!r} did not parse: {raw_args!r}",
                    tool_name=name,
                    call_id=entry.get("id"),
                )
            )
            continue
        tool_calls.append(
            ToolCallBlock(
                call_id=entry.get("id") or "", name=name, arguments=parsed
            )
        )

    # A quirky compatible server can return finish_reason "stop" alongside
    # tool_calls; treat any parsed call as a tool-use turn so the loop
    # dispatches it rather than silently dropping it.
    if tool_calls and stop_reason == "end_turn":
        stop_reason = "tool_use"

    if stop_reason == "tool_use" and not tool_calls:
        faults.append(
            ProtocolFault(
                type="empty_tool_call",
                detail="finish_reason was tool_calls but no call parsed",
            )
        )
    truncated = truncation_fault(stop_reason, tool_calls)
    if truncated is not None:
        faults.append(truncated)

    return ModelResponse(
        stop_reason=stop_reason,
        text=message.get("content") or "",
        thinking=_read_thinking(message),
        tool_calls=tuple(tool_calls),
        usage=_read_usage(data),
        latency_ms=latency_ms,
        raw_stop_reason=raw_finish,
        faults=tuple(faults),
    )


#: What an OpenAI-compatible server calls the field it reveals reasoning in.
#: There is no standard: Ollama and DeepSeek send ``reasoning_content``, and
#: several other servers send ``reasoning``. Both are read; neither is
#: required, and a server that reveals nothing is not a server whose model
#: did not reason.
_REASONING_FIELDS = ("reasoning_content", "reasoning")


def _read_thinking(message: Mapping[str, Any]) -> tuple[ThinkingBlock, ...]:
    """Read whatever reasoning this server chose to reveal.

    Unsigned: none of these servers attest their reasoning, and none requires
    it back. It is carried for the transcript, not for the next request.
    """

    for field in _REASONING_FIELDS:
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            return (ThinkingBlock(text=value),)
    return ()


def _parse_arguments(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _read_usage(data: Mapping[str, Any]) -> Usage | None:
    raw = data.get("usage")
    if not raw:
        return None
    prompt_details = raw.get("prompt_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or {}
    return Usage(
        input_tokens=raw.get("prompt_tokens"),
        output_tokens=raw.get("completion_tokens"),
        cache_read_tokens=prompt_details.get("cached_tokens"),
        cache_write_tokens=None,
        reasoning_tokens=completion_details.get("reasoning_tokens"),
    )
