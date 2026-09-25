"""The five tool groups, and the annotations every served tool carries (C6).

**Groups** are a launch-time filter on one server, not five servers
(``docs/working/mcp-tool-surface.md`` §3.6). All 55 tools' schemas are ~14,800
tokens; a user who wants a quarter of that in their context serves one group.
A group is declared by the **tool modules** it covers, never by tool names:
a tool added to an existing module joins its group with no edit here, and a
tool in a new module belongs to no group until one names it -- which
``tests/test_mcp_surface.py`` catches, because the groups must partition the
registry exactly.

**Annotations** are derived, never restated:

- ``openWorldHint`` is ``TOOL_CLASSES[name] != "local"`` from
  ``tools/bench/plane.py`` (§3.7): a remote tool, and a mixed one whose
  arguments can take it remote, reach a service outside this machine.
- ``readOnlyHint`` is false for a tool whose schema has an argument that
  writes **outside** the artifact directory -- ``download`` (fetches archive
  products into the download root) or ``write_header`` (writes a solved WCS
  into the FITS file). Every tool writes artifacts; that is not what the hint
  is for.
- ``destructiveHint`` (meaningful only when not read-only) is true for
  ``write_header``, which modifies an existing file, and false for
  ``download``, which only adds files.

``tools.bench.plane`` is import-light by design -- it imports nothing from
``tools/agent/`` or ``tools/llm/`` -- so reading it keeps this package's
dependency direction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from tools.bench.plane import TOOL_CLASSES
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

__all__ = [
    "GROUPS",
    "TOOLS_ENV",
    "Group",
    "annotations_for",
    "group_of",
    "groups_from_environment",
    "parse_groups",
    "tools_in_groups",
]

#: Names groups to serve, comma-separated, when ``--tools`` is not given.
TOOLS_ENV = "KEPLER_MCP_TOOLS"


@dataclass(frozen=True)
class Group:
    name: str
    modules: tuple[str, ...]
    #: One line for ``--help`` and the startup log, ending with whether the
    #: group works with no optional data bundle installed (§3.5, §3.6).
    description: str


GROUPS: tuple[Group, ...] = (
    Group(
        "databases",
        (
            "tools.resolve",
            "tools.simbad",
            "tools.ads",
            "tools.ned",
            "tools.vizier",
            "tools.atnf",
            "tools.mast",
            "tools.mpc",
            "tools.casda",
        ),
        "SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS and name resolution. "
        "Runs with no data bundle: remote services only.",
    ),
    Group(
        "optical",
        (
            "tools.optical",
            "tools.astrometry",
            "tools.wcs",
            "tools.photometry",
            "tools.catalogs",
            "tools.calibration",
            "tools.workspace",
            "tools.fieldcal_reference",
        ),
        "Optical frames, WCS and plate solving, photometry, zero points, catalogs, "
        "artifacts. Partly without a bundle: the recorded zero-point references are "
        "core; the frame library, and so photometry and the end-to-end calibration "
        "replay, is the optional optical bundle.",
    ),
    Group(
        "timeseries",
        ("tools.pulsar", "tools.variable_star"),
        "The pulsar chain and the variable-star chain. Runs with no data bundle: "
        "the five pulsar scans are core.",
    ),
    Group(
        "hr",
        ("tools.hr_diagram",),
        "Both HR-diagram entry points. Partly without a bundle: the catalog-only "
        "path needs no local data; the isochrone fit needs the isochrone grid.",
    ),
    Group(
        "radio",
        ("tools.radio_sources",),
        "Radio SED fitting and source identification. Partly without a bundle: "
        "a radio FITS map must be local; the catalogs are remote.",
    ),
)

_BY_NAME = {group.name: group for group in GROUPS}

#: Schema arguments that make a call write outside the artifact directory,
#: and whether that write modifies an existing file.
_WRITES_OUTSIDE_ARTIFACTS = {"download": False, "write_header": True}


def group_of(
    name: str, functions: Mapping[str, Callable[..., Any]] = TOOL_FUNCTIONS
) -> str | None:
    """The group a registered tool belongs to, by its module; ``None`` if none."""

    module = functions[name].__module__
    for group in GROUPS:
        if module in group.modules:
            return group.name
    return None


def parse_groups(value: str | None) -> tuple[str, ...] | None:
    """``"databases, hr"`` -> ``("databases", "hr")``; empty or ``None`` -> all.

    Raises ``ValueError`` naming the valid groups on an unknown one, so a typo
    in a host's configuration fails at startup rather than serving nothing.
    """

    if value is None or not value.strip():
        return None
    names = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    unknown = [name for name in names if name not in _BY_NAME]
    if unknown:
        raise ValueError(
            f"unknown tool group(s) {', '.join(unknown)}; "
            f"choose from {', '.join(_BY_NAME)}"
        )
    return names


def tools_in_groups(
    groups: Iterable[str] | None,
    schemas: Sequence[Mapping[str, Any]] = TOOL_SCHEMAS,
    functions: Mapping[str, Callable[..., Any]] = TOOL_FUNCTIONS,
) -> list[Mapping[str, Any]]:
    """The registry schemas in ``groups``, in registry order; all of them for ``None``."""

    if groups is None:
        return list(schemas)
    wanted = set(groups)
    return [s for s in schemas if group_of(s["name"], functions) in wanted]


def groups_from_environment(environ: Mapping[str, str] | None = None) -> tuple[str, ...] | None:
    environ = os.environ if environ is None else environ
    return parse_groups(environ.get(TOOLS_ENV))


def annotations_for(schema: Mapping[str, Any]) -> dict[str, bool]:
    """``{read_only_hint, open_world_hint[, destructive_hint]}`` for one tool.

    ``destructive_hint`` is given only for a tool that is not read-only; the
    protocol defines it for no other, and it costs every tool's listing bytes.
    """

    properties = set((schema.get("input_schema") or {}).get("properties") or {})
    writes = properties & set(_WRITES_OUTSIDE_ARTIFACTS)
    hints = {
        "read_only_hint": not writes,
        "open_world_hint": TOOL_CLASSES[schema["name"]] != "local",
    }
    if writes:
        hints["destructive_hint"] = any(_WRITES_OUTSIDE_ARTIFACTS[arg] for arg in writes)
    return hints
