"""The efficiency axis -- **Q2**.

``docs/benchmarking/harness.md`` section 7.2. Pure reporting: no pass/fail, and no
money. Three things are measured -- **timing per token, turns, and tokens
used** -- plus the call counts that explain a token total.

**Three clocks, never one.** Wall-clock per task is the number a user feels and
it is *not* a property of the model: on this surface tool execution dominates
it. Field calibration is a 30-90 s network round trip, a periodogram is real
compute over a real scan, and an all-sky ``solve_astrometry`` is ~285 s. A
model that reaches the right answer by calling ``run_photometry_on_target``
with ``use_field_cal=true`` looks an order of magnitude slower than one that
answers from a listing, and that says nothing about tokens per second. So:

* **model time** -- ``sum(turns[].latency_ms)``; a property of the model and
  its serving stack.
* **tool time** -- ``sum(ToolCallFinished.duration_ms)``; a property of the
  model's *choices*.
* **wall clock** -- what a user waits for.

**Timing per token is derived from the model clock alone.** Tool time never
enters it.

**The four token classes stay separate.** ``SYSTEM_PROMPT`` is ~270 lines and
is resent every turn alongside 55 tool schemas, so on a multi-turn task that
fixed prefix dominates the input total. A backend that caches it and one that
does not are doing visibly different amounts of work at identical behaviour,
and folding cache reads into one input number would hide that.

There is no cost axis and no price table (section 15, divergence 3). Tokens
are the measurement; converting them to money is the reader's job, against
their own current pricing page.
"""

from __future__ import annotations

from typing import Any, Mapping

from tools.bench.graders import Evidence, GradeResult
from tools.sessions import USAGE_FIELDS

__all__ = ["grade", "RATE_KINDS"]

#: How a tokens-per-second figure was obtained. Printed beside every rate,
#: because a streaming rate and an average over a completed response are two
#: different quantities and one undifferentiated column would compare them.
RATE_KINDS: tuple[str, ...] = ("streaming", "averaged", "unknown")


def grade(task: Any, evidence: Evidence) -> GradeResult:
    """Report, never judge. ``passed`` is always ``True`` on this axis."""

    result = GradeResult(axis="efficiency")
    manifest = evidence.manifest
    turns = manifest.get("turns") or []
    calls = evidence.tool_calls()

    model_time_ms = _sum_optional(turn.get("latency_ms") for turn in turns)
    tool_time_ms = _sum_optional(
        event.get("duration_ms")
        for event in evidence.events
        if event.get("event") == "ToolCallFinished"
    )

    totals = _usage_totals(manifest)
    output_tokens = totals.get("output_tokens")
    rate_kind = _rate_kind(manifest)

    cache_read = totals.get("cache_read_tokens")
    input_tokens = totals.get("input_tokens")
    cache_share = (
        cache_read / input_tokens
        if cache_read is not None and input_tokens
        else None
    )

    cache_hits = sum(1 for call in calls if call.get("cache_hit"))

    result.metrics = {
        "turns": len(turns),
        "tool_calls": len(calls),
        "distinct_calls": manifest.get("cache_entry_count"),
        # A re-issued identical call is tokens spent for nothing. It is a
        # confirmed-live failure mode and already recorded per call, so
        # reporting it costs nothing -- it sits under "tokens used" rather
        # than standing as a metric of its own.
        "duplicate_calls": cache_hits,
        "duplicate_rate": (cache_hits / len(calls)) if calls else None,
        "tokens": {name: totals.get(name) for name in USAGE_FIELDS},
        "cache_share_of_input": cache_share,
        "model_time_ms": model_time_ms,
        "tool_time_ms": tool_time_ms,
        "wall_ms": None,  # filled in by the caller from the run record
        "tokens_per_second": _rate(output_tokens, model_time_ms),
        "tokens_per_second_kind": rate_kind,
        "incomplete": evidence.incomplete,
        "outcome": evidence.outcome,
    }
    return result


def _sum_optional(values) -> float | None:
    """Sum the values that are present, or ``None`` if none were.

    Never ``0.0`` for "nothing reported": a run whose adapter did not report
    latency did not take no time.
    """

    present = [float(value) for value in values if value is not None]
    return sum(present) if present else None


def _usage_totals(manifest: Mapping[str, Any]) -> dict[str, int | None]:
    """``usage_totals`` from a v2 manifest, or rebuilt from the turns.

    A v1 manifest has neither, and every class reads ``None`` -- not ``0``.
    """

    totals = manifest.get("usage_totals")
    if isinstance(totals, Mapping):
        return {name: totals.get(name) for name in USAGE_FIELDS}

    rebuilt: dict[str, int | None] = {name: None for name in USAGE_FIELDS}
    for turn in manifest.get("turns") or []:
        usage = turn.get("usage")
        if not isinstance(usage, Mapping):
            continue
        for name in USAGE_FIELDS:
            value = usage.get(name)
            if value is not None:
                rebuilt[name] = (rebuilt[name] or 0) + value
    return rebuilt


def _rate(output_tokens: int | None, model_time_ms: float | None) -> float | None:
    if not output_tokens or not model_time_ms:
        return None
    return output_tokens / (model_time_ms / 1000.0)


def _rate_kind(manifest: Mapping[str, Any]) -> str:
    """Whether the rate is a streaming rate or an average over a completed
    response.

    Only the Anthropic adapter streams natively; the other three call
    ``on_text`` once with the finished text, so their ``latency_ms`` is a
    whole round trip. Printing both in one undifferentiated column would
    compare two different quantities.
    """

    backend = manifest.get("backend")
    if not isinstance(backend, Mapping):
        return "unknown"
    capabilities = backend.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return "unknown"
    streaming = capabilities.get("streaming")
    if streaming is None:
        return "unknown"
    return "streaming" if streaming else "averaged"
