"""OpenAIBackend: Chat Completions over raw httpx.

Phase 2a of docs/working/model-backends.md, sections 4.2-4.5. No network: every
request goes through an httpx MockTransport that the test inspects.
"""

from __future__ import annotations

import json

import pytest

from tests.llm_fakes import CapturingTransport, openai_chat_response, openai_tool_call
from tools.llm import BackendUnavailableError, Message, TextBlock, ToolCallBlock, ToolResultBlock
from tools.llm.openai_backend import OpenAIBackend


def _backend(body):
    capture = CapturingTransport(body)
    backend = OpenAIBackend(model="gpt-4.1", api_key="sk-test", transport=capture())
    return backend, capture


def test_capabilities_match_the_per_backend_table():
    caps = OpenAIBackend(model="gpt-4.1", api_key="sk-x").capabilities
    assert caps.streaming is False
    assert caps.parallel_tool_calls is True
    assert caps.native_tool_call_ids is True
    assert caps.schema_dialect == "openai_function"
    assert caps.supports_union_types is True
    assert caps.max_output_tokens == 16384


def test_missing_api_key_raises_backend_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BackendUnavailableError) as excinfo:
        OpenAIBackend(model="gpt-4.1")
    assert excinfo.value.variable == "OPENAI_API_KEY"


def test_a_plain_answer_round_trips_to_a_model_response():
    backend, capture = _backend(openai_chat_response(text="M31 is Andromeda."))
    seen: list[str] = []
    response = backend.complete(
        messages=(Message(role="user", blocks=(TextBlock("what is M31"),)),),
        tools=[],
        system="be helpful",
        max_tokens=200,
        on_text=seen.append,
    )
    assert response.text == "M31 is Andromeda."
    assert response.stop_reason == "end_turn"
    assert response.raw_stop_reason == "stop"
    assert seen == ["M31 is Andromeda."]
    assert response.usage.input_tokens == 120
    assert response.usage.output_tokens == 18
    assert response.latency_ms is not None

    body = json.loads(capture.last.content)
    assert body["messages"][0] == {"role": "system", "content": "be helpful"}
    assert body["messages"][1] == {"role": "user", "content": "what is M31"}
    assert str(capture.last.url).endswith("/chat/completions")


def test_tool_call_arguments_arrive_as_a_json_string_and_are_parsed():
    backend, _ = _backend(
        openai_chat_response(
            text=None,
            finish_reason="tool_calls",
            tool_calls=[openai_tool_call("search_ned", '{"name": "NGC 6334"}')],
        )
    )
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=50)
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert isinstance(call, ToolCallBlock)
    assert call.name == "search_ned"
    assert call.arguments == {"name": "NGC 6334"}
    assert call.call_id == "call_recorded"


def test_unparseable_tool_arguments_are_a_fault_and_the_call_is_dropped():
    backend, _ = _backend(
        openai_chat_response(
            text=None,
            finish_reason="tool_calls",
            tool_calls=[openai_tool_call("search_ned", '{"name": "NGC 63')],
        )
    )
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=50)
    assert response.tool_calls == ()
    assert [f.type for f in response.faults] == ["malformed_arguments_json", "empty_tool_call"]


def test_finish_reason_length_with_a_tool_call_records_truncated_output():
    backend, _ = _backend(
        openai_chat_response(
            text=None,
            finish_reason="length",
            tool_calls=[openai_tool_call("search_ned", '{"name": "M31"}')],
        )
    )
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=5)
    assert response.stop_reason == "max_tokens"
    assert "truncated_output" in [f.type for f in response.faults]


def test_a_stop_finish_reason_alongside_tool_calls_is_still_a_tool_use_turn():
    backend, _ = _backend(
        openai_chat_response(
            text=None,
            finish_reason="stop",  # a quirky compatible server
            tool_calls=[openai_tool_call("search_ned", '{"name": "M31"}')],
        )
    )
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=50)
    assert response.stop_reason == "tool_use"
    assert response.raw_stop_reason == "stop"
    assert len(response.tool_calls) == 1


def test_finish_reason_content_filter_maps_to_refusal():
    backend, _ = _backend(openai_chat_response(text="", finish_reason="content_filter"))
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=5)
    assert response.stop_reason == "refusal"
    assert response.raw_stop_reason == "content_filter"


def test_a_response_with_no_usage_block_yields_none():
    body = openai_chat_response()
    body.pop("usage")
    backend, _ = _backend(body)
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=5)
    assert response.usage is None


def test_message_rendering_matches_the_openai_dialect():
    backend, capture = _backend(openai_chat_response())
    history = (
        Message(role="user", blocks=(TextBlock("find M31"),)),
        Message(
            role="assistant",
            blocks=(
                TextBlock("looking"),
                ToolCallBlock(call_id="call_1", name="search_ned", arguments={"name": "M31"}),
            ),
        ),
        Message(
            role="user",
            blocks=(ToolResultBlock(call_id="call_1", name="search_ned", content='{"ok": 1}'),),
        ),
    )
    backend.complete(
        messages=history,
        tools=[{"type": "function", "function": {"name": "search_ned"}}],
        system="SYS",
        max_tokens=64,
    )
    body = json.loads(capture.last.content)
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assistant = body["messages"][2]
    assert assistant["content"] == "looking"
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert assistant["tool_calls"][0]["function"]["name"] == "search_ned"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"name": "M31"}
    tool_msg = body["messages"][3]
    assert tool_msg == {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": 1}'}
    assert body["tools"][0]["function"]["name"] == "search_ned"


def test_an_http_error_status_raises_rather_than_returning_a_bad_response():
    capture = CapturingTransport({"error": {"message": "bad request"}}, status_code=400)
    backend = OpenAIBackend(model="gpt-4.1", api_key="sk-x", transport=capture())
    with pytest.raises(Exception):
        backend.complete(messages=(), tools=[], system="s", max_tokens=5)
