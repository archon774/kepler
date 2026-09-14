"""``falsify`` -- the adversarial pass over the answer keys themselves.

Every probe here is tested against a *constructed* false positive, because a
falsifier that finds nothing is indistinguishable from a broken one. Reporting
"no candidates" over the shipped corpus is only worth anything if these pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest_bench import BARE_TASK, manifest, write_task
from tools.bench.falsify import PROBES, falsify_run


def _run_dir(tmp_path: Path, *, task_body: str, answer: str, events, failures):
    """A graded run directory with one entry, built by hand.

    Hand-built rather than run, because the point is to hand `falsify` a
    grader verdict that is *wrong* -- which a real grade would not produce.
    """

    task_id = next(
        line.split(":", 1)[1].strip()
        for line in task_body.splitlines()
        if line.startswith("id:")
    )
    suite_root = tmp_path / "suites" / "core"
    suite_root.mkdir(parents=True)
    (suite_root / "suite.yaml").write_text(
        f"id: core\ndescription: Core\ntasks: [{task_id}]\n", encoding="utf-8"
    )
    (suite_root / f"{task_id}.yaml").write_text(task_body, encoding="utf-8")

    session = tmp_path / "session"
    session.mkdir()
    (session / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )
    (session / "answer.txt").write_text(answer, encoding="utf-8")
    (session / "session_manifest.json").write_text(
        json.dumps(manifest(outcome="end_turn")), encoding="utf-8"
    )

    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "r",
                "config": {"suite_id": "core"},
                "runs": [{"task_id": task_id, "backend": "b/m", "repeat": 1,
                          "directory": str(session)}],
            }
        ),
        encoding="utf-8",
    )
    (run / "grades.json").write_text(
        json.dumps(
            {
                "grades": [
                    {
                        "task_id": task_id,
                        "backend": "b/m",
                        "repeat": 1,
                        "directory": str(session),
                        "incomplete": False,
                        "answer": {"passed": False, "failures": list(failures)},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return run, suite_root.parent


def _finished(tool, result):
    return {"event": "ToolCallFinished", "name": tool, "result": result}


def test_the_probe_list_is_closed():
    """A probe that is added without a constructed positive beside it is a
    probe nobody has shown to work."""

    assert set(PROBES) == {
        "tolerance",
        "off_subject",
        "sourced_after_all",
        "named_the_artifact",
    }


def test_a_key_an_order_of_magnitude_tighter_than_the_answer_is_accused():
    """The model reported the right number; the key graded its precision."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # The realistic shape: the solve records 21.147659857998637 and the
        # model reports it to six figures. A key demanding parts-per-million
        # agreement fails a correct answer for its formatting.
        body = BARE_TASK + (
            "expect:\n  answer:\n    must_report_value:\n"
            "      - name: zero_point_mag\n"
            "        source:\n"
            "          dataset: fieldcal/zp_solutions/ngc5128_b_002\n"
            "          file: fit_summary.json\n"
            "          path: zero_point\n"
            "        rel_tol: 0.000001\n"
        )
        run, suites = _run_dir(
            tmp_path,
            task_body=body,
            answer="The zero point is 21.1477 mag.",
            events=[_finished("calibrate_zeropoint", {"status": "ok"})],
            failures=[
                {"check": "must_report_value", "detail": "zero_point_mag: no number"}
            ],
        )
        out = falsify_run(run, suite_root=suites, fixture_root="benchmarks/fixtures")
    probes = {f["probe"] for f in out["findings"]}
    assert "tolerance" in probes


def test_a_negation_that_fired_without_naming_the_subject_is_accused():
    """The live defect this probe exists for: a pattern meant to catch "the
    object is not in NED" matched "NED has no band filter of its own"."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        body = (
            "id: t\ntitle: T\nprompt: What does NED have on NGC 6334?\n"
            "expect:\n  answer:\n"
            '    must_not_match: ["NED (has|holds) no"]\n'
        )
        run, suites = _run_dir(
            tmp_path,
            task_body=body,
            answer="NED has no band filter of its own, so I filtered locally.",
            events=[_finished("search_ned", {"status": "ok"})],
            failures=[
                {
                    "check": "must_not_match",
                    "detail": (
                        "the answer matched 'NED (has|holds) no': "
                        "NED has no band filter of its own"
                    ),
                }
            ],
        )
        out = falsify_run(run, suite_root=suites, fixture_root="benchmarks/fixtures")
    findings = [f for f in out["findings"] if f["probe"] == "off_subject"]
    assert findings, out["findings"]
    assert "NGC" in findings[0]["detail"] or "6334" in findings[0]["detail"]


def test_a_negation_that_named_the_subject_is_not_accused():
    """The probe must not accuse a check that fired correctly, or it is noise."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        body = (
            "id: t\ntitle: T\nprompt: What does NED have on NGC 6334?\n"
            "expect:\n  answer:\n"
            '    must_not_match: ["not in NED"]\n'
        )
        run, suites = _run_dir(
            tmp_path,
            task_body=body,
            answer="NGC 6334 is not in NED.",
            events=[_finished("search_ned", {"status": "ok"})],
            failures=[
                {
                    "check": "must_not_match",
                    "detail": "the answer matched 'not in NED': NGC 6334 is not in NED.",
                }
            ],
        )
        out = falsify_run(run, suite_root=suites, fixture_root="benchmarks/fixtures")
    assert [f for f in out["findings"] if f["probe"] == "off_subject"] == []


def test_a_number_the_event_stream_contains_is_accused():
    """A sourcing check that fired over a sourced number is a grader defect."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        body = BARE_TASK + (
            "expect:\n  answer:\n    must_source_value:\n"
            "      - pattern: '%\\\\s*/\\\\s*yr'\n"
            "        because: a rate must come from a tool\n"
        )
        run, suites = _run_dir(
            tmp_path,
            task_body=body,
            answer="The decline is 0.670 %/yr.",
            events=[_finished("get_paper_abstract", {"status": "ok", "rate": 0.670})],
            failures=[
                {
                    "check": "must_source_value",
                    "detail": "the answer states '0.670' matching '%/yr'",
                }
            ],
        )
        out = falsify_run(run, suite_root=suites, fixture_root="benchmarks/fixtures")
    assert any(f["probe"] == "sourced_after_all" for f in out["findings"])


@pytest.mark.parametrize("run_id", [
    "2026-09-14-rank-qwen3.8-27b",
    "2026-09-14-rank-claude-sonnet-5",
    "2026-09-14-rank-qwen3.5-9b",
    "2026-09-14-rank-gemma4-12b",
])
def test_the_shipped_keys_survive_the_pass(run_id):
    """The result that matters, and it is only meaningful because the probes
    above are shown to fire. Skipped where the run directory is not present --
    artifacts/ is gitignored, so a fresh checkout has no recorded runs."""

    run = Path("artifacts/bench") / run_id
    if not (run / "grades.json").exists():
        pytest.skip(f"{run} is not present (artifacts/ is not tracked)")
    out = falsify_run(run)
    assert out["findings"] == [], out["findings"]
