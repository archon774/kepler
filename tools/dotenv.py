"""Load a checkout's ``.env`` into the environment, before anything reads it.

Kept apart from ``tools.config``, which resolves its settings **at import**.
An entry point that loaded ``.env`` through ``tools.config`` had already
fixed every import-time setting -- the artifact and data roots, the isochrone
directory, preview rows, frame caps, the MCP tool groups -- from the
environment *without* the file. The values were loaded, logged as read, and
ignored. Importing this module resolves nothing, so ``kepler-mcp`` and the
console can load ``.env`` first. ``tools.config`` re-exports all of it.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["DOTENV_PATH", "load_dotenv"]

#: The repository-local credential file. Untracked and gitignored; it holds a
#: developer's own provider keys and never ships.
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"

#: Bare-line fallback for :func:`load_dotenv`. A ``.env`` written by hand often
#: holds nothing but the key itself, with no variable name in front of it; a
#: prefix long enough to identify one provider unambiguously tells us which
#: variable it was meant to be. Only prefixes that are provider-issued and
#: self-identifying belong here -- an OpenAI ``sk-`` is not, because several
#: services mint keys with it.
_BARE_KEY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("sk-ant-", "ANTHROPIC_API_KEY"),
)


def load_dotenv(
    path: str | Path | None = None, *, environ: dict[str, str] | None = None
) -> tuple[str, ...]:
    """Merge ``KEY=value`` lines from a ``.env`` file into the environment.

    Returns the variable names this call set, in file order, so a caller can
    report what it picked up without ever handling the values.

    **The real environment always wins.** A variable already set is left
    alone, so ``ANTHROPIC_API_KEY=... uv run kepler`` still overrides the file
    and a test's ``monkeypatch.setenv`` is not silently undone. A missing or
    unreadable file is not an error -- the file is optional by construction.

    Accepted syntax is the intersection every ``.env`` writer agrees on:
    blank lines and ``#`` comments are skipped, a leading ``export`` is
    dropped, names are stripped, and a value wrapped in matching single or
    double quotes is unwrapped. Nothing is interpolated: ``$HOME`` stays four
    characters, because a credential is not a shell word.

    A line carrying no ``=`` is read through :data:`_BARE_KEY_PREFIXES` and
    assigned to the variable its prefix names. Anything else on such a line is
    ignored rather than guessed at.
    """

    target = os.environ if environ is None else environ
    source = Path(path) if path is not None else DOTENV_PATH
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()

    loaded: list[str] = []
    for line in text.splitlines():
        name, value = _parse_dotenv_line(line)
        if name is None or value is None:
            continue
        # The environment beats the file; an empty existing value does not
        # count as set, matching env_value's own notion of "unset".
        if target.get(name):
            continue
        target[name] = value
        loaded.append(name)
    return tuple(loaded)


def _parse_dotenv_line(line: str) -> tuple[str | None, str | None]:
    """One ``.env`` line as a ``(name, value)`` pair, or ``(None, None)``."""

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None, None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()

    if "=" not in stripped:
        for prefix, name in _BARE_KEY_PREFIXES:
            if stripped.startswith(prefix):
                return name, stripped
        return None, None

    name, _, value = stripped.partition("=")
    name = name.strip()
    if not name:
        return None, None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return name, value
