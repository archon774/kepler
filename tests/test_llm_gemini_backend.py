"""GeminiBackend: generateContent over raw httpx.

Phase 3 of docs/working/model-backends.md -- the hardest adapter: a different
schema dialect, a different message shape, and no tool-call identifiers at all.
"""

from __future__ import annotations

import json

import pytest

from tests.llm_fakes import CapturingTransport, load_response_fixture
from tools.llm import BackendUnavailableError, Message, TextBlock, ToolCallBlock, ToolResultBlock
from tools.llm.gemini_backend import GeminiBackend


def _backend(body, *, api_key="AIza-test"):
    capture = CapturingTransport(body)
    return GeminiBackend(model="gemini-2.5-pro", api_key=api_key, transport=capture()), capture


def _fc_response():
    return load_response_fixture("gemini_function_call.json")


# --- construction ------------------------------------------------------


def test_missing_api_key_raises_backend_unavailable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(BackendUnavailableError) as excinfo:
        GeminiBackend(model="gemini-2.5-pro")
    assert excinfo.value.variable == "GEMINI_API_KEY"


def test_capabilities_match_the_per_backend_table():
    caps = GeminiBackend(model="gemini-2.5-pro", api_key="AIza-x").capabilities
    assert caps.streaming is False
    assert caps.native_tool_call_ids is False
    assert caps.schema_dialect == "gemini_openapi"
    assert caps.supports_union_types is False
    assert caps.max_output_tokens == 8192


# --- S4: header auth only, no key in the URL -----------------------


def test_the_api_key_travels_in_the_x_goog_api_key_header_only():
    backend, capture = _backend(_fc_response())
    backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    request = capture.last
    assert request.headers.get("x-goog-api-key") == "AIza-test"
    assert "AIza-test" not in str(request.url)
    assert "key=" not in str(request.url)


# --- synthetic call ids -----------------------------------------


def test_function_call_parts_get_synthetic_ids_in_order():
    backend, _ = _backend(_fc_response())
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    assert response.stop_reason == "tool_use"
    assert response.raw_stop_reason == "STOP"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.call_id == "call_0"
    assert call.name == "search_ned"
    # arguments arrive as a mapping, not a JSON string
    assert call.arguments == {"name": "M31", "table": "photometry"}
    assert response.text == "I'll resolve M31 in NED."


def test_two_function_calls_get_call_0_and_call_1():
    body = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"functionCall": {"name": "search_ned", "args": {"name": "M31"}}},
                        {"functionCall": {"name": "search_ned", "args": {"name": "M33"}}},
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }
    backend, _ = _backend(body)
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    assert [c.call_id for c in response.tool_calls] == ["call_0", "call_1"]


# --- one-response-per-call ----------------------------------


def test_a_result_count_mismatch_raises_call_id_mismatch():
    backend, _ = _backend(_fc_response())
    history = (
        Message(
            role="assistant",
            blocks=(
                ToolCallBlock(call_id="call_0", name="search_ned", arguments={"name": "M31"}),
                ToolCallBlock(call_id="call_1", name="search_ned", arguments={"name": "M33"}),
            ),
        ),
        Message(
            role="user",
            blocks=(
                ToolResultBlock(call_id="call_0", name="search_ned", content='{"ok": 1}'),
            ),
        ),
    )
    with pytest.raises(ValueError, match="call_id_mismatch"):
        backend.complete(messages=history, tools=[], system="s", max_tokens=64)


def test_matching_counts_render_without_error():
    backend, capture = _backend(_fc_response())
    history = (
        Message(
            role="assistant",
            blocks=(
                ToolCallBlock(call_id="call_0", name="search_ned", arguments={"name": "M31"}),
            ),
        ),
        Message(
            role="user",
            blocks=(
                ToolResultBlock(call_id="call_0", name="search_ned", content='{"ok": 1}'),
            ),
        ),
    )
    backend.complete(messages=history, tools=[], system="s", max_tokens=64)
    body = json.loads(capture.last.content)
    assert body["contents"][0]["role"] == "model"
    assert body["contents"][0]["parts"][0]["functionCall"]["name"] == "search_ned"
    assert body["contents"][1]["role"] == "user"
    assert body["contents"][1]["parts"][0]["functionResponse"]["name"] == "search_ned"
    assert body["contents"][1]["parts"][0]["functionResponse"]["response"] == {"ok": 1}


# --- message shape (section 4.5) ---------------------------------


def test_system_prompt_goes_in_system_instruction_never_in_contents():
    backend, capture = _backend(_fc_response())
    backend.complete(
        messages=(Message(role="user", blocks=(TextBlock("find M31"),)),),
        tools=[],
        system="YOU ARE AN ASTRONOMER",
        max_tokens=64,
    )
    body = json.loads(capture.last.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "YOU ARE AN ASTRONOMER"
    for content in body["contents"]:
        for part in content["parts"]:
            assert part.get("text") != "YOU ARE AN ASTRONOMER"


def test_finish_reason_safety_maps_to_refusal():
    body = {"candidates": [{"content": {"parts": [{"text": ""}]}, "finishReason": "SAFETY"}]}
    backend, _ = _backend(body)
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    assert response.stop_reason == "refusal"


def test_max_tokens_with_a_tool_call_records_truncated_output():
    body = {
        "candidates": [
            {
                "content": {"parts": [{"functionCall": {"name": "t", "args": {}}}]},
                "finishReason": "MAX_TOKENS",
            }
        ]
    }
    backend, _ = _backend(body)
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=4)
    assert response.stop_reason == "max_tokens"
    assert "truncated_output" in [f.type for f in response.faults]


def test_usage_is_read_from_usage_metadata():
    backend, _ = _backend(_fc_response())
    response = backend.complete(messages=(), tools=[], system="s", max_tokens=64)
    assert response.usage.input_tokens == 512
    assert response.usage.output_tokens == 44
    assert response.usage.cache_read_tokens == 128


# --- Phase 3 gate: the union reaches Gemini as a nullable integer ----


def test_the_registry_union_reaches_gemini_as_a_nullable_integer_end_to_end(
    monkeypatch, tmp_path
):
    from tools import artifacts, config
    from tools.agent.engine import run_session

    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")

    body = {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
    capture = CapturingTransport(body)
    backend = GeminiBackend(model="gemini-2.5-pro", api_key="AIza-x", transport=capture())

    list(
        run_session(
            "everything about Cas A",
            backend=backend,
            tool_functions={},
        )
    )
    sent = json.loads(capture.last.content)
    declarations = sent["tools"][0]["functionDeclarations"]
    vizier = next(d for d in declarations if d["name"] == "search_vizier")
    max_catalogs = vizier["parameters"]["properties"]["max_catalogs"]
    assert max_catalogs["type"] == "INTEGER"
    assert max_catalogs["nullable"] is True
    assert "null" not in json.dumps(max_catalogs.get("type"))


# --- cross-backend security sweep (S4) ------------------------


def test_no_adapter_places_a_credential_in_a_url():
    secret = "SECRET-KEY-abc123def456"

    # The three HTTP adapters: inspect the real outgoing request.
    from tools.llm.openai_backend import OpenAIBackend
    from tools.llm.ollama_backend import OllamaBackend

    checks = [
        OpenAIBackend(model="gpt-4.1", api_key=secret),
        GeminiBackend(model="gemini-2.5-pro", api_key=secret),
    ]
    for backend in checks:
        capture = CapturingTransport({"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}], "choices": [{"message": {}, "finish_reason": "stop"}]})
        backend._transport = capture()
        try:
            backend.complete(messages=(), tools=[], system="s", max_tokens=8)
        except Exception:
            pass
        for request in capture.requests:
            assert secret not in str(request.url), backend.spec

    # Ollama sends no credential at all.
    ollama_capture = CapturingTransport({"choices": [{"message": {}, "finish_reason": "stop"}]})
    ollama = OllamaBackend(model="qwen3:8b", transport=ollama_capture())
    ollama.complete(messages=(), tools=[], system="s", max_tokens=8)
    for request in ollama_capture.requests:
        assert "authorization" not in request.headers

    # Anthropic authenticates through the SDK client (x-api-key header), never
    # a URL: the adapter hands the key to anthropic.Anthropic(api_key=...).
    import inspect

    from tools.llm import anthropic_backend

    src = inspect.getsource(anthropic_backend)
    assert "api_key=" in src and "?key=" not in src and "key=" + '"' not in src
