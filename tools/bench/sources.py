"""Mechanical sources for an answer key's expected value.

``docs/working/benchmark.md`` section 7.1 names three kinds of right answer --
ground truth, fidelity, correct negative -- and every one of them is
*determinable without consulting a model*. This module is where that stops
being an aspiration and becomes a load-time requirement.

A ``must_report_value`` check used to carry a hand-typed ``expected: 4127``.
That literal is a transcription of something, and a transcription can drift
from what it transcribed without anything failing: the fixture is edited, the
key is not, and the suite now grades a number no tool will ever return. Worse,
nothing recorded *what* it was a transcription of, so a reader could not tell a
measured value from a value someone liked the look of after watching a model
answer.

So a value check names its source instead, and the loader resolves it:

``fixture``
    A field of a recorded fixture response -- the archive's own answer, for a
    class-R tool that is always replayed. Resolved at load time.
``dataset``
    A field of a repository data file -- a curated literature period, a
    recorded zero-point solve. Independent ground truth that predates the
    benchmark and is not written by it. Resolved at load time, and confined to
    the **repository's own** ``data/`` tree: pinned like ``tools.wcs``'s
    fixture guard rather than following ``KEPLER_DATA_DIR``, because an answer
    key that moved with an operator's environment variable would not be a
    fixed reference at all.
``tool_result``
    A field a deterministic Kepler tool returned *in the session being
    graded* -- the fidelity case. Resolved at grade time, because the value is
    whatever the tool computed on the run.

``tool_result`` is not circular, and the distinction is worth stating plainly
because it is the whole argument for the module. It reads the return value of
repository code whose behaviour is pinned by the preservation suite, not the
model's prose. The model chooses which arguments to pass -- that is graded on
the trajectory axis -- but it cannot change what the tool computes from them.
Weighing an answer against a tool's output is fidelity; weighing it against
another model's output would be an opinion poll, and nothing here does that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "SOURCE_KINDS",
    "SourceError",
    "load_source",
    "resolve_static",
    "describe",
]


class SourceError(Exception):
    """A value source that does not name a resolvable mechanical value."""


#: The three kinds, and the keys each one requires beyond ``kind``.
SOURCE_KINDS: Mapping[str, frozenset[str]] = {
    "fixture": frozenset({"entry", "path"}),
    "dataset": frozenset({"path"}),
    "tool_result": frozenset({"field"}),
}

_OPTIONAL: Mapping[str, frozenset[str]] = {
    "fixture": frozenset(),
    "dataset": frozenset({"file"}),
    "tool_result": frozenset(),
}


def load_source(spec: Any, *, where: str) -> dict[str, Any]:
    """Validate a ``source:`` block's shape. Resolution happens later."""

    if not isinstance(spec, Mapping):
        raise SourceError(
            f"{where} source must be a mapping naming one of "
            f"{sorted(SOURCE_KINDS)}, got {type(spec).__name__}"
        )
    named = [kind for kind in SOURCE_KINDS if kind in spec]
    if len(named) != 1:
        raise SourceError(
            f"{where} source must name exactly one of {sorted(SOURCE_KINDS)}; "
            f"found {sorted(named) or 'none'}"
        )
    kind = named[0]
    required = SOURCE_KINDS[kind]
    allowed = {kind} | required | _OPTIONAL[kind]
    unknown = set(spec) - allowed
    if unknown:
        raise SourceError(
            f"{where} source ({kind}) has unknown key(s) {sorted(unknown)}; "
            f"allowed are {sorted(allowed)}"
        )
    missing = sorted(required - set(spec))
    if missing:
        raise SourceError(f"{where} source ({kind}) is missing {missing}")

    loaded = {"kind": kind, "name": str(spec[kind])}
    for key in required | _OPTIONAL[kind]:
        if key in spec:
            loaded[key] = str(spec[key])
    return loaded


def describe(source: Mapping[str, Any]) -> str:
    """A one-line human-readable citation, for the report and failure text."""

    kind = source["kind"]
    if kind == "fixture":
        return f"fixture {source['name']}[{source['entry']}].{source['path']}"
    if kind == "dataset":
        file = source.get("file")
        target = f"{source['name']}/{file}" if file else source["name"]
        return f"dataset {target}:{source['path']}"
    return f"{source['name']}.{source['field']} as returned this session"


def _walk(payload: Any, path: str, *, where: str, origin: str) -> Any:
    """Follow a dotted path. An integer segment indexes a sequence."""

    current = payload
    for segment in path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                raise SourceError(
                    f"{where} source path {path!r} has no {segment!r} in "
                    f"{origin} (keys: {sorted(current)[:12]})"
                )
            current = current[segment]
            continue
        if isinstance(current, (list, tuple)):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError) as exc:
                raise SourceError(
                    f"{where} source path {path!r}: {segment!r} does not index "
                    f"a {len(current)}-element sequence in {origin}"
                ) from exc
            continue
        raise SourceError(
            f"{where} source path {path!r} ran past a leaf value in {origin}"
        )
    return current


def _as_number(value: Any, *, where: str, origin: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SourceError(
            f"{where} source resolved to {value!r} in {origin}, which is not a "
            "number. A value check compares numbers; point it at the field "
            "that holds one."
        )
    return float(value)


def resolve_static(
    source: Mapping[str, Any],
    *,
    fixture_root: str | Path,
    data_root: str | Path | None = None,
    where: str,
) -> float:
    """Resolve a ``fixture`` or ``dataset`` source to its number.

    ``tool_result`` is not resolvable here by construction -- it has no value
    until a session has run -- and asking for one is a programming error
    rather than a corpus error.
    """

    kind = source["kind"]
    if kind == "tool_result":
        raise SourceError(
            f"{where} source is a tool_result; it resolves against a graded "
            "session, not the corpus"
        )
    if kind == "fixture":
        return _resolve_fixture(source, fixture_root=fixture_root, where=where)
    return _resolve_dataset(source, data_root=data_root, where=where)


def _resolve_fixture(
    source: Mapping[str, Any], *, fixture_root: str | Path, where: str
) -> float:
    import yaml

    from tools.bench.fixtures import resolve_fixture_path

    path = resolve_fixture_path(source["name"], Path(fixture_root))
    try:
        # S5: safe_load only, for the same reason the fixture store uses it.
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceError(f"{where} fixture {path} is not readable YAML: {exc}") from exc
    entries = payload.get("entries") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        raise SourceError(f"{where} fixture {path} has no entries list")
    wanted = source["entry"]
    for entry in entries:
        if isinstance(entry, Mapping) and str(entry.get("id")) == wanted:
            value = _walk(
                entry, source["path"], where=where, origin=f"{path} entry {wanted!r}"
            )
            return _as_number(value, where=where, origin=f"{path} entry {wanted!r}")
    known = [str(e.get("id")) for e in entries if isinstance(e, Mapping)]
    raise SourceError(
        f"{where} fixture {path} has no entry {wanted!r} (entries: {known})"
    )


#: The repository's own data tree. Deliberately **not** ``tools.config.DATA_DIR``:
#: that one is an operator setting, and a ground-truth reference that moves when
#: an operator repoints a directory is not ground truth. ``tools/wcs.py`` pins
#: its fixture-subtree guard to the repository for the same reason.
REPO_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def _resolve_dataset(
    source: Mapping[str, Any], *, data_root: str | Path | None, where: str
) -> float:
    from tools.config import safe_resolve, within

    root = safe_resolve(Path(data_root) if data_root is not None else REPO_DATA_ROOT)
    relative = source["name"]
    if source.get("file"):
        relative = f"{relative}/{source['file']}"
    target = safe_resolve(root / relative)
    # The corpus is data, and a data file naming an absolute path or climbing
    # out of the data root would read whatever it liked at load time. The tool
    # layer decides this on the resolved path for the same reason (S7).
    if not within(target, root):
        raise SourceError(
            f"{where} dataset {relative!r} resolves outside the data root"
        )
    if not target.is_file():
        raise SourceError(f"{where} dataset {target} does not exist")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceError(f"{where} dataset {target} is not readable JSON: {exc}") from exc
    value = _walk(payload, source["path"], where=where, origin=str(target))
    return _as_number(value, where=where, origin=str(target))
