"""The skill and the agent loop's system prompt say the same load-bearing things.

``tools/skill/source/`` restates, for a model that never receives
``SYSTEM_PROMPT``, the rules ``tools/agent/prompt.py`` gives Kepler's own loop.
Two hand-written statements of one rule drift the first time a correction
lands in one and not the other, so this module pins them together: every
invariant below must appear, word for word after normalisation, in **both**
``SYSTEM_PROMPT`` and the skill's entry document. The entry document, not the
references, because it is the part a served surface always delivers (C5).

It also keeps the skill honest about itself: every rule cites a section that
exists, every tool it names is registered, every registered tool is named, and
the rendered repository copy matches its source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tools.agent.prompt import SYSTEM_PROMPT
from tools.registry import TOOL_SCHEMAS
from tools.skill import (
    BRIEF_LIMIT,
    REPOSITORY_COPY,
    SERVED_URI_PREFIX,
    SKILL_NAME,
    check_repository_copy,
    render_repository_copy,
    served_brief,
    served_documents,
    source_documents,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL_NAMES = {schema["name"] for schema in TOOL_SCHEMAS}
_SOURCES = source_documents()
_ENTRY = _SOURCES["SKILL.md"]


def _normalise(text: str) -> str:
    """Lower-case, drop Markdown emphasis and quote markers, collapse whitespace."""
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = text.replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", text).strip().lower()


_PROMPT_NORMALISED = _normalise(SYSTEM_PROMPT)
_ENTRY_NORMALISED = _normalise(_ENTRY)

#: The rules whose drift would produce a silently wrong answer. Each phrase must
#: survive in both texts; rewording one side means rewording the other.
INVARIANTS: dict[str, tuple[str, ...]] = {
    "measure_before_compare": (
        "measure first, compare second",
        "retry with different parameters",
    ),
    "peak_fold_snr_over_peak_confidence": (
        "check peak_fold_snr, not peak_confidence",
        "the confidence threshold assumes white noise",
    ),
    "wrong_period_is_silent": (
        "folding at a wrong period returns a flat profile, not an error",
    ),
    "reference_fold_is_not_a_detection": (
        "pulse_snr is not an independent detection",
        "a blind search succeeds on one of the five bundled scans",
        "an ordinary outcome to report, not a failure to hide",
    ),
    "recurring_artifacts": (
        "0.016665 s is 60.006 hz mains interference",
        "a 2.1-2.2 s peak is leftover baseline red noise",
    ),
    "no_period_from_audio": ("never read a period off rendered audio",),
    "sonify_with_period": ("always pass period_s when you have one",),
    "no_invented_paths": ("never invent a path",),
    "ned_formal_designation": ("always convert to the formal catalog designation",),
    "atnf_no_name_resolution": ("atnf (search_atnf): zero name resolution",),
    "mpc_no_name_resolution": (
        "mpc (search_mpc): zero name resolution, and it fails hard",
    ),
    "null_not_none": (
        "set the parameter to the json value null",
        'do not send the text "none"',
        "omitting the parameter entirely does not disable the cap",
    ),
    "literature_sourcing": (
        "before stating a specific number and attributing it to a named paper",
        "general background, not independently verified against the source this session",
        "never fill in a missing value",
    ),
}


@pytest.mark.parametrize("name", sorted(INVARIANTS))
def test_invariant_appears_in_both_the_prompt_and_the_skill(name):
    for phrase in INVARIANTS[name]:
        assert phrase in _PROMPT_NORMALISED, f"{name}: SYSTEM_PROMPT lost {phrase!r}"
        assert phrase in _ENTRY_NORMALISED, f"{name}: SKILL.md lost {phrase!r}"


def _first_occurrences(text: str, marker: str, names: list[str]) -> list[int]:
    start = text.index(marker)
    return [text.index(name, start) for name in names]


def test_pulsar_stages_appear_in_dependency_order_in_both():
    stages = [
        "load_pulsar_lightcurve",
        "compute_pulsar_periodogram",
        "fold_pulsar_lightcurve",
        "sonify_pulsar",
    ]
    for text, marker in (
        (_PROMPT_NORMALISED, "pulsar pipeline. to hear"),
        (_ENTRY_NORMALISED, "the pulsar chain: the order is a dependency"),
    ):
        positions = _first_occurrences(text, marker, stages)
        assert positions == sorted(positions), marker


def _authority_blocks(text: str) -> list[str]:
    """Each ``> Authority: ...`` blockquote, joined onto one line."""
    blocks, current = [], None
    for line in text.splitlines():
        if line.startswith("> Authority:"):
            current = [line[2:]]
            blocks.append(current)
        elif current is not None and line.startswith(">"):
            current.append(line[1:].strip())
        else:
            current = None
    return [" ".join(block) for block in blocks]


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.mark.parametrize("name", sorted(_SOURCES))
def test_every_citation_names_something_that_exists(name):
    """A cited path exists, a cited tool is registered, a cited section is real."""
    for block in _authority_blocks(_SOURCES[name]):
        cited = re.findall(r"`([^`]+)`", block)
        paths = [token for token in cited if "/" in token]
        tools = [token for token in cited if "/" not in token]
        assert paths, f"{name}: an Authority block cites no file: {block}"
        for path in paths:
            assert (_REPO_ROOT / path).is_file(), f"{name}: cites missing {path}"
        assert set(tools) <= _TOOL_NAMES, f"{name}: cites unregistered {tools}"

        cited_text = _collapse(
            " ".join(
                SYSTEM_PROMPT
                if path == "tools/agent/prompt.py"
                else (_REPO_ROOT / path).read_text(encoding="utf-8")
                for path in paths
            )
        )
        for section in re.findall(r'"([^"]+)"', block):
            assert _collapse(section) in cited_text, (
                f"{name}: cites section {section!r}, found in none of {paths}"
            )


def test_every_rule_in_the_entry_document_cites_its_authority():
    sections = re.split(r"^## ", _ENTRY, flags=re.MULTILINE)[1:]
    assert sections
    for section in sections:
        heading = section.splitlines()[0]
        assert "> Authority: `tools/agent/prompt.py`" in section, heading


def test_every_registered_tool_is_named_by_the_skill():
    corpus = "\n".join(_SOURCES.values())
    named = set(re.findall(r"\b[a-z][a-z0-9_]*\b", corpus))
    assert _TOOL_NAMES - named == set()


def test_every_tool_like_name_the_skill_uses_is_registered():
    """A backticked call ``name(`` is a tool; a renamed tool must not linger.

    ADS's second-order operators are the one other thing written that way.
    """
    corpus = "\n".join(_SOURCES.values())
    called = set(re.findall(r"`([a-z][a-z0-9_]*)\(", corpus))
    assert called - {"similar", "trending"} <= _TOOL_NAMES


@pytest.mark.parametrize("name", sorted(_SOURCES))
def test_relative_links_resolve_to_a_source_document(name):
    base = Path(name).parent
    for target in re.findall(r"\]\(([^)\s#:]+\.md)\)", _SOURCES[name]):
        resolved = (base / target).as_posix()
        assert resolved in _SOURCES, f"{name}: dead link {target}"


def test_the_repository_copy_is_rendered_from_the_source():
    assert check_repository_copy() == [], (
        "skills/kepler-tools/ is stale; run `uv run python -m tools.skill`"
    )


def test_the_rendered_entry_carries_loadable_frontmatter():
    rendered = render_repository_copy()["SKILL.md"]
    _, frontmatter, body = rendered.split("---\n", 2)
    meta = yaml.safe_load(frontmatter)
    assert meta["name"] == SKILL_NAME
    assert meta["description"]
    assert body.rstrip().endswith(_ENTRY.rstrip())


def test_the_claude_skill_link_points_at_the_repository_copy():
    link = _REPO_ROOT / ".claude" / "skills" / SKILL_NAME
    assert link.is_symlink()
    assert link.resolve() == REPOSITORY_COPY


def test_the_working_on_the_repository_files_point_at_the_skill():
    for doc in ("AGENTS.md", "CLAUDE.md"):
        text = (_REPO_ROOT / doc).read_text(encoding="utf-8")
        assert "skills/kepler-tools/" in text, doc


# --- the served skill (C5) ------------------------------------------------------

#: What the always-delivered brief must still say. Each phrase is also in
#: SYSTEM_PROMPT, so the brief cannot drift from the authority either.
BRIEF_INVARIANTS = (
    "never invent a path",
    "measure first, compare second",
    "peak_fold_snr, not peak_confidence",
    "not an independent detection",
    "0.016665 s",
    "2.1-2.2 s",
    "formal designation",
    "zero name resolution",
    'the text "none"',
)


@pytest.mark.parametrize("phrase", BRIEF_INVARIANTS)
def test_the_brief_keeps_the_rules_the_prompt_states(phrase):
    assert phrase in _normalise(served_brief()), phrase
    assert phrase in _PROMPT_NORMALISED, phrase


def test_the_brief_points_at_every_served_document_and_nothing_else():
    named = set(re.findall(r"kepler://skill/[\w/.-]+\.md", served_brief()))
    assert named == {SERVED_URI_PREFIX + name for name in served_documents()}


def test_the_brief_leaves_room_for_the_install_facts():
    """Measured in C5: Claude Code delivers ~2,000 characters of instructions."""
    assert BRIEF_LIMIT <= 2_000
    assert len(served_brief()) <= BRIEF_LIMIT - 800


def test_the_served_documents_and_the_repository_copy_share_one_source():
    """Undo each surface's rendering and both give back the source, exactly."""
    served = served_documents()
    repository = render_repository_copy()
    assert set(served) == set(_SOURCES) - {"BRIEF.md", "references/checkout.md"}
    for name, text in served.items():
        source = _SOURCES[name]
        kept = "".join(
            line
            for line in source.splitlines(keepends=True)
            if not (line.startswith("|") and "references/checkout.md" in line)
        )
        assert text.replace(SERVED_URI_PREFIX, "") == kept, name
        assert repository[name].endswith(source), name
    assert "kepler://" not in "".join(repository.values())
