"""Resolve and pin the artifact and data roots before anything reads them.

``tools.config`` resolves ``ARTIFACT_DIR`` and ``DATA_DIR`` **at import**, and
several tool modules copy the value out at their own import
(``from tools.config import ARTIFACT_DIR``). Reassigning either afterwards
moves nothing. So the server decides both roots first, writes them into the
environment as absolute paths, and only then imports the registry -- which is
why this module imports nothing from ``tools`` but :mod:`tools.paths` (which
resolves nothing at import) and repeats the two variable names rather than
reading them from ``tools.config``. A test asserts they match.

**The artifact root defaults to a per-user directory, not the launch
directory** (``docs/working/mcp-tool-surface.md`` §3.2, decided in C3).
``tools.config``'s own default is ``artifacts/`` beside the process's working
directory, and a host launches a server wherever it likes: the user's project,
their home directory, or a directory they cannot write. Defaulting there would
put an untracked ``artifacts/`` into the user's repository unasked, or fail on
the first write. A fixed per-user directory is the same place every session,
the server logs it at startup, and ``KEPLER_ARTIFACT_DIR`` still wins for a
user who wants artifacts beside their project.

``KEPLER_DATA_DIR`` already defaults to a package-anchored path, so pinning it
only makes the resolved value explicit in the environment and in the log.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping

from tools.paths import BUNDLED_DATA_LINK, kepler_home

__all__ = [
    "ARTIFACT_DIR_ENV",
    "DATA_DIR_ENV",
    "PinnedRoots",
    "default_data_dir",
    "pin_roots",
    "user_artifact_dir",
]

ARTIFACT_DIR_ENV = "KEPLER_ARTIFACT_DIR"
DATA_DIR_ENV = "KEPLER_DATA_DIR"


@dataclass(frozen=True)
class PinnedRoots:
    """The two roots the server pinned, and where each value came from."""

    artifact_dir: Path
    artifact_source: str
    data_dir: Path
    data_source: str


def user_artifact_dir(
    environ: MutableMapping[str, str] | None = None,
    *,
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """The per-user artifact directory: ``<kepler home>/artifacts``.

    ``~/.local/share/kepler/artifacts`` on Linux (``$XDG_DATA_HOME`` honoured),
    ``~/Library/Application Support/kepler/artifacts`` on macOS,
    ``%LOCALAPPDATA%\\kepler\\artifacts`` on Windows; ``KEPLER_HOME`` moves
    all of them. See :func:`tools.paths.kepler_home`.
    """

    return kepler_home(environ, platform=platform, home=home) / "artifacts"


def default_data_dir() -> Path:
    """``tools.config``'s own ``DATA_DIR`` default: the bundled data root.

    The repository's ``data/`` in a checkout, the shipped core data in an
    installed wheel (:data:`tools.paths.BUNDLED_DATA_LINK`).
    """

    return BUNDLED_DATA_LINK.resolve()


def _from_environment(environ: MutableMapping[str, str], name: str) -> Path | None:
    value = environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def pin_roots(environ: MutableMapping[str, str] | None = None) -> PinnedRoots:
    """Resolve both roots, write them back into ``environ``, and report them.

    An explicit, non-empty variable wins and is only made absolute; an unset
    or empty one takes the default. The artifact directory is created, so a
    root the user cannot write fails here, at startup, with the path in the
    message -- not on the first tool call that tries to save a table.

    Call this before ``tools.config`` is imported, or the tools will not see
    the pinned values; ``tools.mcp.__main__`` enforces that ordering.
    """

    environ = os.environ if environ is None else environ

    artifact_dir = _from_environment(environ, ARTIFACT_DIR_ENV)
    if artifact_dir is None:
        artifact_dir, artifact_source = user_artifact_dir(environ), "per-user default"
    else:
        artifact_source = ARTIFACT_DIR_ENV
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    data_dir = _from_environment(environ, DATA_DIR_ENV)
    if data_dir is None:
        data_dir, data_source = default_data_dir(), "package default"
    else:
        data_source = DATA_DIR_ENV
    data_dir = data_dir.resolve()

    environ[ARTIFACT_DIR_ENV] = str(artifact_dir)
    environ[DATA_DIR_ENV] = str(data_dir)
    return PinnedRoots(artifact_dir, artifact_source, data_dir, data_source)
