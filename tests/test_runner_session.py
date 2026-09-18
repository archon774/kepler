"""Session manifest behavior for the optional agent runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import artifacts, config, runner
from tools.models import ToolResult


class _FakeStream:
    def __init__(self, response, text_chunks=()):
        self._response = response
        self._chunks = list(text_chunks)
        self.text_stream = iter(self._chunks)

    def __iter__(self):
        # The adapter reads the SDK's own event stream, not `text_stream`:
        # reasoning is invisible from there.
        return iter(
            [SimpleNamespace(type="text", text=chunk) for chunk in self._chunks]
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def get_final_message(self):
        return self._response


class _FakeMessages:
    def __init__(self, streams):
        self._streams = iter(streams)
        self.requests = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        return next(self._streams)


def _tool_use_response(tool_use_id: str):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use",
                id=tool_use_id,
                name="fake_lookup",
                input={"target": "M31"},
            )
        ],
    )


def test_runner_persists_session_manifest_and_reuses_cached_tool_call(
    monkeypatch, tmp_path
):
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", artifact_root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", artifact_root)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    fake_messages = _FakeMessages(
        [
            _FakeStream(_tool_use_response("toolu_1"), ["Looking up M31.\n"]),
            _FakeStream(_tool_use_response("toolu_2"), ["Checking again.\n"]),
            _FakeStream(
                SimpleNamespace(stop_reason="end_turn", content=[]),
                ["Finished.\n"],
            ),
        ]
    )

    class FakeAnthropic:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.messages = fake_messages

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(Anthropic=FakeAnthropic),
    )

    calls = []

    def fake_lookup(target: str):
        calls.append(target)
        artifact = artifacts.write_text(
            json.dumps({"target": target}),
            f"lookup_{target}",
            subdir="fake",
            ext="json",
        )
        return ToolResult(status="ok", count=1, artifact=artifact)

    monkeypatch.setattr(runner, "TOOL_FUNCTIONS", {"fake_lookup": fake_lookup})
    monkeypatch.setattr(
        runner,
        "TOOL_SCHEMAS",
        [
            {
                "name": "fake_lookup",
                "description": "Fake lookup.",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )

    manifest_path = runner.run("Find M31", max_turns=5, model="fake-model")

    assert manifest_path is not None
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    assert manifest["outcome"] == "end_turn"
    assert manifest["model"] == "fake-model"
    assert manifest["user_message"] == "Find M31"
    assert manifest["tool_call_count"] == 2
    assert manifest["cache_entry_count"] == 1
    assert [call["cache_hit"] for call in manifest["tool_calls"]] == [False, True]
    assert calls == ["M31"]

    cache_entry = manifest["call_cache"][0]
    assert cache_entry["use_count"] == 2
    assert cache_entry["cache_hit_count"] == 1

    first_artifact = Path(manifest["tool_calls"][0]["artifacts"][0]["path"])
    second_artifact = Path(manifest["tool_calls"][1]["artifacts"][0]["path"])
    assert first_artifact == second_artifact
    assert manifest["session_id"] in first_artifact.parts
    assert first_artifact.exists()
    assert Path(manifest_path).parent == first_artifact.parents[1]
    assert artifacts.current_artifact_subdir() is None
