"""Argument validation wired through the runner shim (S8, Phase 1b).

Uses a hand-written stub backend passed through the ``backend`` keyword -- no
anthropic SDK to fake here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.llm_fakes import StubBackend
from tools import artifacts, config, runner
from tools.llm.types import ModelResponse, ToolCallBlock
from tools.models import ToolResult


@pytest.fixture(autouse=True)
def _artifact_root(monkeypatch, tmp_path):
    root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)


@pytest.fixture
def registry(monkeypatch):
    calls: list[dict] = []

    def capped_search(**kwargs):
        calls.append(kwargs)
        return ToolResult(status="ok", count=0)

    monkeypatch.setattr(
        runner,
        "TOOL_SCHEMAS",
        [
            {
                "name": "capped_search",
                "description": "search with an optional cap",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "max_catalogs": {"type": ["integer", "null"]},
                    },
                    "required": ["target"],
                },
            }
        ],
    )
    monkeypatch.setattr(runner, "TOOL_FUNCTIONS", {"capped_search": capped_search})
    return calls


def _run(backend):
    return runner.run("find everything", max_turns=4, backend=backend)


def test_the_string_None_is_rejected_as_stringified_null_and_never_dispatched(registry):
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(
                    ToolCallBlock(
                        call_id="c0",
                        name="capped_search",
                        arguments={"target": "Cas A", "max_catalogs": "None"},
                    ),
                ),
            ),
            ModelResponse(stop_reason="end_turn", text="done"),
        ]
    )
    manifest_path = _run(backend)

    assert registry == []  # the tool function was never called

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    faults = manifest["protocol_faults"]
    assert len(faults) == 1
    assert faults[0]["type"] == "stringified_null"
    assert faults[0]["tool_name"] == "capped_search"
    assert faults[0]["turn"] == 1
    # the recorded tool call keeps the real arguments the model sent
    assert manifest["tool_calls"][0]["arguments"] == {
        "target": "Cas A",
        "max_catalogs": "None",
    }
    assert manifest["tool_calls"][0]["status"] == "error"


def test_json_null_is_the_correct_way_to_uncap_and_dispatches_normally(registry):
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(
                    ToolCallBlock(
                        call_id="c0",
                        name="capped_search",
                        arguments={"target": "Cas A", "max_catalogs": None},
                    ),
                ),
            ),
            ModelResponse(stop_reason="end_turn", text="done"),
        ]
    )
    manifest_path = _run(backend)

    assert registry == [{"target": "Cas A", "max_catalogs": None}]
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert manifest["protocol_faults"] == []


def test_an_identical_rejected_call_is_a_cache_hit_the_second_time(registry):
    bad = ToolCallBlock(
        call_id="c0", name="capped_search", arguments={"target": "X", "max_catalogs": "None"}
    )
    backend = StubBackend(
        [
            ModelResponse(stop_reason="tool_use", tool_calls=(bad,)),
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(
                    ToolCallBlock(
                        call_id="c1", name="capped_search",
                        arguments={"target": "X", "max_catalogs": "None"},
                    ),
                ),
            ),
            ModelResponse(stop_reason="end_turn", text="done"),
        ]
    )
    manifest_path = _run(backend)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert [c["cache_hit"] for c in manifest["tool_calls"]] == [False, True]
    assert len(manifest["protocol_faults"]) == 2
    assert registry == []
