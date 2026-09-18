"""Session manifest schema version 2 (docs/benchmarking/harness.md section 8).

Version 2 is additive. The properties that matter are as much about what it
does *not* do as what it adds: a recorded v1 manifest must still read, and an
absent token count must stay ``None`` rather than becoming ``0`` -- a provider
that did not report cache tokens did not report zero of them, and a benchmark
that cannot tell the two apart will report a caching backend and a silent one
as doing identical work.
"""

from __future__ import annotations

import json

import pytest

from tests.llm_fakes import StubBackend
from tools import artifacts, config
from tools.agent.engine import run_session
from tools.llm.types import ModelResponse, Usage
from tools.models import ToolResult
from tools.sessions import (
    USAGE_FIELDS,
    AgentSession,
    backend_record,
    read_session_manifest,
)


def _session(**kwargs) -> AgentSession:
    return AgentSession(
        user_message="find M31", model="m", max_turns=4, system="sys", **kwargs
    )


# --- the v2 payload -------------------------------------------------------


def test_schema_version_is_2():
    assert _session().to_manifest()["schema_version"] == 2


def test_every_v1_key_is_still_written_with_its_v1_meaning():
    """Additive means additive: nothing v1 wrote may have been renamed or
    dropped, or a reader of a recorded run breaks on the upgrade."""

    manifest = _session().to_manifest()
    for key in (
        "schema_version",
        "session_id",
        "created_at",
        "updated_at",
        "completed_at",
        "outcome",
        "user_message",
        "model",
        "max_turns",
        "current_turn",
        "system_prompt_sha256",
        "artifact_directory",
        "manifest_path",
        "turns",
        "tool_call_count",
        "cache_entry_count",
        "tool_calls",
        "call_cache",
        "protocol_faults",
        "notes",
    ):
        assert key in manifest, key


def test_a_turn_carries_latency_usage_and_the_raw_stop_reason():
    session = _session()
    session.record_turn(
        turn=1,
        stop_reason="max_tokens",
        raw_stop_reason="length",
        assistant_text="partial",
        tool_call_sequences=[],
        usage=Usage(input_tokens=120, output_tokens=18),
        latency_ms=845.5,
    )
    turn = session.to_manifest()["turns"][0]
    assert turn["latency_ms"] == 845.5
    assert turn["usage"]["input_tokens"] == 120
    # The normalized value and the provider's own string are separate keys:
    # `length`, `MAX_TOKENS` and `max_tokens` all mean the ceiling was hit,
    # and only the normalized one says so without a per-provider lookup.
    assert turn["stop_reason"] == "max_tokens"
    assert turn["raw_stop_reason"] == "length"


def test_a_provider_that_reported_no_usage_records_none_not_a_dict_of_zeros():
    session = _session()
    session.record_turn(
        turn=1, stop_reason="end_turn", assistant_text="hi", tool_call_sequences=[]
    )
    turn = session.to_manifest()["turns"][0]
    assert turn["usage"] is None
    assert turn["latency_ms"] is None


def test_usage_totals_sum_each_class_separately():
    session = _session()
    for _ in range(2):
        session.record_turn(
            turn=1,
            stop_reason="tool_use",
            assistant_text="",
            tool_call_sequences=[],
            usage=Usage(
                input_tokens=100,
                output_tokens=10,
                cache_read_tokens=4000,
                cache_write_tokens=None,
            ),
        )
    totals = session.to_manifest()["usage_totals"]
    assert totals["input_tokens"] == 200
    assert totals["output_tokens"] == 20
    # Kept apart from input_tokens on purpose: SYSTEM_PROMPT plus the tool
    # schemas is a large fixed prefix resent every turn, so a backend that
    # caches it and one that does not are doing visibly different work.
    assert totals["cache_read_tokens"] == 8000
    assert totals["cache_write_tokens"] is None


def test_a_class_no_provider_reported_stays_none_rather_than_zero():
    session = _session()
    session.record_turn(
        turn=1,
        stop_reason="end_turn",
        assistant_text="hi",
        tool_call_sequences=[],
        usage=Usage(input_tokens=5),
    )
    totals = session.to_manifest()["usage_totals"]
    assert totals["input_tokens"] == 5
    assert totals["reasoning_tokens"] is None
    assert set(totals) == set(USAGE_FIELDS)


def test_a_class_reported_on_some_turns_totals_over_those_turns():
    """Half-reported is not unreported: the total over the turns that did
    report is a real number, and blanking it would lose it."""

    session = _session()
    session.record_turn(
        turn=1, stop_reason="tool_use", assistant_text="", tool_call_sequences=[]
    )
    session.record_turn(
        turn=2,
        stop_reason="end_turn",
        assistant_text="",
        tool_call_sequences=[],
        usage=Usage(output_tokens=7),
    )
    assert session.to_manifest()["usage_totals"]["output_tokens"] == 7


def test_usage_totals_are_none_when_nothing_reported_anything():
    session = _session()
    session.record_turn(
        turn=1, stop_reason="end_turn", assistant_text="hi", tool_call_sequences=[]
    )
    assert all(
        value is None for value in session.to_manifest()["usage_totals"].values()
    )


# --- the backend record ---------------------------------------------------


def test_backend_record_splits_the_spec_and_keeps_the_capabilities():
    record = backend_record(StubBackend([], spec="ollama/qwen3.8:27b-mlx"))
    assert record["spec"] == "ollama/qwen3.8:27b-mlx"
    assert record["provider"] == "ollama"
    assert record["model"] == "qwen3.8:27b-mlx"
    # The dialect is why two runs are or are not comparable: a model reached
    # through the Gemini OpenAPI subset is not being asked the same question
    # as one reached through JSON Schema.
    assert record["capabilities"]["schema_dialect"] == "json_schema"
    assert record["capabilities"]["max_output_tokens"] == 4096


def test_an_sdk_backend_with_no_base_url_records_none():
    assert backend_record(StubBackend([]))["base_url_host"] is None


def test_the_base_url_host_is_recorded_without_userinfo(monkeypatch):
    """S4. The port never puts a credential in a URL; the manifest is durable
    and must not become the one place a misconfigured one is preserved."""

    from tools.llm.ollama_backend import OllamaBackend

    backend = OllamaBackend(
        model="qwen3:8b", base_url="https://user:secret@ollama.example/v1"
    )
    record = backend_record(backend)
    assert record["base_url_host"] == "ollama.example"
    assert "secret" not in json.dumps(record)


def test_a_backend_with_no_spec_records_none_rather_than_an_empty_string():
    class _Bare:
        pass

    record = backend_record(_Bare())
    assert record["spec"] is None
    assert record["provider"] is None
    assert record["capabilities"] is None


# --- the artifact-subdirectory override -----------------------------------


def test_the_default_artifact_subdir_is_unchanged():
    session = _session()
    assert session.artifact_subdir == f"sessions/{session.session_id}"


def test_an_override_moves_the_manifest_and_the_artifacts_together(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")
    session = _session(artifact_subdir_override="bench/run-1/task/r1")
    assert session.artifact_subdir == "bench/run-1/task/r1"
    assert session.manifest_path.parent.name == "r1"


@pytest.mark.parametrize("bad", ["/absolute", "../escape", "a/../../b", ""])
def test_an_override_that_could_escape_the_artifact_root_is_rejected(bad):
    """Validated at construction, the same way ``scoped_artifacts`` validates
    its argument -- and earlier, so the error names the cause rather than
    arriving at the first artifact write several turns in."""

    with pytest.raises(ValueError):
        _session(artifact_subdir_override=bad)


# --- reading a recorded v1 manifest ---------------------------------------


V1_MANIFEST = {
    "schema_version": 1,
    "session_id": "20260101T000000Z_abc123def456",
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:10+00:00",
    "completed_at": "2026-01-01T00:00:10+00:00",
    "outcome": "end_turn",
    "user_message": "find M31",
    "model": "fake-model",
    "max_turns": 5,
    "current_turn": 1,
    "system_prompt_sha256": "0" * 64,
    "turns": [
        {
            "turn": 1,
            "stop_reason": "end_turn",
            "assistant_text": "done",
            "tool_call_sequences": [],
        }
    ],
    "tool_call_count": 0,
    "cache_entry_count": 0,
    "tool_calls": [],
    "call_cache": [],
    "protocol_faults": [],
}


def test_a_recorded_v1_manifest_still_reads(tmp_path):
    path = tmp_path / "session_manifest.json"
    path.write_text(json.dumps(V1_MANIFEST), encoding="utf-8")
    manifest = read_session_manifest(path)
    assert manifest["schema_version"] == 1
    assert manifest["outcome"] == "end_turn"


def test_a_v1_manifests_missing_keys_read_as_none_never_zero(tmp_path):
    """The rule a grader depends on. ``.get`` returning ``None`` is the whole
    contract; anything that defaults these to ``0`` reports a run nobody
    measured as a run that cost nothing."""

    path = tmp_path / "session_manifest.json"
    path.write_text(json.dumps(V1_MANIFEST), encoding="utf-8")
    manifest = read_session_manifest(path)
    assert manifest.get("usage_totals") is None
    assert manifest.get("backend") is None
    assert manifest["turns"][0].get("latency_ms") is None
    assert manifest["turns"][0].get("usage") is None
    assert manifest["turns"][0].get("raw_stop_reason") is None


# --- the engine wiring ----------------------------------------------------


def _stub_registry():
    schemas = [
        {
            "name": "fake_lookup",
            "description": "Fake lookup.",
            "input_schema": {
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
        }
    ]
    return schemas, {"fake_lookup": lambda target: ToolResult(status="ok", count=1)}


def test_the_engine_writes_the_backend_and_the_usage_into_the_manifest(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")
    schemas, functions = _stub_registry()
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="end_turn",
                text="M31 is a galaxy.",
                usage=Usage(input_tokens=1843, output_tokens=92, cache_read_tokens=12032),
                latency_ms=902.25,
                raw_stop_reason="stop",
            )
        ],
        spec="openai/gpt-4.1",
    )
    session = AgentSession(
        user_message="find M31",
        model="gpt-4.1",
        max_turns=3,
        system="sys",
        artifact_subdir_override="bench/run-1/find-m31/r1",
    )
    events = list(
        run_session(
            "find M31",
            backend=backend,
            system="sys",
            max_turns=3,
            session=session,
            tool_schemas=schemas,
            tool_functions=functions,
        )
    )
    assert events[-1].outcome == "end_turn"

    manifest = read_session_manifest(session.manifest_path)
    assert manifest["schema_version"] == 2
    assert manifest["backend"]["spec"] == "openai/gpt-4.1"
    assert manifest["backend"]["provider"] == "openai"
    assert manifest["usage_totals"]["input_tokens"] == 1843
    assert manifest["usage_totals"]["cache_read_tokens"] == 12032
    assert manifest["turns"][0]["latency_ms"] == 902.25
    assert manifest["turns"][0]["stop_reason"] == "end_turn"
    assert manifest["turns"][0]["raw_stop_reason"] == "stop"
    # The override put the record where the harness will look for it.
    assert session.manifest_path.parent.name == "r1"


def test_the_engine_records_the_backend_even_on_a_caller_supplied_session(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")
    schemas, functions = _stub_registry()
    session = AgentSession(
        user_message="hi", model="m", max_turns=2, system="sys"
    )
    assert session.backend is None
    list(
        run_session(
            "hi",
            backend=StubBackend(
                [ModelResponse(stop_reason="end_turn", text="hello")],
                spec="gemini/gemini-2.5-pro",
            ),
            system="sys",
            max_turns=2,
            session=session,
            tool_schemas=schemas,
            tool_functions=functions,
        )
    )
    assert session.backend["provider"] == "gemini"
