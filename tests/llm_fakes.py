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
    """One streamed message: yields ``text_chunks`` then a final message."""

    def __init__(self, final_message: Any, text_chunks: Iterable[str] = ()) -> None:
        self._final = final_message
        self.text_stream = iter(list(text_chunks))

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
        if on_text is not None and response.text:
            on_text(response.text)
        return response


def fake_anthropic_module(messages: FakeAnthropicMessages) -> SimpleNamespace:
    """A stand-in ``anthropic`` module: ``anthropic.Anthropic(api_key=...)``
    hands back a client whose ``.messages`` is ``messages`` and records the key
    it was constructed with on ``messages.api_key``."""

    class _Client:
        def __init__(self, api_key: str) -> None:
            messages.api_key = api_key
            self.messages = messages

    return SimpleNamespace(Anthropic=_Client)
