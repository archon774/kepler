"""The runner shim's backend selection: explicit kwarg, KEPLER_MODEL_BACKEND,
or the Anthropic default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.llm_fakes import StubBackend
from tools import artifacts, config, runner
from tools.llm.types import ModelResponse


@pytest.fixture(autouse=True)
def _artifact_root(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.delenv("KEPLER_MODEL_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_an_explicit_backend_kwarg_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("KEPLER_MODEL_BACKEND", "openai/gpt-4.1")
    monkeypatch.setattr(runner, "TOOL_SCHEMAS", [])
    monkeypatch.setattr(runner, "TOOL_FUNCTIONS", {})
    backend = StubBackend([ModelResponse(stop_reason="end_turn", text="done")])

    manifest_path = runner.run("hi", backend=backend)

    assert manifest_path is not None
    assert backend.calls, "the explicit stub backend was not used"


def test_KEPLER_MODEL_BACKEND_routes_through_build_backend(monkeypatch):
    # openai spec, no OPENAI_API_KEY -> build_backend raises BackendUnavailable
    # naming that variable, and the shim prints it and returns None. No network.
    monkeypatch.setenv("KEPLER_MODEL_BACKEND", "openai/gpt-4.1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    captured: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(map(str, a))))

    result = runner.run("hi")

    assert result is None
    assert any("OPENAI_API_KEY" in line for line in captured)


def test_the_default_path_still_names_anthropic_when_no_spec_and_no_key(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(map(str, a))))

    result = runner.run("hi")

    assert result is None
    assert any("ANTHROPIC_API_KEY" in line for line in captured)
