"""``ReplayBackend``: transcript replay, ``on_text``, and loud exhaustion.

docs/benchmarking/harness.md section 5.4. The harness replays remote *tools*
against live models; this replays the *model*, so the harness can be tested
with both sides recorded -- offline, deterministic, and free.
"""

from __future__ import annotations

import json

import pytest

from tools import artifacts, config
from tools.agent.engine import run_session
from tools.llm.factory import RECOGNIZED_PROVIDERS, build_backend
from tools.llm.replay_backend import (
    ReplayBackend,
    TranscriptError,
    TranscriptExhausted,
    load_transcript,
)
from tools.llm.types import ModelResponse
from tools.models import PulsarScan, PulsarScanList

SMOKE_TRANSCRIPT = "benchmarks/transcripts/smoke.json"


def _write(tmp_path, payload, name="t.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- the transcript format ------------------------------------------------


def test_a_transcript_loads_into_model_responses(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "stop_reason": "tool_use",
                "text": "looking",
                "tool_calls": [
                    {"call_id": "c1", "name": "list_pulsar_scans", "arguments": {}}
                ],
                "usage": {"input_tokens": 120, "output_tokens": 8},
                "raw_stop_reason": "tool_use",
            },
            {"stop_reason": "end_turn", "text": "done"},
        ],
    )
    responses = load_transcript(path)
    assert [r.stop_reason for r in responses] == ["tool_use", "end_turn"]
    assert responses[0].tool_calls[0].name == "list_pulsar_scans"
    assert responses[0].usage.input_tokens == 120
    assert responses[0].usage.cache_read_tokens is None
    assert responses[1].tool_calls == ()
    assert responses[1].usage is None


def test_a_recorded_fault_replays_as_a_protocol_fault(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "stop_reason": "end_turn",
                "text": "",
                "faults": [
                    {
                        "type": "malformed_arguments_json",
                        "detail": "unterminated string",
                        "tool_name": "search_vizier",
                    }
                ],
            }
        ],
    )
    fault = load_transcript(path)[0].faults[0]
    assert fault.type == "malformed_arguments_json"
    assert fault.tool_name == "search_vizier"


@pytest.mark.parametrize(
    "payload",
    [
        {"stop_reason": "finished"},
        {"stop_reason": None},
        {},
    ],
)
def test_an_unrecognized_stop_reason_fails_at_load(tmp_path, payload):
    with pytest.raises(TranscriptError, match="stop_reason"):
        load_transcript(_write(tmp_path, [payload]))


def test_an_unknown_key_fails_at_load_rather_than_being_ignored(tmp_path):
    """A typo in ``tool_calls`` that is silently dropped produces a turn which
    quietly calls nothing, and a harness test that then passes is asserting
    the loop can do nothing."""

    with pytest.raises(TranscriptError, match="tool_call"):
        load_transcript(
            _write(tmp_path, [{"stop_reason": "tool_use", "tool_call": []}])
        )


def test_an_unknown_usage_key_fails_at_load(tmp_path):
    with pytest.raises(TranscriptError, match="usage"):
        load_transcript(
            _write(
                tmp_path,
                [{"stop_reason": "end_turn", "usage": {"prompt_tokens": 10}}],
            )
        )


def test_a_tool_call_missing_its_identity_fails_at_load(tmp_path):
    with pytest.raises(TranscriptError, match="call_id"):
        load_transcript(
            _write(
                tmp_path,
                [{"stop_reason": "tool_use", "tool_calls": [{"name": "x"}]}],
            )
        )


def test_string_arguments_are_rejected_with_the_fault_route_named(tmp_path):
    """A transcript holds already-parsed arguments; replaying a provider's
    parse failure is what the ``faults`` key is for."""

    with pytest.raises(TranscriptError, match="malformed_arguments_json"):
        load_transcript(
            _write(
                tmp_path,
                [
                    {
                        "stop_reason": "tool_use",
                        "tool_calls": [
                            {"call_id": "c", "name": "x", "arguments": "{\"a\":"}
                        ],
                    }
                ],
            )
        )


def test_a_non_list_transcript_fails_at_load(tmp_path):
    with pytest.raises(TranscriptError, match="list"):
        load_transcript(_write(tmp_path, {"stop_reason": "end_turn"}))


def test_invalid_json_fails_at_load(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[{", encoding="utf-8")
    with pytest.raises(TranscriptError, match="valid JSON"):
        load_transcript(path)


# --- the backend ----------------------------------------------------------


def test_spec_is_replay_slash_the_transcript_stem():
    backend = ReplayBackend.from_file(SMOKE_TRANSCRIPT)
    assert backend.spec == "replay/smoke"
    assert backend.capabilities.streaming is False
    assert backend.capabilities.supports_union_types is True


def test_on_text_is_called_once_per_response_the_way_a_non_streaming_adapter_does():
    backend = ReplayBackend([ModelResponse(stop_reason="end_turn", text="hello")])
    chunks: list[str] = []
    backend.complete(
        messages=(), tools=[], system="s", max_tokens=16, on_text=chunks.append
    )
    assert chunks == ["hello"]


def test_a_response_with_no_text_calls_on_text_not_at_all():
    backend = ReplayBackend([ModelResponse(stop_reason="tool_use", text="")])
    chunks: list[str] = []
    backend.complete(
        messages=(), tools=[], system="s", max_tokens=16, on_text=chunks.append
    )
    assert chunks == []


def test_responses_are_consumed_in_order_and_the_calls_are_recorded():
    backend = ReplayBackend(
        [
            ModelResponse(stop_reason="tool_use", text="one"),
            ModelResponse(stop_reason="end_turn", text="two"),
        ]
    )
    assert backend.remaining == 2
    first = backend.complete(messages=(), tools=[], system="sys", max_tokens=8)
    second = backend.complete(messages=(), tools=[], system="sys", max_tokens=8)
    assert (first.text, second.text) == ("one", "two")
    assert backend.remaining == 0
    assert [call["system"] for call in backend.calls] == ["sys", "sys"]


def test_running_past_the_end_raises_rather_than_wrapping_around():
    """Loud on purpose. A transcript that repeated its last turn would drive
    an agent loop forever, and the smoke suite exists to prove the loop
    reaches ``end_turn``."""

    backend = ReplayBackend([ModelResponse(stop_reason="tool_use")], name="short")
    backend.complete(messages=(), tools=[], system="s", max_tokens=8)
    with pytest.raises(TranscriptExhausted) as excinfo:
        backend.complete(messages=(), tools=[], system="s", max_tokens=8)
    assert excinfo.value.name == "short"
    assert "turn 2" in str(excinfo.value)


def test_it_is_not_reachable_from_the_factory():
    """A transcript is a test asset, not somewhere an operator points a run."""

    assert "replay" not in RECOGNIZED_PROVIDERS
    with pytest.raises(ValueError, match="unknown provider"):
        build_backend("replay/smoke")


# --- end to end through the real loop -------------------------------------


def test_the_smoke_transcript_drives_run_session_to_end_turn(monkeypatch, tmp_path):
    """The 4b gate. Both sides replayed: no socket, no key, no model, and a
    session manifest at the end that a grader can read."""

    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")

    scan = PulsarScan(
        path=str(tmp_path / "b0329.txt"),
        name="B0329+54",
        curated_period_s=0.7145197,
        period_source="curated",
    )
    schemas = [
        {
            "name": "list_pulsar_scans",
            "description": "List bundled scans.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "resolve_pulsar_scan",
            "description": "Resolve a scan by name.",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    ]
    functions = {
        "list_pulsar_scans": lambda: PulsarScanList(
            status="ok", count=1, scans=[scan], search_root=str(tmp_path)
        ),
        "resolve_pulsar_scan": lambda name: scan,
    }

    backend = ReplayBackend.from_file(SMOKE_TRANSCRIPT)
    emitted = list(
        run_session(
            "What pulsar scans are here?",
            backend=backend,
            system="sys",
            max_turns=6,
            tool_schemas=schemas,
            tool_functions=functions,
        )
    )

    assert emitted[-1].outcome == "end_turn"
    assert backend.remaining == 0

    manifest = json.loads(
        (tmp_path / "artifacts").rglob("session_manifest.json").__next__().read_text()
    )
    assert manifest["outcome"] == "end_turn"
    assert manifest["backend"]["spec"] == "replay/smoke"
    assert [call["tool_name"] for call in manifest["tool_calls"]] == [
        "list_pulsar_scans",
        "resolve_pulsar_scan",
    ]
    assert manifest["protocol_faults"] == []
    # The recorded usage reaches the v2 totals, so the smoke run exercises the
    # efficiency axis's input as well as the loop.
    assert manifest["usage_totals"]["output_tokens"] == 28 + 31 + 96
    assert manifest["usage_totals"]["cache_read_tokens"] == 11800 * 3


def test_the_committed_smoke_transcript_is_well_formed_and_terminates():
    responses = load_transcript(SMOKE_TRANSCRIPT)
    assert responses[-1].stop_reason == "end_turn"
    assert all(r.stop_reason == "tool_use" for r in responses[:-1])
    # Header reads only: the smoke suite is the harness's regression test, not
    # a measurement, and must stay under a second.
    called = {c.name for r in responses for c in r.tool_calls}
    assert called == {"list_pulsar_scans", "resolve_pulsar_scan"}
