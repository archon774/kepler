"""The Kepler agent skill: one source, rendered to every surface that carries it.

The skill teaches a model that is *not* running inside Kepler's own agent loop
which tool to reach for, in what order, and which results are silently wrong.
``tools/agent/prompt.py`` is the authority for every rule it restates; the
skill cites that prompt by section name, and
``tests/test_skill_invariants.py`` fails if the load-bearing rules drift
between the two.

``source/`` is the **only** hand-edited copy (``docs/archive/mcp-tool-surface.md``
§3.4: copies are forbidden). It lives inside the ``tools`` package so that it
ships with an installed Kepler, where there is no checkout to read it from.
Every other surface is rendered from it:

- ``skills/kepler-tools/`` in the repository, for a coding agent working in a
  checkout and for a human reading it -- ``python -m tools.skill`` writes it,
  ``python -m tools.skill --check`` reports drift, and a test runs the check;
- the MCP server (phase C5): :func:`served_brief` is its instructions and
  :func:`served_documents` its resources.

The rendered copy differs from the source only by the ``SKILL.md`` frontmatter
a skill loader reads and a banner naming the source. The source carries
neither, because the served instructions need neither.

**Why the served instructions are a brief, not ``SKILL.md``.** Measured in C5:
Claude Code truncates a server's instructions at about 2,000 characters and
marks the cut ``… [truncated]``; everything after it never reaches the model.
``SKILL.md`` is ~12 KB. So ``BRIEF.md`` -- hand-written, part of this one
source, and held under :data:`BRIEF_LIMIT` by a test together with the install
facts the server appends -- is what is always delivered, and it tells the
model to read ``SKILL.md`` and the references, which the server publishes as
resources. The pulsar tools' own descriptions carry measure-first as well, so
that rule does not depend on either.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "BRIEF_LIMIT",
    "REPOSITORY_COPY",
    "SERVED_URI_PREFIX",
    "SKILL_DESCRIPTION",
    "SKILL_NAME",
    "SOURCE_DIR",
    "check_repository_copy",
    "render_repository_copy",
    "served_brief",
    "served_documents",
    "source_documents",
    "write_repository_copy",
]

SKILL_NAME = "kepler-tools"

#: What a skill loader shows a model when deciding whether to load the skill.
SKILL_DESCRIPTION = (
    "How to use Kepler's astronomy tools correctly -- SIMBAD, NED, VizieR, ATNF, "
    "MAST, MPC, CASDA and ADS queries, and the local pulsar, variable-star, "
    "optical photometry, plate-solving, HR-diagram and radio-source pipelines. "
    "Use when calling any Kepler tool, and before any pulsar period "
    "measurement, database name lookup or literature claim -- it covers the "
    "stage orders, identifier forms and silently wrong results the tool "
    "descriptions alone do not."
)

SOURCE_DIR = Path(__file__).resolve().parent / "source"

#: The rendered copy in a checkout. It does not exist in an installed Kepler.
REPOSITORY_COPY = Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME

_ENTRY = "SKILL.md"
_BRIEF = "BRIEF.md"

#: Resource URIs of the served documents are this prefix plus their source path.
SERVED_URI_PREFIX = "kepler://skill/"

#: Source documents the server does not publish: how to call the tools as
#: Python functions from a checkout, which a user of the server never does.
_NOT_SERVED = frozenset({"references/checkout.md"})

#: The most characters of instructions a host is known to deliver whole
#: (Claude Code, measured in C5), with margin. Brief plus install facts.
BRIEF_LIMIT = 1_900


def source_documents() -> dict[str, str]:
    """Every source document, keyed by its path relative to ``source/``.

    Keys use ``/`` on every platform; the entry document is ``"SKILL.md"``.
    """
    return {
        path.relative_to(SOURCE_DIR).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(SOURCE_DIR.rglob("*.md"))
    }


def _banner(name: str) -> str:
    return (
        f"<!-- Rendered from tools/skill/source/{name} by `python -m tools.skill`."
        " Edit the source, not this file. -->\n\n"
    )


def render_repository_copy() -> dict[str, str]:
    """The ``skills/kepler-tools/`` files, keyed like :func:`source_documents`."""
    rendered = {}
    for name, text in source_documents().items():
        body = _banner(name) + text
        if name == _ENTRY:
            body = (
                "---\n"
                f"name: {SKILL_NAME}\n"
                f"description: {SKILL_DESCRIPTION}\n"
                "---\n\n" + body
            )
        rendered[name] = body
    return rendered


def _served_text(text: str, names: frozenset[str]) -> str:
    """Point every mention of a served document at its resource URI.

    Drops the table rows that link a document the server does not publish.
    """

    lines = [
        line
        for line in text.splitlines(keepends=True)
        if not (line.startswith("|") and any(name in line for name in _NOT_SERVED))
    ]
    pattern = re.compile(
        r"(?<![\w/:])("
        + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        + ")"
    )
    return pattern.sub(lambda match: SERVED_URI_PREFIX + match.group(1), "".join(lines))


def served_documents() -> dict[str, str]:
    """The documents the MCP server publishes as resources, keyed like the source.

    Everything but the brief (which is the instructions) and the checkout
    reference, with relative links rewritten to ``kepler://skill/...`` URIs.
    """

    sources = source_documents()
    names = frozenset(sources) - _NOT_SERVED - {_BRIEF}
    return {name: _served_text(sources[name], names) for name in sorted(names)}


def served_brief() -> str:
    """The always-delivered instructions: ``BRIEF.md``, links as resource URIs."""

    sources = source_documents()
    names = frozenset(sources) - _NOT_SERVED - {_BRIEF}
    return _served_text(sources[_BRIEF], names).strip()


def check_repository_copy(target: Path = REPOSITORY_COPY) -> list[str]:
    """Paths under ``target`` that differ from a fresh render, sorted.

    A missing file, a stale one and an extra ``.md`` file the source no longer
    has are all drift. An empty list means the copy is current.
    """
    rendered = render_repository_copy()
    present = (
        {p.relative_to(target).as_posix() for p in target.rglob("*.md")}
        if target.is_dir()
        else set()
    )
    drift = present - rendered.keys()
    for name, text in rendered.items():
        path = target / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            drift.add(name)
    return sorted(drift)


def write_repository_copy(target: Path = REPOSITORY_COPY) -> list[str]:
    """Render into ``target``, removing any ``.md`` the source no longer has.

    Returns the paths written or removed, sorted.
    """
    changed = check_repository_copy(target)
    rendered = render_repository_copy()
    for name in changed:
        path = target / name
        if name in rendered:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered[name], encoding="utf-8")
        else:
            path.unlink()
    return changed
