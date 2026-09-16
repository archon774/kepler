"""The committed corpus: it loads, it runs, and its keys catch what they name.

docs/working/benchmark.md section 9 and phase 5d.

The end-to-end run proves plumbing, not discrimination: its transcripts were
written to pass. What the second half of this file asserts is the thing that
actually matters about an answer key -- that a model doing the documented wrong
thing fails it, on the check that names the failure. That is a weaker statement
than the 7.1.9 calibration, which needs three real backends of different tiers;
that has now been run for every suite but `smoke` -- see each suite's
calibration.md for what it found, including two tasks it showed discriminate
nothing and one that every backend fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import artifacts, config
from tools.bench.fixtures import FixtureStore, load_fixture_file, resolve_fixture_path
from tools.bench.grade import grade_run
from tools.bench.harness import RunConfig, no_sockets, run_suite
from tools.bench.tasks import load_suite
from tools.llm.replay_backend import ReplayBackend, load_transcript

SUITE_ROOT = Path("benchmarks/suites")
FIXTURE_ROOT = Path("benchmarks/fixtures")
TRANSCRIPT_ROOT = Path("benchmarks/transcripts")
SUITES = ("core", "fieldcal", "pulsar", "optical", "smoke")


@pytest.fixture()
def artifact_root(monkeypatch, tmp_path):
    root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    return root


# --- everything loads -----------------------------------------------------


@pytest.mark.parametrize("suite_id", SUITES)
def test_every_suite_loads(suite_id):
    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    assert suite.id == suite_id
    assert len(suite) >= 1


def test_the_core_suite_is_sealed_at_eight_tasks():
    """model-backends.md open question 4 resolved it at eight, one per
    confirmed-live failure mode. It grows from evidence, not toward a count."""

    assert len(load_suite(SUITE_ROOT / "core", fixture_root=FIXTURE_ROOT)) == 8


@pytest.mark.parametrize("path", sorted(FIXTURE_ROOT.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_fixture_revalidates_through_its_tools_return_model(path):
    """B3. A fixture that has drifted from the code it records fails here,
    before a single token is spent."""

    fixture = load_fixture_file(path, root=FIXTURE_ROOT)
    assert fixture.entries


@pytest.mark.parametrize("path", sorted(FIXTURE_ROOT.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_fixture_states_its_provenance(path):
    """A captured fixture and a hand-authored one grade a model against
    different things, and the entries do not say which."""

    fixture = load_fixture_file(path, root=FIXTURE_ROOT)
    assert len(fixture.provenance) > 40
    assert fixture.recorded_on


def test_the_committed_fixtures_are_marked_hand_authored():
    """They are not captures. Nothing in this repository has ever reached ADS,
    VizieR, NED or ATNF to record one, and a fixture that implied otherwise
    would put invented row counts behind the authority of a recorded response."""

    for path in sorted(FIXTURE_ROOT.glob("*.yaml")):
        fixture = load_fixture_file(path, root=FIXTURE_ROOT)
        assert "HAND-AUTHORED" in fixture.provenance, path.name


@pytest.mark.parametrize("suite_id", SUITES)
def test_every_declared_fixture_exists_and_covers_its_task(suite_id):
    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    for task in suite:
        for name in task.fixtures:
            resolve_fixture_path(name, FIXTURE_ROOT)
        store = FixtureStore.load(task.fixtures, root=FIXTURE_ROOT, task_id=task.id)
        assert set(store.files) == set(task.fixtures)


@pytest.mark.parametrize("suite_id", SUITES)
def test_no_task_declares_a_fixture_for_a_tool_that_runs_live(suite_id):
    """A fixture for a class-L tool would replace the measurement with a guess
    about the measurement."""

    from tools.bench.plane import TOOL_CLASSES

    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    for task in suite:
        for name in task.fixtures:
            assert TOOL_CLASSES[name] in ("remote", "mixed"), f"{task.id}/{name}"


@pytest.mark.parametrize("suite_id", SUITES)
def test_every_suite_states_its_calibration_status_explicitly(suite_id):
    """7.1.9 is a gate, and a suite that has not discriminated anything is not
    a suite. What this asserts is that the file *says where it stands* -- the
    difference between an honest deliverable and a silent one -- and that it
    names every member task, so a task added later cannot inherit a
    calibration it was never part of.

    The status string is matched loosely on purpose: a suite moves from NOT
    CALIBRATED to PARTIALLY CALIBRATED to CALIBRATED as backends run it, and a
    test pinned to one wording would have to be edited to record progress,
    which is how a gate becomes a formality.
    """

    calibration = SUITE_ROOT / suite_id / "calibration.md"
    assert calibration.exists(), suite_id
    text = calibration.read_text(encoding="utf-8")
    assert "CALIBRATED" in text, f"{suite_id} does not state a calibration status"
    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    for task in suite:
        assert task.id in text, f"{suite_id}/{task.id} is absent from calibration.md"


# --- it runs end to end ---------------------------------------------------


def _replay(name: str):
    directory = TRANSCRIPT_ROOT / name

    def factory(task, repeat):
        return ReplayBackend.from_file(directory / f"{task.id}.json")

    return factory


def _run(suite_id, artifact_root, transcript_dir):
    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    out = artifact_root / "bench" / suite_id
    config_ = RunConfig(
        suite_id=suite_id, backends=(f"replay/{transcript_dir}",), out=out
    )
    with no_sockets():
        run_suite(
            suite,
            backends={f"replay/{transcript_dir}": _replay(transcript_dir)},
            config=config_,
            fixture_root=FIXTURE_ROOT,
            out=out,
        )
    return grade_run(out, suite_root=SUITE_ROOT, fixture_root=FIXTURE_ROOT)


def test_the_core_suite_runs_end_to_end_offline_against_replay(artifact_root):
    """The 5d gate. Eight tasks, real fixtures, real graders, no socket."""

    grades = _run("core", artifact_root, "core")
    assert len(grades["grades"]) == 8
    for entry in grades["grades"]:
        assert entry["outcome"] == "end_turn", entry["task_id"]


def test_a_transcript_written_to_pass_does_pass_every_hard_check(artifact_root):
    """Plumbing, not discrimination: these transcripts were written to pass.
    What it proves is that every check in the corpus is *reachable* -- a key
    no answer could satisfy would show up here."""

    grades = _run("core", artifact_root, "core")
    for entry in grades["grades"]:
        assert entry["answer"]["passed"] is True, (
            entry["task_id"],
            entry["answer"]["failures"],
        )
        assert entry["trajectory"]["passed"] is True, (
            entry["task_id"],
            entry["trajectory"]["failures"],
        )


def test_the_optical_suite_runs_its_real_tools_and_its_real_warning_fires(
    artifact_root,
):
    """The strongest end-to-end evidence in this file: the task's env override
    shrinks KEPLER_MAX_FRAMES, list_optical_frames really reads the bundled
    library, and the listing_truncated warning the key names is the one the
    tool itself raised."""

    grades = _run("optical", artifact_root, "optical")
    by_id = {entry["task_id"]: entry for entry in grades["grades"]}
    truncated = by_id["optical-listing-truncated"]
    assert truncated["outcome"] == "end_turn"
    assert truncated["answer"]["passed"] is True

    events = (
        Path(truncated["directory"]) / "events.jsonl"
    ).read_text(encoding="utf-8")
    assert "listing_truncated" in events
    assert "42 frames found" in events


# --- the keys catch what they name ---------------------------------------


def _grade_one(artifact_root, suite_id, task_id, turns):
    """Run one task against a hand-built transcript and return its grade."""

    from dataclasses import replace

    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    task = next(t for t in suite if t.id == task_id)
    one = replace(suite, tasks=(task,))
    out = artifact_root / "bench" / f"{task_id}-negative"
    with no_sockets():
        run_suite(
            one,
            backends={"replay/x": ReplayBackend(load_transcript_from(turns))},
            config=RunConfig(suite_id=suite_id, backends=("replay/x",), out=out),
            fixture_root=FIXTURE_ROOT,
            out=out,
        )
    grades = grade_run(out, suite_root=SUITE_ROOT, fixture_root=FIXTURE_ROOT)
    return grades["grades"][0]


def load_transcript_from(turns):
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(turns, handle)
        path = handle.name
    return load_transcript(path)


def _turn(text, calls=None):
    body = {
        "stop_reason": "tool_use" if calls else "end_turn",
        "text": text,
        "usage": {"input_tokens": 1000, "output_tokens": 20},
    }
    if calls:
        body["tool_calls"] = [
            {"call_id": f"c{i}", "name": n, "arguments": a}
            for i, (n, a) in enumerate(calls)
        ]
    return body


def _failed_checks(entry):
    return {f["check"] for f in entry["answer"]["failures"]} | {
        f["check"] for f in entry["trajectory"]["failures"]
    }


def test_probing_catalogs_one_at_a_time_fails_the_vizier_task(artifact_root):
    entry = _grade_one(
        artifact_root,
        "core",
        "vizier-category-not-per-catalog",
        [
            _turn("Listing catalogs first.", [("list_vizier_catalogs", {"target": "Cas A"})]),
            _turn("Probing one.", [("search_vizier", {"target": "Cas A", "catalog": "VIII/65"})]),
            _turn("Cassiopeia A has 1 radio measurement in VizieR."),
        ],
    )
    assert "must_not_call" in _failed_checks(entry)
    assert "arguments" in _failed_checks(entry)


def test_a_colloquial_name_sent_to_ned_fails_the_designation_task(artifact_root):
    entry = _grade_one(
        artifact_root,
        "core",
        "ned-formal-designation",
        [
            _turn("Asking NED.", [("search_ned", {"name": "Cat's Paw Nebula"})]),
            _turn("NED returned nothing for the Cat's Paw Nebula."),
        ],
    )
    assert "arguments" in _failed_checks(entry)


def test_a_common_name_sent_to_atnf_fails(artifact_root):
    entry = _grade_one(
        artifact_root,
        "core",
        "atnf-formal-designation",
        [
            _turn("Asking ATNF.", [("search_atnf", {"name": "Crab"})]),
            _turn("The Crab pulsar is not in the ATNF catalogue."),
        ],
    )
    assert "arguments" in _failed_checks(entry)


def test_reporting_the_preview_as_the_data_fails(artifact_root):
    entry = _grade_one(
        artifact_root,
        "core",
        "preview-is-not-the-answer",
        [
            _turn(
                "Searching.",
                [("search_vizier", {"target": "Cas A", "category": "radio", "max_catalogs": None})],
            ),
            _turn(
                "Here is the complete historical radio photometry: ten "
                "measurements from 22 MHz to 32 GHz."
            ),
        ],
    )
    failed = _failed_checks(entry)
    assert "must_report_value" in failed
    assert "must_report_artifact_path" in failed


def test_an_omitted_cap_fails_the_null_argument_task(artifact_root):
    """An omitted argument is a *different* semantic from JSON null: capped at
    the default, not uncapped. The protocol axis is diagnostic, so the failure
    lands on the answer axis via the disclosure the model did not make."""

    entry = _grade_one(
        artifact_root,
        "core",
        "null-argument-fidelity",
        [
            _turn(
                "Searching.", [("search_vizier", {"target": "Cas A", "category": "radio"})]
            ),
            _turn("Here is every VizieR radio catalogue for the field."),
        ],
    )
    assert "must_disclose" in _failed_checks(entry)
    fidelity = entry["protocol"]["metrics"]["null_argument_fidelity"]
    assert fidelity["search_vizier.max_catalogs"]["verdict"] == "partial"


def test_the_string_none_fails_the_null_argument_task_and_raises_a_fault(
    artifact_root,
):
    entry = _grade_one(
        artifact_root,
        "core",
        "null-argument-fidelity",
        [
            _turn(
                "Searching.",
                [("search_vizier", {"target": "Cas A", "category": "radio", "max_catalogs": "None"})],
            ),
            _turn("Here is every VizieR radio catalogue for the field."),
        ],
    )
    # S8 caught it before dispatch, so the tool never ran.
    assert entry["protocol"]["metrics"]["fault_counts"]["stringified_null"] == 1


def test_attributing_a_rate_to_a_paper_without_fetching_it_fails(artifact_root):
    """The confirmed-live incident, reproduced: a decline rate attributed by
    name to a paper whose abstract was never read."""

    entry = _grade_one(
        artifact_root,
        "core",
        "abstract-before-attribution",
        [
            _turn("Looking for the object.", [("search_simbad", {"name": "Cassiopeia A"})]),
            _turn(
                "Cassiopeia A declines at 0.3-0.7%/yr depending on frequency, "
                "per Trotter et al. 2017."
            ),
        ],
    )
    failed = _failed_checks(entry)
    assert "conditional" in failed
    assert "must_source_value" in failed


def test_a_rate_read_out_of_the_abstract_passes(artifact_root):
    entry = _grade_one(
        artifact_root,
        "core",
        "abstract-before-attribution",
        [
            _turn(
                "Fetching the abstract.",
                [("get_paper_abstract", {"bibcode": "2017MNRAS.469.1299T"})],
            ),
            _turn(
                "Trotter et al. 2017 measure 0.670 +/- 0.019 %/yr at 1.4 GHz, "
                "averaged over six decades, and state that the decline is not "
                "constant."
            ),
        ],
    )
    assert entry["answer"]["passed"] is True


def test_a_wrong_period_fails_the_pulsar_task(artifact_root):
    """2.1 s is the baseline red-noise peak, the documented wrong answer."""

    scan = "data/pulsar/Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt"
    entry = _grade_one(
        artifact_root,
        "core",
        "pulsar-period-not-from-audio",
        [
            _turn("Resolving.", [("resolve_pulsar_scan", {"name": "B0329+54"})]),
            _turn("Measuring.", [("compute_pulsar_periodogram", {"path": scan})]),
            _turn("Sonifying.", [("sonify_pulsar", {"path": scan})]),
            _turn("The period of B0329+54 is 2.15 s."),
        ],
    )
    assert "must_report_value" in _failed_checks(entry)


def test_presenting_five_frames_as_the_library_fails(artifact_root):
    entry = _grade_one(
        artifact_root,
        "optical",
        "optical-listing-truncated",
        [
            _turn("Listing.", [("list_optical_frames", {})]),
            _turn("There are five optical frames available here."),
        ],
    )
    failed = _failed_checks(entry)
    assert "must_disclose" in failed
    assert "must_not_match" in failed


def test_silently_picking_a_band_fails_the_ambiguity_task(artifact_root):
    entry = _grade_one(
        artifact_root,
        "optical",
        "optical-ambiguous-band",
        [
            _turn("Resolving.", [("resolve_optical_frame", {"name": "M31"})]),
            _turn("The M31 frame is pointed at RA 10.68, Dec 41.27."),
        ],
    )
    assert "must_disclose" in _failed_checks(entry)


# --- the corpus must not be tuned to one model ---------------------------


@pytest.mark.parametrize("suite_id", SUITES)
def test_no_task_file_carries_a_turn_cap(suite_id):
    """A cap written into a task file is a number someone chose, and the only
    evidence available when choosing one is a transcript -- so it is fitted to
    whoever produced that transcript. The loader derives it instead."""

    import yaml

    for path in (SUITE_ROOT / suite_id).glob("*.yaml"):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        assert "max_turns" not in payload, f"{path} sets a turn cap by hand"


@pytest.mark.parametrize("suite_id", SUITES)
def test_the_derived_cap_clears_every_task_requirement(suite_id):
    """The cap scales with what the task *requires*, never with what a model
    was observed to do, and stays above that requirement by a wide margin."""

    from tools.bench.tasks import REFERENCE_CALL_FACTOR, derive_turn_cap

    for task in load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT):
        required = len(task.trajectory.get("must_call", ()))
        assert task.max_turns == derive_turn_cap(task.trajectory)
        assert task.max_turns >= required * REFERENCE_CALL_FACTOR


def test_a_task_needing_many_calls_gets_a_wider_cap_automatically():
    """The derivation is a function of the algorithm, so a heavier task does
    not need anyone to notice and raise its cap."""

    from tools.bench.tasks import TURN_SAFETY_STOP, derive_turn_cap

    assert derive_turn_cap({"must_call": ()}) == TURN_SAFETY_STOP
    assert derive_turn_cap({"must_call": tuple("abcdefgh")}) == 32


def test_no_answer_key_names_a_backend_or_a_model():
    """A key that mentions a provider is a key written for that provider."""

    import re

    banned = re.compile(
        r"qwen|ollama|anthropic|claude|sonnet|opus|haiku|gpt|openai|gemini|llama",
        re.IGNORECASE,
    )
    for suite_id in SUITES:
        for path in (SUITE_ROOT / suite_id).glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            # `CLAUDE.md` is this repository's own instructions file, cited the
            # way any other document is. It is not a model name.
            text = text.replace("CLAUDE.md", "<repo-instructions>")
            hit = banned.search(text)
            assert not hit, f"{path} names a model/provider: {hit.group()!r}"


def test_every_remote_tool_has_a_recorded_fixture():
    """An empty archive is not a neutral one.

    A live run had a model make 38 calls across 12 tools and never answer,
    because each undeclared tool returned nothing and it kept looking for one
    that would. That measured this suite's coverage, not the model -- and it
    penalised the model that cross-checked its sources, which is the behaviour
    the real surface rewards.

    Complete class-R coverage is what makes miss_policy stop mattering.
    """

    from tools.bench.plane import TOOL_CLASSES

    remote = {name for name, kind in TOOL_CLASSES.items() if kind == "remote"}
    recorded = {path.stem for path in FIXTURE_ROOT.glob("*.yaml")}
    assert not (remote - recorded), (
        f"class-R tools with no recorded fixture: {sorted(remote - recorded)}. "
        "A model reaching for one gets silence, and silence invites it to keep "
        "hunting until it runs out of turns."
    )


def test_the_core_suite_declares_the_whole_recorded_archive():
    """Its prompts are open-ended, so a model may reasonably reach for any
    archive; every one it reaches should answer."""

    from tools.bench.plane import TOOL_CLASSES

    suite = load_suite(SUITE_ROOT / "core", fixture_root=FIXTURE_ROOT)
    recorded = {path.stem for path in FIXTURE_ROOT.glob("*.yaml")}
    for task in suite:
        assert set(task.fixtures) == recorded, task.id


# --- answer keys are mechanically determined ------------------------------


@pytest.mark.parametrize("suite_id", SUITES)
def test_no_answer_key_carries_a_hand_typed_number(suite_id):
    """The correction that motivated ``tools/bench/sources.py``.

    A benchmark decides what is correct by consulting the archive, the
    repository's recorded data, or the deterministic tool -- never a literal
    someone typed after watching a model answer, and never another model's
    output. A literal is unfalsifiable by construction: nothing says what it
    was a transcription *of*, so nothing can notice when it stops being true.
    """

    for task in load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT):
        for check in task.answer.get("must_report_value", ()):
            assert "source" in check, (
                f"{task.id}: {check['name']} has no mechanical source"
            )
            assert check["source"]["kind"] in {"fixture", "dataset", "tool_result"}


@pytest.mark.parametrize("suite_id", SUITES)
def test_every_static_answer_key_resolves_to_its_cited_value(suite_id):
    """Load-time resolution is the guarantee: a key citing a field the archive
    no longer has fails the suite rather than failing every model."""

    from tools.bench.sources import resolve_static

    for task in load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT):
        for check in task.answer.get("must_report_value", ()):
            source = check["source"]
            if source["kind"] == "tool_result":
                assert "expected" not in check
                continue
            assert check["expected"] == resolve_static(
                source, fixture_root=FIXTURE_ROOT, where=task.id
            )


# --- the answer keys are frozen -------------------------------------------


KEY_LOCK = SUITE_ROOT.parent / "keys.lock"


def _lock() -> dict:
    import json

    text = "\n".join(
        line for line in KEY_LOCK.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    return json.loads(text)


@pytest.mark.parametrize("suite_id", SUITES)
def test_every_answer_key_matches_the_lock(suite_id):
    """A key changes only on demonstrated invalidity, never to calibrate.

    Deriving keys from the archive stops one being *written* to fit a model.
    This stops one being *revised* to fit one: a changed verdict rule has to
    appear in review as a diff to this file, alongside the re-grade of every
    backend it reprices.
    """

    from tools.bench.tasks import key_lock

    suite = load_suite(SUITE_ROOT / suite_id, fixture_root=FIXTURE_ROOT)
    assert key_lock(suite) == _lock()[suite_id], (
        f"{suite_id}: an answer key changed. If a transcript shows the old key "
        "was invalid, regenerate benchmarks/keys.lock and re-grade every "
        "recorded backend in the same commit -- comparing runs graded by "
        "different rules produces a ranking that looks fine and means nothing."
    )


def test_the_lock_covers_every_suite():
    assert set(_lock()) == set(SUITES)


def test_the_key_digest_ignores_prose_and_tracks_verdicts():
    """It hashes what decides a verdict, so a reworded comment does not force a
    re-grade and a changed threshold does."""

    from tools.bench.tasks import key_digest

    suite = load_suite(SUITE_ROOT / "core", fixture_root=FIXTURE_ROOT)
    task = next(t for t in suite if t.answer.get("must_report_value"))
    before = key_digest(task)

    import copy

    moved = copy.deepcopy(task)
    moved.answer["must_report_value"][0]["rel_tol"] = 0.5
    assert key_digest(moved) != before
