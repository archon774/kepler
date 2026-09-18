"""Record mode: capture live class-R results as reviewable fixture entries.

``docs/benchmarking/harness.md`` section 5.3 and requirement S2. ``record`` is
the fifth CLI verb and sits outside the run/grade/compare flow: it performs
**live** remote calls -- the only place in the harness that does -- and writes
fixture entries for a human to review before they are committed.

Three rules shape it, and each exists because a fixture is not test data:

* **S2: a capture made with credentials in the environment contains no
  substring of any of them.** Scanned over the serialized entry, and a hit
  refuses the write rather than redacting quietly -- a partially redacted
  capture is still a capture someone has to trust.
* **Responses only.** A request's arguments are recorded as the match
  predicates a reviewer will edit; headers, URLs and auth are never touched.
* **Third-party prose is flagged, never trusted.** Recorded ADS abstracts,
  VizieR catalog descriptions, SIMBAD notes and NED cells are arbitrary text
  from outside this repository, and a committed fixture is replayed into a
  model's context on every run. A string that reads like an instruction is
  surfaced for the reviewer, because one poisoned capture would corrupt the
  scoreboard permanently and invisibly.

The output is YAML for review, never a direct commit: the verb prints it and
writes it beside the fixture root only when asked, and the diff is reviewed as
adversarial input.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

__all__ = [
    "CredentialLeak",
    "CaptureReview",
    "CapturedEntry",
    "capture_entry",
    "credential_values",
    "scan_for_credentials",
    "flag_imperative_strings",
    "IMPERATIVE_PATTERNS",
]

#: Environment variables whose value must never reach a fixture. The explicit
#: names are the ones this repository documents; the suffix rule catches an
#: operator's own additions, which is the case an explicit list always misses.
_CREDENTIAL_NAMES: frozenset[str] = frozenset(
    {
        "ADS_DEV_KEY",
        "ANTHROPIC_API_KEY",
        "CASDA_OPAL_PASSWORD",
        "CASDA_OPAL_USERNAME",
        "GEMINI_API_KEY",
        "NASA_API_KEY",
        "OPENAI_API_KEY",
    }
)
_CREDENTIAL_SUFFIXES: tuple[str, ...] = (
    "_KEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_PASSWD",
    "_CREDENTIALS",
)

#: Below this length a value is not distinctive enough to search for: a
#: two-character key would match inside half the recorded prose and refuse
#: every capture. Real credentials are far longer; a short one is a
#: misconfiguration the scan cannot help with.
_MIN_CREDENTIAL_LENGTH = 8

#: Text that reads as an instruction aimed at whatever reads it. Not a security
#: boundary -- no recorded text ever reaches a model as a grader, because
#: nothing grades with a model -- but a reviewer's checklist, so a poisoned
#: catalog description is noticed while a human is still looking at the diff.
IMPERATIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "override attempt"),
    (r"disregard\s+(all\s+)?(previous|prior|the\s+above)", "override attempt"),
    (r"\byou\s+(are|must|should|will)\s+now\b", "role reassignment"),
    (r"system\s*(prompt|message)\s*[:=]", "prompt injection"),
    (r"<\s*/?\s*(system|instructions?|assistant)\s*>", "role markup"),
    (r"\bnew\s+instructions?\b", "instruction injection"),
    (r"\b(execute|run)\s+the\s+following\b", "execution request"),
    (r"\bapi[_\s-]?key\b", "credential solicitation"),
    (r"\bcurl\s+https?://", "exfiltration shape"),
)


class CredentialLeak(RuntimeError):
    """A capture contained a credential from the environment. S2.

    Never names the value, only the variable: an error message is written to a
    terminal, a log, and often a bug report.
    """

    def __init__(self, variables: Iterable[str]) -> None:
        self.variables = sorted(set(variables))
        super().__init__(
            "refusing to write a fixture: the captured response contains the "
            f"value of {', '.join(self.variables)}. A live capture records "
            "responses only; re-run the capture without that credential in the "
            "environment, or redact the service's echo of it by hand."
        )


@dataclass(frozen=True)
class CaptureReview:
    """One flagged string in a capture, for a human to look at."""

    where: str
    reason: str
    excerpt: str


@dataclass
class CapturedEntry:
    """A fixture entry awaiting review."""

    tool: str
    entry: dict[str, Any]
    reviews: list[CaptureReview] = field(default_factory=list)

    def to_yaml(self) -> str:
        """The entry as it would appear in a fixture file, plus any review
        notes as YAML comments above it."""

        header = [
            f"# Captured live from {self.tool}. Review before committing:",
            "# - are the match predicates loose enough for other models'",
            "#   spellings, and tight enough to answer only this call?",
            "# - is the recorded prose third-party text you are willing to",
            "#   replay into a model's context on every run?",
        ]
        for review in self.reviews:
            header.append(
                f"# FLAGGED ({review.reason}) at {review.where}: "
                f"{review.excerpt}"
            )
        body = yaml.safe_dump(
            [self.entry], sort_keys=False, allow_unicode=True, width=88
        )
        return "\n".join(header) + "\n" + body


def credential_values(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment values a capture must not contain, by variable name."""

    environ = os.environ if environ is None else environ
    found: dict[str, str] = {}
    for name, value in environ.items():
        if len(value) < _MIN_CREDENTIAL_LENGTH:
            continue
        if name in _CREDENTIAL_NAMES or name.upper().endswith(_CREDENTIAL_SUFFIXES):
            found[name] = value
    return found


def scan_for_credentials(
    text: str, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Variable names whose value appears anywhere in ``text``. S2.

    A plain substring search, deliberately: a service that echoes a key back
    in an error message ("invalid token: sk-...") does not base64 it first,
    and anything cleverer would have more ways to be wrong.
    """

    return [
        name
        for name, value in credential_values(environ).items()
        if value in text
    ]


def flag_imperative_strings(
    value: Any, *, where: str = "response"
) -> list[CaptureReview]:
    """Walk a captured response and flag text that reads like an instruction.

    Advisory. A fixture's recorded prose is replayed into a model's context on
    every run of every suite, so the moment to look at it is while a human is
    reviewing the diff -- not after a scoreboard has been quietly wrong for a
    month.
    """

    reviews: list[CaptureReview] = []
    if isinstance(value, str):
        for pattern, reason in IMPERATIVE_PATTERNS:
            match = re.search(pattern, value, re.IGNORECASE)
            if match:
                reviews.append(
                    CaptureReview(
                        where=where,
                        reason=reason,
                        excerpt=_excerpt(value, match.start()),
                    )
                )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            reviews.extend(flag_imperative_strings(item, where=f"{where}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reviews.extend(flag_imperative_strings(item, where=f"{where}[{index}]"))
    return reviews


def _excerpt(text: str, at: int, width: int = 70) -> str:
    start = max(0, at - 10)
    snippet = " ".join(text[start : start + width].split())
    return f"...{snippet}..." if start else f"{snippet}..."


def capture_entry(
    tool: str,
    arguments: Mapping[str, Any],
    *,
    entry_id: str,
    func: Callable[..., Any] | None = None,
    environ: Mapping[str, str] | None = None,
    content_dir: str | Path | None = None,
    content_threshold: int = 2000,
) -> CapturedEntry:
    """Call ``tool`` **live** and build a reviewable fixture entry from it.

    The only live remote call in the harness. Match predicates are seeded from
    the arguments as ``equals`` rules -- the tightest possible reading, for a
    reviewer to loosen deliberately rather than a guess at looseness nobody
    checked.

    S7 is enforced here too: any ``path``, ``subdir`` or ``ext`` the real tool
    put on an artifact is dropped, and a large recorded body is moved to
    ``content/<name>`` and referenced, never inlined.
    """

    if func is None:
        from tools.registry import TOOL_FUNCTIONS

        func = TOOL_FUNCTIONS[tool]

    from tools.bench.plane import TOOL_CLASSES

    if TOOL_CLASSES.get(tool) == "local":
        raise ValueError(
            f"{tool} is a class-L tool: it runs live in a benchmark and is the "
            "thing being exercised. Recording it would replace the measurement "
            "with a guess about the measurement."
        )

    result = func(**dict(arguments))
    response = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    response = _strip_artifact_paths(response, content_dir, content_threshold, entry_id)

    entry = {
        "id": entry_id,
        "match": {key: {"equals": value} for key, value in arguments.items()},
        "response": response,
    }

    serialized = yaml.safe_dump(entry, sort_keys=False, allow_unicode=True)
    leaked = scan_for_credentials(serialized, environ)
    if leaked:
        raise CredentialLeak(leaked)

    return CapturedEntry(
        tool=tool, entry=entry, reviews=flag_imperative_strings(response)
    )


def _strip_artifact_paths(
    response: dict[str, Any],
    content_dir: str | Path | None,
    threshold: int,
    entry_id: str,
) -> dict[str, Any]:
    """Replace a real artifact's path with its recorded content. S7."""

    def convert(body: Any, index: int) -> Any:
        if not isinstance(body, Mapping):
            return body
        record = {
            key: value
            for key, value in body.items()
            if key not in ("path", "subdir", "ext") and value is not None
        }
        source = body.get("path")
        if source and content_dir is not None:
            text = Path(source).read_text(encoding="utf-8", errors="replace")
            if len(text) >= threshold:
                name = f"{entry_id}_{index}{Path(source).suffix or '.txt'}"
                target = Path(content_dir) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                record["content_ref"] = name
        return record

    if isinstance(response.get("artifact"), Mapping):
        response["artifact"] = convert(response["artifact"], 0)
    if response.get("artifacts"):
        response["artifacts"] = [
            convert(item, index) for index, item in enumerate(response["artifacts"], 1)
        ]
    return response
