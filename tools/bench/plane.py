"""The tool plane: which of Kepler's 55 registered tools run live in a
benchmark, which are replayed from fixtures, and how a call decides.

``docs/working/benchmark.md`` section 3. Kepler's tools are not one surface,
they are three:

* **Class L** -- local and deterministic. They read the bundled fixture tree
  and compute. Run **live**, because replaying ``compute_pulsar_periodogram``
  would mean hand-authoring what the periodogram returns for a period the
  model chose, which lets the task author rather than the data decide whether
  the model's mistake is visible. The flat profile, the 60 Hz mains artifact
  at 0.016665 s and the 2.1--2.2 s red-noise peak are real outputs of real
  code over real scans, free and deterministic.
* **Class R** -- remote. Every one opens a socket, so none is ever executed by
  the harness in ``run`` mode; each is replayed from a recorded fixture.
* **Class M** -- mixed: local code behind a network-capable argument. A task
  must pin the offline path in the *call's arguments*, or the tool is
  replayed. This is the one place the plane is argument-sensitive, and it is
  deliberate: whether the model chose the offline path is itself a graded
  behaviour.

**The plane is closed** (B1). :data:`TOOL_CLASSES` covers every name in
``TOOL_FUNCTIONS``, a test asserts it, and adding a registry tool without
classifying it is a test failure rather than a default. The registry went from
49 tools to 55 in four days while the model port was being written; without
this, the first new remote tool added after the harness lands would run live,
against a real service, inside a benchmark run that believes it is offline --
silently, with the resulting latency and failure folded into someone's
scoreboard.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Mapping

__all__ = [
    "ToolClass",
    "TOOL_CLASSES",
    "OFFLINE_PREDICATES",
    "DEFAULT_BLOCKED",
    "classify_call",
    "build_tool_plane",
    "ReplayShim",
]

#: ``"local"`` runs live; ``"remote"`` is always replayed; ``"mixed"`` runs
#: live only when the call's arguments satisfy the tool's offline predicate.
ToolClass = str

# ---------------------------------------------------------------------------
# The classification. Per *tool*, never per module: ``get_literature_cluster_params``
# looks local -- it returns Cantat-Gaudin & Anders (2020) parameters -- but
# ``algorithms/hrdiagram_py/literature.py`` fetches them through
# ``search_vizier(catalog="J/A+A/640/A1/table1")``, and a per-module guess
# would have put it beside ``extract_photometry_from_fits`` and opened a
# socket. ``tools.hr_diagram`` alone spans all three classes.
# ---------------------------------------------------------------------------

TOOL_CLASSES: Mapping[str, ToolClass] = {
    # --- class L: local, deterministic, run live (26) ---------------------
    # tools.pulsar -- the whole radio-pulsar chain, over the five bundled
    # scans. No fixtures at all, and the richest suite on this surface.
    "list_pulsar_scans": "local",
    "resolve_pulsar_scan": "local",
    "load_pulsar_lightcurve": "local",
    "compute_pulsar_periodogram": "local",
    "fold_pulsar_lightcurve": "local",
    "plot_pulsar": "local",
    "sonify_pulsar": "local",
    # tools.variable_star
    "list_variable_star_fixtures": "local",
    "resolve_variable_star_fixture": "local",
    "load_variable_star_lightcurve": "local",
    "compute_variable_star_periodogram": "local",
    "fold_variable_star_lightcurve": "local",
    # tools.optical -- header reads over the bundled frame library.
    "list_optical_frames": "local",
    "resolve_optical_frame": "local",
    # tools.astrometry
    "describe_image_wcs": "local",
    # tools.fieldcal_reference -- the recorded Skynet solves and the tools
    # that grade against them. compare_zeropoint_to_reference is where the
    # corpus's strongest answer keys come from (7.1.3).
    "list_zeropoint_references": "local",
    "load_zeropoint_reference": "local",
    "replay_field_calibration": "local",
    "compare_zeropoint_to_reference": "local",
    # tools.catalogs -- declaration only; nothing here opens a socket.
    "list_photometric_catalogs": "local",
    "resolve_reference_band": "local",
    # tools.calibration
    "solve_zeropoint_from_measurements": "local",
    # tools.workspace
    "list_artifacts": "local",
    "describe_artifact": "local",
    # tools.photometry -- an inventory of filenames, never capped.
    "list_photometry_targets": "local",
    # tools.hr_diagram
    "extract_photometry_from_fits": "local",
    # --- class R: remote, replayed from fixtures (22) ---------------------
    "search_simbad": "remote",
    "search_simbad_measurements": "remote",
    "search_simbad_bibliography": "remote",
    "get_paper_abstract": "remote",
    "search_ads": "remote",
    "get_citing_papers": "remote",
    "get_referenced_papers": "remote",
    "build_literature_review": "remote",
    "list_vizier_catalogs": "remote",
    "search_vizier": "remote",
    "search_ned": "remote",
    "search_atnf": "remote",
    "search_mast": "remote",
    "search_mpc": "remote",
    "search_casda": "remote",
    "resolve_target": "remote",
    "plot_field_sed": "remote",
    "identify_radio_sources": "remote",
    "analyze_source_spectrum": "remote",
    "crossmatch_gaia": "remote",
    "crossmatch_gaia_by_position": "remote",
    # Local-looking, remote in fact -- see the module docstring above.
    "get_literature_cluster_params": "remote",
    # --- class M: local code behind a network-capable argument (7) --------
    "run_photometry_on_target": "mixed",
    "calibrate_zeropoint": "mixed",
    "solve_astrometry": "mixed",
    # Always-local code whose *input* is a CSV a class-R crossmatch produced.
    # Class L in practice; classified mixed so the pairing stays visible and
    # a task cannot reach them without the replayed input they consume.
    "select_cluster_members": "mixed",
    "fit_and_compare_hr_diagram": "mixed",
    # Each wraps a Gaia crossmatch; there is no offline path, so the
    # predicate is never satisfied and they are always replayed.
    "run_full_hr_pipeline": "mixed",
    "run_full_hr_pipeline_from_catalog": "mixed",
}

#: Tools blocked unless a run opts them in with ``--enable <tool>``.
#: ``solve_astrometry`` needs astrometry.net indices or an ATLAS catalog tree
#: that are not in this repository, the packaged 4107-4119 indices do not
#: solve the bundled fixtures, and an all-sky solve is ~285 s. An operator
#: asset is not something a benchmark reaches for by default.
DEFAULT_BLOCKED: frozenset[str] = frozenset({"solve_astrometry"})


def _pinned_offline_photometry(arguments: Mapping[str, Any]) -> bool:
    """``run_photometry_on_target`` skips the network catalog solve only when
    the model passes ``use_field_cal=false`` explicitly.

    The default is ``true``, so an omitted argument is the *online* path --
    and choosing to turn it off is itself a graded behaviour: the field-cal
    solve costs 30-90 s of network time, and the system prompt tells the model
    to skip it when the user only wants source counts.
    """

    return arguments.get("use_field_cal") is False


def _pinned_offline_zeropoint(arguments: Mapping[str, Any]) -> bool:
    """``calibrate_zeropoint`` solves offline only with ``catalog_fixture``
    *and* ``compare_to`` together.

    The tool's own schema says so -- ``catalog_fixture``'s description reads
    "the solve named by compare_to (required with this)" -- and the two enum
    values are the schema's, not this module's. ``test_bench_plane`` asserts
    this predicate against ``registry.py`` rather than restating the rule in
    prose, so the predicate cannot quietly go stale if the contract in
    ``tools/photometry.py`` changes (section 17 question 1).
    """

    fixture = arguments.get("catalog_fixture")
    return isinstance(fixture, str) and bool(arguments.get("compare_to"))


def _always_local(arguments: Mapping[str, Any]) -> bool:
    """``select_cluster_members`` and ``fit_and_compare_hr_diagram`` compute
    from a CSV already on disk and never query anything themselves."""

    return True


def _never_local(arguments: Mapping[str, Any]) -> bool:
    """The two full-pipeline tools wrap a Gaia crossmatch; no argument makes
    them offline."""

    return False


#: Per-call predicates for class M. Every ``"mixed"`` entry in
#: :data:`TOOL_CLASSES` has one; a test asserts the two agree.
OFFLINE_PREDICATES: Mapping[str, Callable[[Mapping[str, Any]], bool]] = {
    "run_photometry_on_target": _pinned_offline_photometry,
    "calibrate_zeropoint": _pinned_offline_zeropoint,
    # Blocked by default, so the predicate is only consulted under --enable.
    # Live then needs the operator's own index tree; the harness does not
    # inspect the environment here -- it defers to the tool, which reports an
    # "unavailable" backend rather than guessing.
    "solve_astrometry": _always_local,
    "select_cluster_members": _always_local,
    "fit_and_compare_hr_diagram": _always_local,
    "run_full_hr_pipeline": _never_local,
    "run_full_hr_pipeline_from_catalog": _never_local,
}


def classify_call(
    name: str,
    arguments: Mapping[str, Any],
    *,
    blocked: frozenset[str] | None = None,
) -> str:
    """Resolve one call to ``"blocked"``, ``"replay"`` or ``"live"``.

    Resolution order, exactly as section 5.2 specifies: disabled by the run ->
    class R -> class M with the offline predicate satisfied -> class L ->
    class M unpinned. An unclassified name is impossible (B1) and raises
    rather than defaulting, because every default here is wrong: defaulting to
    live opens a socket mid-run, and defaulting to replay measures a fixture
    miss instead of the tool.
    """

    blocked = DEFAULT_BLOCKED if blocked is None else blocked
    if name in blocked:
        return "blocked"

    tool_class = TOOL_CLASSES.get(name)
    if tool_class is None:
        raise KeyError(
            f"{name!r} is a registered tool with no benchmark classification; "
            "add it to TOOL_CLASSES in the same commit that registers it "
            "(docs/working/benchmark.md B1)"
        )
    if tool_class == "remote":
        return "replay"
    if tool_class == "mixed":
        predicate = OFFLINE_PREDICATES[name]
        return "live" if predicate(arguments) else "replay"
    return "live"


class ReplayShim:
    """Stands in for one tool, dispatching per call.

    Built with :func:`functools.wraps` over the real function, so
    ``inspect.signature()`` follows ``__wrapped__`` to the real signature and
    S8's signature-based fallback keeps working exactly as it does in
    production. That is not a nicety: without it, ``list_pulsar_scans`` and
    the four other empty-``properties`` tools would stop faulting on junk
    arguments under replay, and the protocol grader would report a model as
    cleaner than it is.
    """

    def __init__(
        self,
        name: str,
        real: Callable[..., Any],
        *,
        replay: Callable[[str, Mapping[str, Any]], Any],
        blocked: frozenset[str],
    ) -> None:
        self.name = name
        self.real = real
        self._replay = replay
        self._blocked = blocked
        functools.update_wrapper(self, real)

    def __call__(self, **arguments: Any) -> Any:
        route = classify_call(self.name, arguments, blocked=self._blocked)
        if route == "blocked":
            return self._blocked_result()
        if route == "replay":
            return self._replay(self.name, arguments)
        return self.real(**arguments)

    def _blocked_result(self) -> Any:
        """A schema-valid error result of the tool's own return model.

        Built through the tool's declared return type rather than a bare dict,
        so the engine's ``.model_dump()`` works and the model sees the same
        shape a real failure would produce.
        """

        from tools.bench.fixtures import build_error_result

        return build_error_result(
            self.real,
            code="tool_disabled",
            message=(
                f"{self.name} is disabled for this benchmark run; enable it "
                "explicitly with --enable if the operator assets it needs are "
                "configured"
            ),
        )


def build_tool_plane(
    *,
    replay: Callable[[str, Mapping[str, Any]], Any],
    functions: Mapping[str, Callable[..., Any]] | None = None,
    blocked: frozenset[str] | None = None,
    enabled: frozenset[str] = frozenset(),
) -> dict[str, Callable[..., Any]]:
    """Build the ``{name: callable}`` mapping handed to
    ``run_session(tool_functions=...)``.

    The mapping covers **every name in ``TOOL_FUNCTIONS``**, not a subset.
    ``engine.py`` passes ``functions.get(call.name)`` into ``validate_tool_call``
    as the signature fallback for empty-``properties`` schemas, and a missing
    name would turn a schema-valid call into a spurious ``unknown_tool``
    fault -- inflating the protocol axis with the harness's own omission.

    ``enabled`` removes tools from ``blocked``; it is ``--enable`` on the CLI.
    """

    if functions is None:
        from tools.registry import TOOL_FUNCTIONS

        functions = TOOL_FUNCTIONS
    resolved_blocked = (
        DEFAULT_BLOCKED if blocked is None else blocked
    ) - enabled

    unclassified = set(functions) - set(TOOL_CLASSES)
    if unclassified:
        raise KeyError(
            f"registered tool(s) with no benchmark classification: "
            f"{sorted(unclassified)}; add them to TOOL_CLASSES in the same "
            "commit that registers them (docs/working/benchmark.md B1)"
        )

    return {
        name: ReplayShim(
            name, real, replay=replay, blocked=frozenset(resolved_blocked)
        )
        for name, real in functions.items()
    }
