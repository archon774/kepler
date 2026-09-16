"""The console's selectable model backends, and how one is opened.

This is the UI-facing half of backend selection: the short list a person
actually picks from, the rule that turns ``anthropic`` into a full
``provider/model`` spec, and the availability probe that decides whether a
switch may happen at all.

It deliberately owns none of the construction rules. Credential and endpoint
binding stays in :mod:`tools.llm.factory` (S3) -- this module hands it a spec
and interprets the failure. Like :mod:`tools.tui.commands` it imports no
Textual, so every decision here is testable without a terminal.

**Why a probe and not a try/except around the first turn.** Anthropic fails
fast, at construction, when its key is missing. Ollama does not: a backend
pointed at a daemon that is not running builds perfectly and then raises a
connection error several seconds into the user's first question, after the
transcript already shows a turn starting. ``docs/working/tui-harness.md``
section 11 requires "never a connection traceback", so the switch is what
pays the probe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from tools.config import load_dotenv
from tools.llm.base import BackendUnavailableError, ModelBackend
from tools.llm.factory import build_backend

__all__ = [
    "BackendChoice",
    "CHOICES",
    "UnknownBackendError",
    "choice_for",
    "names",
    "resolve_spec",
    "open_backend",
    "describe_choices",
    "unavailable_message",
    "spec_of",
]


@dataclass(frozen=True)
class BackendChoice:
    """One provider the console offers by name, and what configures it."""

    provider: str
    default_model: str
    #: The variable that carries this provider's credential, or ``None`` when
    #: it authenticates with nothing. Named in every failure message, so a
    #: person is told what to set rather than what broke.
    credential_env: str | None
    #: The variable that moves this provider off its default host, if any.
    endpoint_env: str | None
    summary: str


#: The two backends this console offers by bare name. A full ``provider/model``
#: spec still reaches :func:`tools.llm.factory.build_backend`, which recognizes
#: four providers; these are the ones with a default model and a probe, and so
#: the ones ``/backend`` lists.
CHOICES: tuple[BackendChoice, ...] = (
    BackendChoice(
        provider="anthropic",
        default_model="claude-sonnet-5",
        credential_env="ANTHROPIC_API_KEY",
        endpoint_env=None,
        summary="Anthropic's hosted API. Streams natively; needs a key.",
    ),
    BackendChoice(
        provider="ollama",
        default_model="qwen3:8b",
        credential_env=None,
        endpoint_env="OLLAMA_BASE_URL",
        summary="A local Ollama daemon. No key; the daemon must be running.",
    ),
)


class UnknownBackendError(ValueError):
    """A bare name that is not one of :data:`CHOICES`."""


def choice_for(provider: str) -> BackendChoice | None:
    """Return the offered choice for a provider name, if there is one."""

    for choice in CHOICES:
        if choice.provider == provider:
            return choice
    return None


def resolve_spec(*words: str) -> str:
    """Turn what a person typed after ``/backend`` into a full spec.

    Accepts a bare provider (``anthropic``), a provider and model as separate
    words (``ollama qwen3:8b``), or a spec that already carries its model
    (``anthropic/claude-opus-5``). A spec with a slash is passed through
    untouched -- validating the provider is the factory's job, and it
    recognizes more of them than this console lists.
    """

    parts = [word for word in words if word]
    if not parts:
        raise UnknownBackendError("name a backend: " + ", ".join(names()))

    head = parts[0]
    if "/" in head:
        if len(parts) > 1:
            raise UnknownBackendError(
                f"{head!r} already names a model; drop the extra argument"
            )
        return head

    choice = choice_for(head)
    if choice is None:
        raise UnknownBackendError(
            f"unknown backend {head!r}; offered: " + ", ".join(names())
        )
    model = parts[1] if len(parts) > 1 else choice.default_model
    return f"{choice.provider}/{model}"


def names() -> tuple[str, ...]:
    """The provider names ``/backend`` accepts bare."""

    return tuple(choice.provider for choice in CHOICES)


def open_backend(
    spec: str, *, build: Callable[..., ModelBackend] = build_backend
) -> ModelBackend:
    """Build the backend named by ``spec`` and refuse to return a dead one.

    ``.env`` is re-read first, so a key added to the file while the console is
    open takes effect on the next ``/backend`` without a restart. It never
    overrides a variable already set -- see :func:`tools.config.load_dotenv`.

    Raises :class:`~tools.llm.base.BackendUnavailableError` when the backend
    cannot be constructed *or* when it builds but its service does not answer.
    Both carry the variable to set, which is the only thing the caller renders.
    """

    load_dotenv()
    backend = build(spec)

    probe = getattr(backend, "is_available", None)
    if callable(probe) and not probe():
        provider, _, _ = spec.partition("/")
        choice = choice_for(provider)
        variable = (
            (choice.endpoint_env if choice else None)
            or (choice.credential_env if choice else None)
            or "KEPLER_MODEL_BACKEND"
        )
        raise BackendUnavailableError(
            variable, f"{spec} built, but its service did not answer"
        )
    return backend


#: What to tell a person to *do*, keyed by the variable the port names. The
#: adapters' own hints are written for a Python caller ("pass api_key=..."),
#: which is not an option in front of a console prompt.
_REMEDIES: dict[str, str] = {
    "ANTHROPIC_API_KEY": (
        "no API key. Put it in the repository's .env file or set "
        "ANTHROPIC_API_KEY, then try again"
    ),
    "OLLAMA_BASE_URL": (
        "no Ollama daemon answered. Start one with `ollama serve`, or point "
        "OLLAMA_BASE_URL at the host running it"
    ),
}


def unavailable_message(
    spec: str, exc: BackendUnavailableError, current_spec: str = ""
) -> str:
    """One wording for a refused backend, shared by the launcher and ``/backend``.

    Always says what to do, and -- when the console is already running --
    which backend is still answering, so a failed switch never reads as a
    session that has lost its model.
    """

    remedy = _REMEDIES.get(exc.variable, f"set {exc.variable}")
    text = f"Cannot use {spec}: {remedy}."
    if current_spec:
        text += f" Still on {current_spec}."
    return text


def describe_choices(active_spec: str | None = None) -> str:
    """The text ``/backend`` renders with no arguments.

    Marks the running backend so the listing answers "which am I on?" and
    "what else is there?" in one screen.
    """

    lines = []
    if active_spec:
        lines.append(f"Active backend: {active_spec}")
    for choice in CHOICES:
        marker = (
            "* "
            if active_spec and active_spec.startswith(f"{choice.provider}/")
            else "  "
        )
        default = f"{choice.provider}/{choice.default_model}"
        configures = choice.credential_env or choice.endpoint_env or "nothing"
        lines.append(
            f"{marker}/backend {choice.provider} — {choice.summary} "
            f"Default {default}; reads {configures}."
        )
    lines.append(
        "  /backend <provider>/<model> selects a specific model, "
        "e.g. /backend ollama/llama3.1:8b."
    )
    return "\n".join(lines)


def spec_of(backend: Any) -> str:
    """A backend's ``provider/model`` spec, or an empty string if it has none.

    The shell is constructed with plain stand-ins in tests, so this never
    assumes the attribute is there.
    """

    return str(getattr(backend, "spec", "") or "")
