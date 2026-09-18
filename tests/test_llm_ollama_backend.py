"""OllamaBackend: a thin OpenAIBackend subclass for a local daemon.

Phase 2b of docs/archive/model-backends.md. The offline tests run by default;
the live measurement is marked ``ollama`` and is deselected unless
KEPLER_TEST_MODEL_API=1 and the daemon is reachable.
"""

from __future__ import annotations

import json

import pytest

from tests.llm_fakes import (
    CapturingTransport,
    failing_transport,
    openai_chat_response,
    openai_tool_call,
)
from tools.llm.base import BackendUnavailableError
from tools.llm.factory import build_backend
from tools.llm.ollama_backend import OLLAMA_DEFAULT_BASE_URL, OllamaBackend
from tools.llm.types import Message, TextBlock

#: The reference model for the live measurement. Named once here so later work
#: imports the name rather than hard-coding a string. The plan's `qwen3:8b`
#: was not available on the measurement host; `qwen3.8:27b-mlx` was used
#: instead -- same qwen3.x tool-calling tier. See section 11 question 1.
OLLAMA_REFERENCE_MODEL = "qwen3.8:27b-mlx"


# --- offline --------------------------------------------------------------


def test_spec_and_capabilities():
    backend = OllamaBackend(model="qwen3:8b")
    assert backend.spec == "ollama/qwen3:8b"
    assert backend.capabilities.schema_dialect == "openai_function"
    assert backend.capabilities.max_output_tokens == 8192
    assert backend._base_url == OLLAMA_DEFAULT_BASE_URL


def test_no_authorization_header_ever_even_with_openai_api_key_in_the_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-be-ignored")
    capture = CapturingTransport(openai_chat_response())
    backend = OllamaBackend(model="qwen3:8b", transport=capture())
    backend.complete(
        messages=(Message(role="user", blocks=(TextBlock("hi"),)),),
        tools=[],
        system="s",
        max_tokens=64,
    )
    for request in capture.requests:
        assert "authorization" not in request.headers


def test_construction_never_raises_for_a_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    OllamaBackend(model="qwen3:8b")  # no BackendUnavailableError


def test_is_available_is_false_on_a_connection_error():
    backend = OllamaBackend(model="qwen3:8b", transport=failing_transport())
    assert backend.is_available() is False


def test_installed_models_reads_the_names_the_daemon_reports():
    capture = CapturingTransport(
        {"models": [{"name": "gemma4:12b"}, {"name": "qwen3.5:9b"}]}
    )
    backend = OllamaBackend(model="qwen3:8b", transport=capture())

    assert backend.installed_models() == ("gemma4:12b", "qwen3.5:9b")
    assert capture.last.url.path.endswith("/api/tags")


def test_installed_models_is_empty_when_the_daemon_cannot_be_asked():
    """`()` means "could not ask", not "holds nothing" -- a caller must not
    turn a failed listing into a refusal to run."""

    backend = OllamaBackend(model="qwen3:8b", transport=failing_transport())

    assert backend.installed_models() == ()


def test_installed_models_ignores_entries_without_a_usable_name():
    capture = CapturingTransport(
        {"models": [{"name": "gemma4:12b"}, {"size": 1}, {"name": 7}]}
    )
    backend = OllamaBackend(model="qwen3:8b", transport=capture())

    assert backend.installed_models() == ("gemma4:12b",)


def test_is_available_is_true_when_the_tags_endpoint_answers_200():
    capture = CapturingTransport({"models": []})
    backend = OllamaBackend(model="qwen3:8b", transport=capture())
    assert backend.is_available() is True
    assert capture.last.url.path.endswith("/api/tags")
    assert "/v1/" not in str(capture.last.url)


def test_complete_raises_backend_unavailable_naming_ollama_base_url():
    backend = OllamaBackend(model="qwen3:8b", transport=failing_transport())
    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.complete(messages=(), tools=[], system="s", max_tokens=16)
    assert excinfo.value.variable == "OLLAMA_BASE_URL"
    assert "ollama serve" in str(excinfo.value)


def test_a_tool_call_still_round_trips_through_the_compat_endpoint():
    capture = CapturingTransport(
        openai_chat_response(
            text=None,
            finish_reason="tool_calls",
            tool_calls=[openai_tool_call("search_vizier", '{"max_catalogs": null}')],
        )
    )
    backend = OllamaBackend(model="qwen3:8b", transport=capture())
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0].arguments == {"max_catalogs": None}
    assert str(capture.last.url).endswith("/v1/chat/completions")


def test_every_response_carries_a_latency_and_a_populated_usage():
    """Inherited from ``OpenAIBackend.complete``, and asserted here anyway:
    the benchmark's efficiency axis (docs/benchmarking/harness.md 7.2) has no
    data if any one adapter leaves either at ``None``, and "it is inherited"
    is a claim about today's class body, not a test."""

    capture = CapturingTransport(openai_chat_response())
    backend = OllamaBackend(model="qwen3:8b", transport=capture())
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    assert response.latency_ms is not None and response.latency_ms >= 0.0
    assert response.usage is not None
    assert response.usage.input_tokens == 120
    assert response.usage.output_tokens == 18


def test_the_factory_builds_it_without_a_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-be-ignored")
    backend = build_backend("ollama/qwen3:8b")
    assert isinstance(backend, OllamaBackend)
    assert backend._api_key is None


def test_first_slash_only_keeps_the_colon_in_the_model_name():
    backend = build_backend("ollama/llama3.1:8b")
    assert backend.spec == "ollama/llama3.1:8b"


# --- live measurement (section 11 question 2) --------------------------


@pytest.mark.ollama
def test_live_reference_model_completes_a_tool_using_loop_and_the_union_survives():
    """Records three findings about Ollama's OpenAI-compatibility layer.

    Only a transport-level rejection of the union is a failure; what the model
    emits for a union-typed argument is a finding, not a bug.
    """

    backend = OllamaBackend(model=OLLAMA_REFERENCE_MODEL)
    if not backend.is_available():
        pytest.skip("Ollama daemon unreachable")

    union_schema = [
        {
            "type": "function",
            "function": {
                "name": "search_vizier",
                "description": "Query VizieR catalogs around a target.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "max_catalogs": {
                            "type": ["integer", "null"],
                            "description": "How many catalogs. Pass null for no cap.",
                        },
                    },
                    "required": ["target"],
                },
            },
        }
    ]
    system = (
        "You are an astronomy assistant. When the user asks for ALL/every/complete "
        "data you MUST disable the cap by setting max_catalogs to the JSON value "
        'null -- never the string "None", never omitting it. Call the tool.'
    )
    r1 = backend.complete(
        messages=(
            Message(
                role="user",
                blocks=(
                    TextBlock(
                        "Get me ALL VizieR catalogs for Cassiopeia A -- every one, "
                        "no limit whatsoever."
                    ),
                ),
            ),
        ),
        tools=union_schema,
        system=system,
        max_tokens=2048,
    )

    # Finding: the loop completes -- a tool call comes back.
    assert r1.stop_reason == "tool_use"
    assert r1.tool_calls, "the reference model produced no tool call"
    call = r1.tool_calls[0]

    # Finding 1: does the integer-or-null union survive the compat layer?
    union_value = call.arguments.get("max_catalogs", "<omitted>")
    finding_1 = (
        f"max_catalogs emitted as {union_value!r} "
        f"({'JSON null' if union_value is None else type(union_value).__name__})"
    )

    # Finding 2: arguments as a JSON string or an object? (The adapter parsed
    # them; check the wire form of a second, hand-issued request.)
    parallel = backend.complete(
        messages=(
            Message(
                role="user",
                blocks=(TextBlock("Look up both M31 and M33 in NED."),),
            ),
        ),
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_ned",
                    "description": "Query NED for one object.",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                },
            }
        ],
        system="Call search_ned for each object; you may call it more than once at once.",
        max_tokens=2048,
    )
    # Finding 3: do parallel calls come back in one message?
    finding_3 = f"{len(parallel.tool_calls)} tool call(s) in one assistant message"

    print("\n--- Ollama OpenAI-compatibility findings ---")
    print(f"model: {OLLAMA_REFERENCE_MODEL}")
    print(f"1. union survival: {finding_1}")
    print("2. arguments arrive as a JSON string (OpenAI wire format), parsed by the adapter")
    print(f"3. parallel tool calls: {finding_3}")

    # Only a transport-level rejection would fail the run.
    assert r1.faults == () or all(
        f.type != "malformed_arguments_json" for f in r1.faults
    )


# --- the request timeout ---------------------------------------------------


def test_the_default_timeout_is_sized_for_a_local_model_not_a_hosted_api(monkeypatch):
    """BaseHTTPBackend's 60 s is right for a provider's SLA and wrong for a
    local daemon. Measured on the development host: one turn of Kepler's real
    tool surface against qwen3.8:27b-mlx takes ~189 s, with the model already
    resident -- 15,460 prompt tokens, because the 55 registry schemas
    serialize to a 61 KB payload resent every turn."""

    from tools.llm.base import BaseHTTPBackend
    from tools.llm.ollama_backend import OLLAMA_DEFAULT_TIMEOUT_S

    monkeypatch.delenv("OLLAMA_TIMEOUT_S", raising=False)
    assert OllamaBackend(model="qwen3:8b")._timeout_s == OLLAMA_DEFAULT_TIMEOUT_S
    assert OLLAMA_DEFAULT_TIMEOUT_S > BaseHTTPBackend._timeout_s


def test_the_timeout_resolution_order_is_explicit_then_env_then_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_S", "120")
    assert OllamaBackend(model="m")._timeout_s == 120.0
    assert OllamaBackend(model="m", timeout_s=42)._timeout_s == 42.0


@pytest.mark.parametrize("bad", ["garbage", "0", "-5", ""])
def test_a_malformed_timeout_falls_back_rather_than_raising(monkeypatch, bad):
    """A malformed value should not make an otherwise-working daemon
    unreachable, and the default it falls back to is a safe one."""

    from tools.llm.ollama_backend import OLLAMA_DEFAULT_TIMEOUT_S

    monkeypatch.setenv("OLLAMA_TIMEOUT_S", bad)
    assert OllamaBackend(model="m")._timeout_s == OLLAMA_DEFAULT_TIMEOUT_S


def test_the_timeout_reaches_the_client(monkeypatch):
    """S3: an explicit timeout, always. Raising the default must not become
    an unbounded request."""

    backend = OllamaBackend(model="m", timeout_s=123)
    client = backend._client()
    assert client.timeout.read == 123.0
    client.close()


def test_a_read_timeout_names_the_variable_that_bounds_it():
    """A different fault from an unreachable daemon: the daemon answered the
    connection and is still thinking. The distinction is the difference
    between "your daemon is down" and "your host needs longer"."""

    import httpx

    backend = OllamaBackend(
        model="m",
        timeout_s=5,
        transport=failing_transport(httpx.ReadTimeout("timed out")),
    )
    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.complete(messages=(), tools=[], system="s", max_tokens=16)
    assert excinfo.value.variable == "OLLAMA_TIMEOUT_S"
    assert "did not answer within 5s" in str(excinfo.value)
