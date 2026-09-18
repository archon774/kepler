"""Fake provider SDKs and recorded-response helpers for ``tools.llm`` tests.

The fake Anthropic SDK mirrors the streaming shape already proven in
``tests/test_runner_session.py``: a context manager exposing ``.text_stream``
and ``.get_final_message()``. Nothing here opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"

#: Keys whose values the real SDKs hand back as plain dicts (tool arguments),
#: so :func:`as_namespace` leaves them alone instead of making them namespaces.
_LEAF_KEYS = {"input"}


def load_response_fixture(name: str) -> dict[str, Any]:
    """Load ``tests/fixtures/llm/responses/<name>`` as a dict."""

    return json.loads(
        (FIXTURES / "responses" / name).read_text(encoding="utf-8")
    )


def as_namespace(value: Any) -> Any:
    """Recursively turn dicts into attribute-accessible namespaces, the way an
    SDK response model reads. Tool-argument mappings are left as dicts."""

    if isinstance(value, dict):
        return SimpleNamespace(
            **{
                key: (sub if key in _LEAF_KEYS else as_namespace(sub))
                for key, sub in value.items()
            }
        )
    if isinstance(value, list):
        return [as_namespace(item) for item in value]
    return value


class FakeAnthropicStream:
    """One streamed message, shaped like the SDK's own event stream.

    The SDK fires the raw ``content_block_delta`` **and** a synthesized
    ``text`` or ``thinking`` event for the same chunk, so this fake fires both
    too: an adapter that counted each chunk twice would pass against a fake
    that emitted only one of them.
    """

    def __init__(
        self,
        final_message: Any,
        text_chunks: Iterable[str] = (),
        thinking_chunks: Iterable[str] = (),
    ) -> None:
        self._final = final_message
        events: list[Any] = []
        for chunk in thinking_chunks:
            events.append(
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="thinking_delta", thinking=chunk),
                )
            )
            events.append(SimpleNamespace(type="thinking", thinking=chunk))
        for chunk in text_chunks:
            events.append(
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text=chunk),
                )
            )
            events.append(SimpleNamespace(type="text", text=chunk))
        self._events = events
        self.text_stream = iter(list(text_chunks))

    def __iter__(self) -> Any:
        return iter(self._events)

    def __enter__(self) -> "FakeAnthropicStream":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get_final_message(self) -> Any:
        return self._final


class FakeAnthropicMessages:
    """Records every ``stream(**kwargs)`` call and returns queued streams."""

    def __init__(self, streams: Iterable[FakeAnthropicStream]) -> None:
        self._streams = iter(list(streams))
        self.requests: list[dict[str, Any]] = []
        self.api_key: str | None = None

    def stream(self, **kwargs: Any) -> FakeAnthropicStream:
        self.requests.append(kwargs)
        return next(self._streams)


class StubBackend:
    """A hand-written ``ModelBackend`` for engine and runner tests: no SDK, no
    network. ``complete()`` returns queued ``ModelResponse`` objects and
    forwards their text to ``on_text`` once, the way every non-Anthropic
    adapter does."""

    def __init__(
        self,
        responses: Iterable[Any],
        *,
        spec: str = "stub/model",
        max_output_tokens: int = 4096,
    ) -> None:
        from tools.llm.base import Capabilities

        self._responses = iter(list(responses))
        self.spec = spec
        self.capabilities = Capabilities(
            streaming=False,
            parallel_tool_calls=True,
            native_tool_call_ids=True,
            schema_dialect="json_schema",
            supports_union_types=True,
            max_output_tokens=max_output_tokens,
        )
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        messages: Any,
        tools: Any,
        system: str,
        max_tokens: int,
        temperature: float = 0.0,
        on_text: Any = None,
        on_thinking: Any = None,
    ) -> Any:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        response = next(self._responses)
        if on_thinking is not None:
            for block in getattr(response, "thinking", ()):
                if block.text:
                    on_thinking(block.text)
        if on_text is not None and response.text:
            on_text(response.text)
        return response


def fake_anthropic_module(messages: FakeAnthropicMessages) -> SimpleNamespace:
    """A stand-in ``anthropic`` module: ``anthropic.Anthropic(api_key=...)``
    hands back a client whose ``.messages`` is ``messages`` and records the key
    it was constructed with on ``messages.api_key``.

    The SDK's **real exception classes** are carried through. The adapter
    catches ``anthropic.BadRequestError`` to retry a model that refuses
    ``temperature``, and a fake module without the class makes that handler
    unreachable -- the stand-in has to be faithful enough for the code's own
    error handling to run against it.
    """

    import anthropic as real

    class _Client:
        def __init__(self, api_key: str) -> None:
            messages.api_key = api_key
            self.messages = messages

    return SimpleNamespace(
        Anthropic=_Client,
        BadRequestError=real.BadRequestError,
        APIStatusError=real.APIStatusError,
        APIError=real.APIError,
    )


class CapturingTransport:
    """An ``httpx`` mock transport that records every request and replies with a
    canned JSON body. Pass it to a ``BaseHTTPBackend`` subclass via the
    ``transport`` keyword -- production never sets it."""

    def __init__(self, body: Any = None, status_code: int = 200) -> None:
        import httpx

        self.requests: list[httpx.Request] = []
        self._body = {} if body is None else body
        self._status = status_code
        self._transport = httpx.MockTransport(self._handle)

    def _handle(self, request: "Any") -> "Any":
        import httpx

        self.requests.append(request)
        body = self._body(request) if callable(self._body) else self._body
        return httpx.Response(self._status, json=body)

    def __call__(self) -> Any:
        return self._transport

    @property
    def last(self) -> Any:
        return self.requests[-1]


def openai_chat_response(
    *,
    text: str | None = "Here is the answer.",
    tool_calls: Iterable[dict[str, Any]] = (),
    finish_reason: str = "stop",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A minimal OpenAI Chat Completions response body."""

    message: dict[str, Any] = {"role": "assistant", "content": text}
    calls = list(tool_calls)
    if calls:
        message["tool_calls"] = calls
    return {
        "id": "chatcmpl-recorded",
        "object": "chat.completion",
        "model": "gpt-4.1",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage
        or {"prompt_tokens": 120, "completion_tokens": 18, "total_tokens": 138},
    }


def failing_transport(exc: Exception | None = None) -> Any:
    """An ``httpx`` mock transport whose every request raises a connection
    error -- for testing a backend's unreachable-daemon handling."""

    import httpx

    error = exc or httpx.ConnectError("connection refused")

    def _raise(request: Any) -> Any:
        raise error

    return httpx.MockTransport(_raise)


def openai_tool_call(
    name: str, arguments: str, *, call_id: str = "call_recorded"
) -> dict[str, Any]:
    """One OpenAI tool_calls entry. ``arguments`` is a JSON *string*, as the
    wire format has it."""

    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }
