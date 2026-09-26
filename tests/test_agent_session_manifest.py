"""Session manifest behaviour, engine and Anthropic adapter end to end.

Retargeted from ``tools/runner.py`` when the shim was deleted. The assertions are the shim's, unchanged: what they pin is the
manifest the engine writes, and the engine wrote it before the shim was
removed as well as after. Only the call site moved -- from ``runner.run()`` to
iterating :func:`~tools.agent.engine.run_session` -- and the backend became
explicit rather than built inside the shim.

It is the one test that drives the engine, the real Anthropic adapter (over a
fake SDK module) and the session recorder together, which is why it was worth
keeping rather than folding into the engine's own tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import artifacts, config
from tools.agent import events
from tools.agent.engine import run_session
from tools.agent.prompt import SYSTEM_PROMPT
from tools.llm.anthropic_backend import AnthropicBackend
from tools.models import ToolResult
from tools.sessions import AgentSession


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


def test_a_session_persists_its_manifest_and_reuses_a_cached_tool_call(
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

    schemas = [
        {
            "name": "fake_lookup",
            "description": "Fake lookup.",
            "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}},
        }
    ]
    session = AgentSession(
        user_message="Find M31",
        model="fake-model",
        max_turns=5,
        system=SYSTEM_PROMPT,
    )

    manifest_path = None
    for event in run_session(
        "Find M31",
        backend=AnthropicBackend(model="fake-model"),
        max_turns=5,
        session=session,
        tool_schemas=schemas,
        tool_functions={"fake_lookup": fake_lookup},
    ):
        if isinstance(event, events.SessionFinished):
            manifest_path = event.manifest_path

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
