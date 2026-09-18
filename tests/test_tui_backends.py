"""Backend selection: the ``.env`` reader, spec resolution, and the probe.

All headless. Nothing here starts a terminal, builds a real adapter, or opens
a socket -- ``open_backend`` takes its builder as a keyword argument precisely
so this file can drive every branch with stand-ins.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools import config
from tools.llm.base import BackendUnavailableError
from tools.tui import backends


# --------------------------------------------------------------------------
# .env loading
# --------------------------------------------------------------------------


def test_load_dotenv_reads_names_values_comments_and_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "PLAIN=value",
                "export EXPORTED=exported-value",
                "  SPACED  =  spaced-value  ",
                "QUOTED=\"double quoted\"",
                "SINGLE='single quoted'",
                "NOT_INTERPOLATED=$HOME",
            ]
        ),
        encoding="utf-8",
    )
    environ: dict[str, str] = {}

    loaded = config.load_dotenv(env_file, environ=environ)

    assert loaded == (
        "PLAIN",
        "EXPORTED",
        "SPACED",
        "QUOTED",
        "SINGLE",
        "NOT_INTERPOLATED",
    )
    assert environ["PLAIN"] == "value"
    assert environ["EXPORTED"] == "exported-value"
    assert environ["SPACED"] == "spaced-value"
    assert environ["QUOTED"] == "double quoted"
    assert environ["SINGLE"] == "single quoted"
    # A credential is not a shell word: nothing is expanded.
    assert environ["NOT_INTERPOLATED"] == "$HOME"


def test_load_dotenv_reads_a_bare_anthropic_key_as_its_variable(tmp_path):
    """The file this repository ships on a development host is the key alone,
    with no variable name in front of it."""

    env_file = tmp_path / ".env"
    env_file.write_text("sk-ant-api03-not-a-real-key\n", encoding="utf-8")
    environ: dict[str, str] = {}

    assert config.load_dotenv(env_file, environ=environ) == ("ANTHROPIC_API_KEY",)
    assert environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-not-a-real-key"


def test_load_dotenv_ignores_a_bare_line_it_cannot_identify(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("just some words\n", encoding="utf-8")
    environ: dict[str, str] = {}

    assert config.load_dotenv(env_file, environ=environ) == ()
    assert environ == {}


def test_load_dotenv_never_overrides_a_variable_already_set(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    environ = {"ANTHROPIC_API_KEY": "from-environment"}

    assert config.load_dotenv(env_file, environ=environ) == ()
    assert environ["ANTHROPIC_API_KEY"] == "from-environment"


def test_load_dotenv_treats_an_empty_existing_value_as_unset(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    environ = {"ANTHROPIC_API_KEY": ""}

    assert config.load_dotenv(env_file, environ=environ) == ("ANTHROPIC_API_KEY",)
    assert environ["ANTHROPIC_API_KEY"] == "from-file"


def test_load_dotenv_is_silent_when_the_file_is_absent(tmp_path):
    environ: dict[str, str] = {}

    assert config.load_dotenv(tmp_path / "nothing-here", environ=environ) == ()
    assert environ == {}


# --------------------------------------------------------------------------
# Spec resolution
# --------------------------------------------------------------------------


def test_resolve_spec_expands_a_bare_provider_to_its_default_model():
    assert backends.resolve_spec("anthropic") == "anthropic/claude-sonnet-5"
    assert backends.resolve_spec("ollama") == "ollama/qwen3.8:27b-mlx"


def test_resolve_spec_accepts_a_provider_and_model_as_separate_words():
    assert backends.resolve_spec("ollama", "llama3.1:8b") == "ollama/llama3.1:8b"


def test_resolve_spec_passes_a_full_spec_through_untouched():
    # Only the factory decides which providers exist; this console lists two
    # but must not refuse the other two.
    assert backends.resolve_spec("gemini/gemini-2.5-pro") == "gemini/gemini-2.5-pro"
    # Split on the first slash only, so a model name carrying one survives.
    assert (
        backends.resolve_spec("openai/meta-llama/Llama-3-8b")
        == "openai/meta-llama/Llama-3-8b"
    )


def test_resolve_spec_rejects_an_unknown_bare_name_and_names_the_choices():
    with pytest.raises(backends.UnknownBackendError) as excinfo:
        backends.resolve_spec("hal9000")

    assert "anthropic" in str(excinfo.value)
    assert "ollama" in str(excinfo.value)


def test_resolve_spec_rejects_an_empty_selection_and_a_doubled_model():
    with pytest.raises(backends.UnknownBackendError):
        backends.resolve_spec()
    with pytest.raises(backends.UnknownBackendError):
        backends.resolve_spec("ollama/qwen3:8b", "llama3.1:8b")


# --------------------------------------------------------------------------
# Opening a backend
# --------------------------------------------------------------------------


class _Probed:
    """A backend whose availability probe answers however the test says."""

    def __init__(self, spec: str, available: bool) -> None:
        self.spec = spec
        self._available = available
        self.probes = 0

    def is_available(self) -> bool:
        self.probes += 1
        return self._available


def test_open_backend_returns_a_backend_whose_service_answers():
    backend = _Probed("ollama/qwen3:8b", available=True)

    opened = backends.open_backend("ollama/qwen3:8b", build=lambda spec, **_: backend)

    assert opened is backend
    assert backend.probes == 1


def test_open_backend_refuses_a_backend_whose_service_is_silent():
    backend = _Probed("ollama/qwen3:8b", available=False)

    with pytest.raises(BackendUnavailableError) as excinfo:
        backends.open_backend("ollama/qwen3:8b", build=lambda spec, **_: backend)

    # The endpoint variable, not a credential one: Ollama authenticates with
    # nothing, so "set your key" would be the wrong instruction.
    assert excinfo.value.variable == "OLLAMA_BASE_URL"


class _WithModels(_Probed):
    """A backend that can also report which models its service holds."""

    def __init__(self, spec: str, installed) -> None:
        super().__init__(spec, available=True)
        self._installed = installed

    def installed_models(self):
        return self._installed


def test_open_backend_refuses_a_model_the_running_service_does_not_hold():
    """The daemon being up is not the daemon having your model.

    Ollama answers an unknown model with a 404 from the chat endpoint, which
    lands mid-turn on the user's first question as an httpx error. The switch
    is where that must be caught, while there is still a backend to stay on.
    """

    backend = _WithModels("ollama/qwen3:8b", ("gemma4:12b", "qwen3.5:9b"))

    with pytest.raises(backends.ModelNotInstalled) as excinfo:
        backends.open_backend("ollama/qwen3:8b", build=lambda spec, **_: backend)

    assert excinfo.value.model == "qwen3:8b"
    assert excinfo.value.installed == ("gemma4:12b", "qwen3.5:9b")


def test_open_backend_accepts_a_model_the_service_reports():
    backend = _WithModels("ollama/qwen3.5:9b", ("gemma4:12b", "qwen3.5:9b"))

    assert backends.open_backend("ollama/qwen3.5:9b", build=lambda spec, **_: backend) is backend


def test_an_unaskable_model_listing_is_not_treated_as_an_empty_one():
    """`()` means "could not ask", never "holds nothing" -- a failed listing
    must not become a refusal to run."""

    backend = _WithModels("ollama/qwen3:8b", ())

    assert backends.open_backend("ollama/qwen3:8b", build=lambda spec, **_: backend) is backend


def test_unavailable_message_for_a_missing_model_names_what_is_installed():
    exc = backends.ModelNotInstalled(
        "ollama/qwen3:8b", "qwen3:8b", ("gemma4:12b", "qwen3.5:9b")
    )

    message = backends.unavailable_message(
        "ollama/qwen3:8b", exc, "anthropic/claude-sonnet-5"
    )

    assert "no model named 'qwen3:8b'" in message
    assert "gemma4:12b" in message and "qwen3.5:9b" in message
    # Not the daemon-down remedy: the daemon is up.
    assert "ollama serve" not in message
    assert "Still on anthropic/claude-sonnet-5" in message


def test_unavailable_message_elides_a_long_model_listing():
    exc = backends.ModelNotInstalled(
        "ollama/absent", "absent", tuple(f"m{i}:1b" for i in range(12))
    )

    message = backends.unavailable_message("ollama/absent", exc)

    assert "m0:1b" in message
    assert "and 4 more" in message


def test_open_backend_leaves_a_backend_without_a_probe_alone():
    class _Unprobeable:
        spec = "anthropic/claude-sonnet-5"

    backend = _Unprobeable()

    assert backends.open_backend("anthropic/claude-sonnet-5", build=lambda spec, **_: backend) is backend


def test_open_backend_propagates_a_construction_failure_unchanged():
    def build(spec: str, **_):
        raise BackendUnavailableError("ANTHROPIC_API_KEY")

    with pytest.raises(BackendUnavailableError) as excinfo:
        backends.open_backend("anthropic/claude-sonnet-5", build=build)

    assert excinfo.value.variable == "ANTHROPIC_API_KEY"


# --------------------------------------------------------------------------
# What a person is told
# --------------------------------------------------------------------------


def test_unavailable_message_says_what_to_do_and_what_still_works():
    message = backends.unavailable_message(
        "ollama/qwen3:8b",
        BackendUnavailableError("OLLAMA_BASE_URL"),
        "anthropic/claude-sonnet-5",
    )

    assert "ollama/qwen3:8b" in message
    assert "ollama serve" in message
    assert "Still on anthropic/claude-sonnet-5" in message


def test_unavailable_message_points_an_anthropic_failure_at_the_env_file():
    message = backends.unavailable_message(
        "anthropic/claude-sonnet-5", BackendUnavailableError("ANTHROPIC_API_KEY")
    )

    assert ".env" in message
    assert "ANTHROPIC_API_KEY" in message
    assert "Still on" not in message


def test_unavailable_message_falls_back_to_naming_the_variable():
    message = backends.unavailable_message(
        "openai/gpt-4.1", BackendUnavailableError("OPENAI_API_KEY")
    )

    assert "set OPENAI_API_KEY" in message


def test_describe_choices_lists_every_choice_and_marks_the_active_one():
    described = backends.describe_choices("ollama/qwen3:8b")

    assert "Active backend: ollama/qwen3:8b" in described
    for choice in backends.CHOICES:
        assert f"/backend {choice.provider}" in described
    assert "* /backend ollama" in described
    assert "* /backend anthropic" not in described


def test_backend_selection_has_no_textual_import():
    """Like the command registry, this must stay testable without a terminal."""

    tree = ast.parse(Path(backends.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not {name for name in imported if name.startswith("textual")}
