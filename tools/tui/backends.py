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
    "ModelNotInstalled",
    "choice_for",
    "names",
    "offered_models",
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
        # `qwen3.8:27b-mlx`, not the `qwen3:8b` of model-backends.md's plan.
        # Phase 2b could not find `qwen3:8b` on the measurement host and
        # standardised on this one (`tests/test_llm_ollama_backend.py`'s
        # OLLAMA_REFERENCE_MODEL, and every `benchmark.md` sweep); the
        # README's `qwen3:8b` example is the stale plan value. A default
        # nobody has installed makes the bare `/backend ollama` fail for
        # everyone.
        provider="ollama",
        default_model="qwen3.8:27b-mlx",
        credential_env=None,
        endpoint_env="OLLAMA_BASE_URL",
        summary="A local Ollama daemon. No key; the daemon must be running.",
    ),
)


class UnknownBackendError(ValueError):
    """A bare name that is not one of :data:`CHOICES`."""


class ModelNotInstalled(BackendUnavailableError):
    """The service is up, but it does not hold the model the spec names.

    Its own subclass because the remedy is nothing like the others': no
    variable needs setting, and what the person needs is the list of models
    that *are* there. :func:`unavailable_message` renders that list.
    """

    def __init__(self, spec: str, model: str, installed: tuple[str, ...]) -> None:
        self.spec = spec
        self.model = model
        self.installed = installed
        super().__init__(
            "OLLAMA_BASE_URL", f"the daemon holds no model named {model!r}"
        )


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


def offered_models(provider: str) -> tuple[str, ...]:
    """The models this provider's host says it holds, newest first.

    ``()`` means "could not be asked" -- an unreachable daemon, or a provider
    with nothing to ask. It never means "holds nothing", and a caller must not
    turn it into a refusal: the answer to an unanswerable question is to carry
    on with the default, not to block the switch.

    Only Ollama answers today, because only Ollama publishes an inventory that
    needs no credential. Anthropic's model list is a decision about which
    models this console offers, and that is :data:`CHOICES`.
    """

    if provider != "ollama":
        return ()

    from tools.llm.ollama_backend import OllamaBackend

    choice = choice_for(provider)
    default = choice.default_model if choice else ""
    try:
        return OllamaBackend(model=default).installed_models()
    except Exception:
        # A listing is a convenience. Nothing about failing to get one should
        # be able to stop the switch the person actually asked for.
        return ()


def open_backend(
    spec: str,
    *,
    build: Callable[..., ModelBackend] = build_backend,
    thinking_budget: int | None = None,
) -> ModelBackend:
    """Build the backend named by ``spec`` and refuse to return a dead one.

    ``thinking_budget`` asks the provider to reveal its reasoning; it reaches
    the factory unexamined, because which providers take a budget is the
    factory's business and not this module's.

    ``.env`` is re-read first, so a key added to the file while the console is
    open takes effect on the next ``/backend`` without a restart. It never
    overrides a variable already set -- see :func:`tools.config.load_dotenv`.

    Raises :class:`~tools.llm.base.BackendUnavailableError` when the backend
    cannot be constructed *or* when it builds but its service does not answer.
    Both carry the variable to set, which is the only thing the caller renders.
    """

    load_dotenv()
    backend = build(spec, thinking_budget=thinking_budget)

    _require_service(backend, spec)
    _require_model(backend, spec)
    return backend


def _require_service(backend: ModelBackend, spec: str) -> None:
    """Refuse a backend whose service does not answer at all."""

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


def _require_model(backend: ModelBackend, spec: str) -> None:
    """Refuse a spec naming a model the (running) service does not hold.

    A daemon that is up is not a daemon that has your model. Ollama answers an
    unknown one with a 404 from the chat endpoint, which surfaces *mid-turn* as
    an ``httpx.HTTPStatusError`` on the user's first question -- the raw
    traceback ``docs/working/tui-harness.md`` section 11 says must never
    happen. Checking here moves it to the switch, where there is still another
    backend to stay on.

    An empty listing means "could not ask", not "has nothing", so it is never
    turned into a refusal.
    """

    listing = getattr(backend, "installed_models", None)
    if not callable(listing):
        return
    installed = tuple(listing())
    if not installed:
        return
    model = spec.partition("/")[2]
    if model and model not in installed:
        raise ModelNotInstalled(spec, model, installed)


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

    if isinstance(exc, ModelNotInstalled):
        # Naming the installed models is the whole remedy: there is no
        # variable to set, and guessing a substitute would silently answer a
        # different question than the one asked.
        available = ", ".join(exc.installed[:8])
        if len(exc.installed) > 8:
            available += f", and {len(exc.installed) - 8} more"
        text = (
            f"Cannot use {spec}: the service holds no model named "
            f"{exc.model!r}. Installed: {available}."
        )
    else:
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
