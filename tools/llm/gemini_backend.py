"""``GeminiBackend`` -- Google Gemini ``generateContent`` over raw ``httpx``.

The hardest adapter (section 4.4): the OpenAPI-subset schema dialect, a
``model``/``user`` message shape with ``functionCall``/``functionResponse``
parts, and **no tool-call identifiers at all** -- the adapter synthesizes
``call_0``, ``call_1``, ... in the order the ``functionCall`` parts appear and
maps results back by position. It asserts exactly one ``functionResponse`` per
``functionCall`` and raises on a mismatch: a silent misalignment would
misattribute a tool result to the wrong call and corrupt a trajectory grade.

The API key travels in the ``x-goog-api-key`` header, never the ``?key=``
query parameter (S4).
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

__all__ = ["GeminiBackend", "GEMINI_DEFAULT_BASE_URL", "GEMINI_MAX_OUTPUT_TOKENS"]

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MAX_OUTPUT_TOKENS = 8192

_CAPABILITIES = Capabilities(
    streaming=False,
    parallel_tool_calls=True,
    native_tool_call_ids=False,
    schema_dialect="gemini_openapi",
    supports_union_types=False,
    max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
)

#: Gemini ``finishReason`` -> the neutral closed set. ``STOP`` with
#: ``functionCall`` parts is re-read as ``tool_use`` below.
_FINISH_REASONS: dict[str, StopReason] = {
    "STOP": "end_turn",
    "MAX_TOKENS": "max_tokens",
    "SAFETY": "refusal",
    "RECITATION": "refusal",
    "BLOCKLIST": "refusal",
    "PROHIBITED_CONTENT": "refusal",
    "SPII": "refusal",
}


class GeminiBackend(BaseHTTPBackend):
    """Adapter over ``models/{model}:generateContent``."""

    _DEFAULT_BASE_URL = GEMINI_DEFAULT_BASE_URL

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Any = None,
    ) -> None:
        resolved_base = (base_url or self._DEFAULT_BASE_URL).rstrip("/")
        on_default_host = resolved_base == self._DEFAULT_BASE_URL.rstrip("/")
        if api_key is not None:
            resolved_key: str | None = api_key
        elif on_default_host:
            resolved_key = os.environ.get("GEMINI_API_KEY")
        else:
            # S3: a custom endpoint must be explicitly paired with its key;
            # never read GEMINI_API_KEY for it.
            resolved_key = None
        if not resolved_key and on_default_host:
            raise BackendUnavailableError(
                "GEMINI_API_KEY", "pass api_key=... or set the variable"
            )
        super().__init__(
            base_url=resolved_base,
            api_key=resolved_key,
            transport=transport,
        )
        self._model = model
        self.spec = f"gemini/{model}"
        self.capabilities = _CAPABILITIES

    def _auth_headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key}

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
        body: dict[str, Any] = {
            "contents": _render_contents(messages),
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if tools:
            body["tools"] = list(tools)

        start = time.monotonic()
        data = self._post_json(
            f"/models/{self._model}:generateContent", body
        )
        latency_ms = (time.monotonic() - start) * 1000.0

        response = _to_model_response(data, latency_ms)
        if on_text is not None and response.text:
            on_text(response.text)
        return response


# --- rendering (section 4.5) --------------------------------------


def _render_contents(messages: Sequence[Message]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    pending_calls = 0

    for message in messages:
        if message.role == "assistant":
            parts: list[dict[str, Any]] = []
            calls = 0
            for block in message.blocks:
                if isinstance(block, TextBlock) and block.text:
                    parts.append({"text": block.text})
                elif isinstance(block, ToolCallBlock):
                    parts.append(
                        {
                            "functionCall": {
                                "name": block.name,
                                "args": dict(block.arguments),
                            }
                        }
                    )
                    calls += 1
            contents.append({"role": "model", "parts": parts})
            pending_calls = calls
            continue

        results = [b for b in message.blocks if isinstance(b, ToolResultBlock)]
        texts = [b for b in message.blocks if isinstance(b, TextBlock)]

        if results:
            if len(results) != pending_calls:
                raise ValueError(
                    f"call_id_mismatch: {len(results)} functionResponse part(s) "
                    f"for {pending_calls} functionCall part(s). Gemini matches "
                    "results to calls by position; a mismatch would misattribute "
                    "a tool result to the wrong call."
                )
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": result.name,
                                "response": _response_object(result.content),
                            }
                        }
                        for result in results
                    ],
                }
            )
        if texts:
            contents.append(
                {
                    "role": "user",
                    "parts": [{"text": "".join(t.text for t in texts)}],
                }
            )
        pending_calls = 0

    return contents


def _response_object(content: str) -> dict[str, Any]:
    """Gemini's ``functionResponse.response`` must be an object."""

    try:
        value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        value = content
    return value if isinstance(value, dict) else {"result": value}


# --- response parsing --------------------------------------------


def _to_model_response(data: Mapping[str, Any], latency_ms: float) -> ModelResponse:
    candidates = data.get("candidates") or [{}]
    candidate = candidates[0] if candidates else {}
    content = candidate.get("content") or {}
    raw_finish = candidate.get("finishReason")

    text_parts: list[str] = []
    tool_calls: list[ToolCallBlock] = []
    for part in content.get("parts") or []:
        if "text" in part:
            text_parts.append(part.get("text") or "")
        elif "functionCall" in part:
            fc = part["functionCall"] or {}
            args = fc.get("args")
            tool_calls.append(
                ToolCallBlock(
                    call_id=f"call_{len(tool_calls)}",
                    name=fc.get("name") or "",
                    arguments=args if isinstance(args, Mapping) else {},
                )
            )

    stop_reason: StopReason = _FINISH_REASONS.get(raw_finish or "", "other")
    if tool_calls and stop_reason == "end_turn":
        stop_reason = "tool_use"

    faults: list[ProtocolFault] = []
    if raw_finish == "MALFORMED_FUNCTION_CALL":
        faults.append(
            ProtocolFault(
                type="empty_tool_call",
                detail="Gemini reported MALFORMED_FUNCTION_CALL",
            )
        )
    elif stop_reason == "tool_use" and not tool_calls:
        faults.append(
            ProtocolFault(
                type="empty_tool_call",
                detail="a tool-use turn yielded no parsable functionCall part",
            )
        )
    truncated = truncation_fault(stop_reason, tool_calls)
    if truncated is not None:
        faults.append(truncated)

    return ModelResponse(
        stop_reason=stop_reason,
        text="".join(text_parts),
        tool_calls=tuple(tool_calls),
        usage=_read_usage(data),
        latency_ms=latency_ms,
        raw_stop_reason=raw_finish,
        faults=tuple(faults),
    )


def _read_usage(data: Mapping[str, Any]) -> Usage | None:
    raw = data.get("usageMetadata")
    if not raw:
        return None
    return Usage(
        input_tokens=raw.get("promptTokenCount"),
        output_tokens=raw.get("candidatesTokenCount"),
        cache_read_tokens=raw.get("cachedContentTokenCount"),
        cache_write_tokens=None,
        reasoning_tokens=raw.get("thoughtsTokenCount"),
    )
