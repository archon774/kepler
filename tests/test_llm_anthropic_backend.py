"""AnthropicBackend: the Anthropic Messages API adapter.

Phase 0b of docs/working/model-backends.md. The behaviour requirements are
sections 4.2-4.6 plus the Phase 0b list; the implementer chooses how.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.llm_fakes import (
    FakeAnthropicMessages,
    FakeAnthropicStream,
    as_namespace,
    fake_anthropic_module,
    load_response_fixture,
)
from tools.llm import BackendUnavailableError, Message, TextBlock, ToolCallBlock, ToolResultBlock
from tools.llm import anthropic_backend as ab


def _install(monkeypatch, streams) -> FakeAnthropicMessages:
    messages = FakeAnthropicMessages(streams)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module(messages))
    return messages


def _tool_use_message():
    return as_namespace(load_response_fixture("anthropic_tool_use.json"))


def _end_turn_message(**overrides):
    payload = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}]}
    payload.update(overrides)
    return as_namespace(payload)


# --- construction -----------------------------------------------------------


def test_missing_api_key_raises_backend_unavailable_naming_the_variable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BackendUnavailableError) as excinfo:
        ab.AnthropicBackend()
    assert excinfo.value.variable == "ANTHROPIC_API_KEY"


def test_explicit_key_bypasses_the_environment(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = ab.AnthropicBackend(api_key="explicit-key")
    assert backend.spec == "anthropic/claude-sonnet-5"


def test_env_key_is_used_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    messages = _install(monkeypatch, [FakeAnthropicStream(_end_turn_message(), ["Done."])])
    backend = ab.AnthropicBackend()
    backend.complete(messages=(), tools=[], system="s", max_tokens=1000)
    assert messages.api_key == "env-key"


def test_construction_does_not_import_the_anthropic_sdk():
    code = (
        "import sys; from tools.llm.anthropic_backend import AnthropicBackend; "
        "AnthropicBackend(api_key='k'); "
        "assert 'anthropic' not in sys.modules, 'anthropic imported too early'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_capabilities_match_the_per_backend_table(monkeypatch):
    backend = ab.AnthropicBackend(api_key="k")
    caps = backend.capabilities
    assert caps.streaming is True
    assert caps.parallel_tool_calls is True
    assert caps.native_tool_call_ids is True
    assert caps.schema_dialect == "json_schema"
    assert caps.supports_union_types is True
    assert caps.max_output_tokens == 128000


# --- complete() ------------------------------------------------------------


def test_complete_streams_text_to_the_callback_and_returns_tool_calls(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _install(
        monkeypatch,
        [FakeAnthropicStream(_tool_use_message(), ["I'll resolve ", "M31 first."])],
    )
    seen: list[str] = []
    backend = ab.AnthropicBackend()
    response = backend.complete(
        messages=(Message(role="user", blocks=(TextBlock("Find M31"),)),),
        tools=[],
        system="sys",
        max_tokens=2000,
        on_text=seen.append,
    )
    assert seen == ["I'll resolve ", "M31 first."]
    assert response.text == "I'll resolve M31 first."
    assert response.stop_reason == "tool_use"
    assert response.raw_stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert isinstance(call, ToolCallBlock)
    assert call.name == "search_simbad"
    assert call.call_id == "toolu_01Aq9wRecordedToolUseId"
    assert call.arguments == {"target": "M31"}
    assert response.latency_ms is not None and response.latency_ms >= 0.0


def test_complete_works_without_an_on_text_callback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _install(monkeypatch, [FakeAnthropicStream(_end_turn_message(), ["Hello."])])
    backend = ab.AnthropicBackend()
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=10)
    assert response.text == "Hello."
    assert response.stop_reason == "end_turn"


def test_usage_is_read_from_the_final_message(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _install(monkeypatch, [FakeAnthropicStream(_tool_use_message(), ["x"])])
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert response.usage is not None
    assert response.usage.input_tokens == 1843
    assert response.usage.output_tokens == 92
    assert response.usage.cache_read_tokens == 12032
    assert response.usage.cache_write_tokens == 0
    assert response.usage.reasoning_tokens is None


def test_a_final_message_with_no_usage_attribute_yields_none_not_a_crash(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    bare = _end_turn_message()
    assert not hasattr(bare, "usage")
    _install(monkeypatch, [FakeAnthropicStream(bare, ["hi"])])
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert response.usage is None


# --- stop-reason normalization -------------------------------------------


def test_stop_sequence_normalizes_to_end_turn_but_keeps_the_raw_value(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _install(
        monkeypatch,
        [FakeAnthropicStream(_end_turn_message(stop_reason="stop_sequence"), ["x"])],
    )
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert response.stop_reason == "end_turn"
    assert response.raw_stop_reason == "stop_sequence"


def test_an_unrecognized_stop_reason_maps_to_other(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _install(
        monkeypatch,
        [FakeAnthropicStream(_end_turn_message(stop_reason="pause_turn"), ["x"])],
    )
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert response.stop_reason == "other"
    assert response.raw_stop_reason == "pause_turn"


# --- protocol faults ----------------------------------------------------


def test_tool_use_stop_with_no_tool_block_records_an_empty_tool_call_fault(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    payload = {"stop_reason": "tool_use", "content": [{"type": "text", "text": "hm"}]}
    _install(monkeypatch, [FakeAnthropicStream(as_namespace(payload), ["hm"])])
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert response.tool_calls == ()
    assert [f.type for f in response.faults] == ["empty_tool_call"]


def test_max_tokens_with_a_tool_call_records_truncated_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    payload = {
        "stop_reason": "max_tokens",
        "content": [
            {"type": "tool_use", "id": "toolu_x", "name": "search_ned", "input": {"target": "NGC 1"}}
        ],
    }
    _install(monkeypatch, [FakeAnthropicStream(as_namespace(payload), [])])
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert "truncated_output" in [f.type for f in response.faults]


def test_max_tokens_with_no_tool_call_is_plain_truncated_prose_no_fault(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    payload = {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "a long..."}]}
    _install(monkeypatch, [FakeAnthropicStream(as_namespace(payload), ["a long..."])])
    response = ab.AnthropicBackend().complete(
        messages=(), tools=[], system="s", max_tokens=10
    )
    assert response.faults == ()


# --- message rendering (section 4.5) ----------------------------------


def test_neutral_history_renders_to_anthropic_wire_format(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    messages_recorder = _install(
        monkeypatch, [FakeAnthropicStream(_end_turn_message(), ["ok"])]
    )
    history = (
        Message(role="user", blocks=(TextBlock("Find M31"),)),
        Message(
            role="assistant",
            blocks=(
                TextBlock("Looking it up."),
                ToolCallBlock(call_id="toolu_1", name="search_simbad", arguments={"target": "M31"}),
            ),
        ),
        Message(
            role="user",
            blocks=(
                ToolResultBlock(call_id="toolu_1", name="search_simbad", content='{"ok": true}'),
            ),
        ),
    )
    ab.AnthropicBackend().complete(
        messages=history, tools=[{"name": "search_simbad"}], system="SYS", max_tokens=5
    )
    request = messages_recorder.requests[0]
    assert request["system"] == "SYS"
    assert request["max_tokens"] == 5
    rendered = request["messages"]
    assert rendered[0] == {"role": "user", "content": "Find M31"}
    assert rendered[1]["role"] == "assistant"
    assert {"type": "text", "text": "Looking it up."} in rendered[1]["content"]
    assert {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "search_simbad",
        "input": {"target": "M31"},
    } in rendered[1]["content"]
    assert rendered[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"ok": true}'}
        ],
    }


def test_an_error_tool_result_sets_is_error_true(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    recorder = _install(monkeypatch, [FakeAnthropicStream(_end_turn_message(), ["ok"])])
    history = (
        Message(
            role="user",
            blocks=(
                ToolResultBlock(
                    call_id="c1", name="search_ned", content="boom", is_error=True
                ),
            ),
        ),
    )
    ab.AnthropicBackend().complete(messages=history, tools=[], system="s", max_tokens=5)
    entry = recorder.requests[0]["messages"][0]["content"][0]
    assert entry["is_error"] is True


# --- a model that refuses `temperature` -----------------------------------


@pytest.fixture(autouse=True)
def _forget_temperature_refusals():
    """The refusal set is module-level so one 400 teaches every later backend
    in the process. That is right in production and cross-test pollution in a
    suite, so each test starts from a clean slate."""

    from tools.llm import anthropic_backend as module

    module._TEMPERATURE_REJECTED.clear()
    yield
    module._TEMPERATURE_REJECTED.clear()


class _RefusingMessages(FakeAnthropicMessages):
    """Raises the provider's temperature refusal until the parameter is gone."""

    def __init__(self, streams, *, error):
        super().__init__(streams)
        self._error = error

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        if "temperature" in kwargs:
            raise self._error
        return next(self._streams)


def _bad_request(message):
    import anthropic
    import httpx

    return anthropic.BadRequestError(
        message,
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        body=None,
    )


def test_a_model_that_deprecates_temperature_is_retried_without_it(monkeypatch):
    """claude-sonnet-5 answers `temperature` with a 400. Failing a whole
    benchmark task over a request field the caller never chose would be the
    port's fault, not the model's."""

    final = as_namespace(load_response_fixture("anthropic_tool_use.json"))
    messages = _RefusingMessages(
        [FakeAnthropicStream(final, ["hello"])],
        error=_bad_request("`temperature` is deprecated for this model."),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module(messages))

    backend = ab.AnthropicBackend(model="claude-sonnet-5", api_key="k")
    response = backend.complete(
        messages=(), tools=[], system="s", max_tokens=32, temperature=0.0
    )
    assert response.stop_reason in ("end_turn", "tool_use")
    # First attempt carried it, the retry did not.
    assert "temperature" in messages.requests[0]
    assert "temperature" not in messages.requests[1]


def test_the_refusal_is_remembered_so_the_next_call_does_not_pay_for_it(monkeypatch):
    final = as_namespace(load_response_fixture("anthropic_tool_use.json"))
    messages = _RefusingMessages(
        [FakeAnthropicStream(final, ["a"]), FakeAnthropicStream(final, ["b"])],
        error=_bad_request("`temperature` is deprecated for this model."),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module(messages))

    backend = ab.AnthropicBackend(model="claude-sonnet-5", api_key="k")
    backend.complete(messages=(), tools=[], system="s", max_tokens=32)
    backend.complete(messages=(), tools=[], system="s", max_tokens=32)
    # Three requests, not four: the second call never sent temperature.
    assert len(messages.requests) == 3
    assert "temperature" not in messages.requests[2]


def test_temperature_supported_is_reported_and_reaches_the_manifest(monkeypatch):
    """A benchmark claims determinism from temperature 0. Where the provider
    refuses the parameter that claim does not hold, and a run record that
    stayed silent would overstate its own reproducibility."""

    from tools.sessions import backend_record

    final = as_namespace(load_response_fixture("anthropic_tool_use.json"))
    messages = _RefusingMessages(
        [FakeAnthropicStream(final, ["hello"])],
        error=_bad_request("`temperature` is deprecated for this model."),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module(messages))

    backend = ab.AnthropicBackend(model="claude-sonnet-5", api_key="k")
    assert backend.temperature_supported is True  # nothing observed yet
    backend.complete(messages=(), tools=[], system="s", max_tokens=32)
    assert backend.temperature_supported is False
    assert backend_record(backend)["temperature_supported"] is False


def test_a_different_bad_request_is_not_swallowed(monkeypatch):
    """Only the temperature refusal is retried. Anything else is a real error
    and must surface, not be masked by a silent second attempt."""

    final = as_namespace(load_response_fixture("anthropic_tool_use.json"))
    messages = _RefusingMessages(
        [FakeAnthropicStream(final, ["hello"])],
        error=_bad_request("max_tokens must be a positive integer"),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module(messages))

    import anthropic

    backend = ab.AnthropicBackend(model="claude-sonnet-5", api_key="k")
    with pytest.raises(anthropic.BadRequestError):
        backend.complete(messages=(), tools=[], system="s", max_tokens=32)


def test_a_backend_that_does_not_report_temperature_support_omits_the_key():
    """Never assumed true: the key is absent rather than optimistic."""

    from tests.llm_fakes import StubBackend
    from tools.sessions import backend_record

    assert "temperature_supported" not in backend_record(StubBackend([]))
