"""The Kepler agent skill: one source, rendered to every surface that carries it.

The skill teaches a model that is *not* running inside Kepler's own agent loop
which tool to reach for, in what order, and which results are silently wrong.
``tools/agent/prompt.py`` is the authority for every rule it restates; the
skill cites that prompt by section name, and
``tests/test_skill_invariants.py`` fails if the load-bearing rules drift
between the two.

``source/`` is the **only** hand-edited copy (``docs/working/mcp-tool-surface.md``
§3.4: copies are forbidden). It lives inside the ``tools`` package so that it
ships with an installed Kepler, where there is no checkout to read it from.
Every other surface is rendered from it:

- ``skills/kepler-tools/`` in the repository, for a coding agent working in a
  checkout and for a human reading it -- ``python -m tools.skill`` writes it,
  ``python -m tools.skill --check`` reports drift, and a test runs the check;
- the MCP server's instructions and resources (phase C5), which will read
  :func:`source_documents` rather than the repository copy.

The rendered copy differs from the source only by the ``SKILL.md`` frontmatter
a skill loader reads and a banner naming the source. The source carries
neither, because the served instructions need neither.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "REPOSITORY_COPY",
    "SKILL_DESCRIPTION",
    "SKILL_NAME",
    "SOURCE_DIR",
    "check_repository_copy",
    "render_repository_copy",
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
