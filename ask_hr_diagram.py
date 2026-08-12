"""
ask_hr_diagram.py - command-line front end for hr_agent.py.

Point it at a FITS frame or an existing photometry table (e.g. an Afterglow
export), ask a question in plain English, and it runs hr_agent's tool-calling
loop -- extract/load photometry -> crossmatch Gaia -> look up literature
cluster parameters -> remove field stars -> fit an isochrone -> plot -- built
on tools.hr_diagram / algorithms.hrdiagram.

Usage, from a terminal:
    python ask_hr_diagram.py <path> "<question>"   # <path> and <question> are
                                                     # placeholders -- replace
                                                     # them, don't type the < >
    python ask_hr_diagram.py <path>          # prompts for the question
    python ask_hr_diagram.py                 # uses DEFAULT_PATH/DEFAULT_QUESTION
                                               # below if set, else prompts for both

Usage, from Python (a REPL, a notebook, another script) -- no file editing,
no hardcoded question, prompts you right there:
    >>> import ask_hr_diagram
    >>> ask_hr_diagram.ask()
    Path to a FITS frame or photometry CSV: ...
    What do you want to know? ...

    ask() also takes either argument directly to skip that prompt:
    ask_hr_diagram.ask(path="myfile.csv")                    # only prompts for the question
    ask_hr_diagram.ask(path="myfile.csv", question="...")    # doesn't prompt at all

Examples:
    python ask_hr_diagram.py ngc2168.fits "Create an HR diagram for NGC 2168 and compare to literature."

    python ask_hr_diagram.py "isochrone_cache/afterglow_photometry (ngc 1851) (1).csv" \\
        "Build an HR diagram for NGC 1851 in B-R vs V. The magnitudes already have E(B-V)=0.0725 removed."

A bare filename (no folder) is looked up inside isochrone_cache/ automatically
(see _resolve_path below), so you don't need the full path for a file that's
already there -- "ChristianNGC1893Photometry_Feb23 (1).csv" resolves the same
as "isochrone_cache/ChristianNGC1893Photometry_Feb23 (1).csv".

Needs ANTHROPIC_API_KEY set in the environment (hr_agent.py reads it when it
constructs its Anthropic client).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# tools.config.artifact_directory() (what every tools.hr_diagram write
# defaults to) reads KEPLER_ARTIFACT_DIR, falling back to an "artifacts"
# subdirectory of the current working directory otherwise -- which would
# scatter output wherever this script happens to be invoked from. Pin it to
# isochrone_cache/ next to this file
# instead, so results always land in the same place regardless of cwd. Must
# happen before hr_agent (and anything under tools) is imported, since
# artifact_directory() is called during each tool's execution, not at import
# time -- but setting it this early keeps the ordering obviously correct
# rather than relying on that. setdefault() leaves an explicit override alone
# if the caller already set KEPLER_ARTIFACT_DIR themselves.
os.environ.setdefault("KEPLER_ARTIFACT_DIR", str(Path(__file__).parent / "isochrone_cache"))

import hr_agent  # noqa: E402 -- import after the env var is set, see above

# ---------------------------------------------------------------------------
# Edit these two and just run `python ask_hr_diagram.py` with no arguments --
# no need to retype the path/question on the command line every time. Command-
# line arguments, if given, still take priority over whatever's set here.
# ---------------------------------------------------------------------------
DEFAULT_PATH: str | None = None  # e.g. "ChristianNGC1893Photometry_Feb23 (1).csv"
DEFAULT_QUESTION: str | None = None  # e.g. "Create an HR diagram and compare to literature."


ISOCHRONE_CACHE_DIR = Path(__file__).parent / "isochrone_cache"


def _resolve_path(raw_path: str) -> Path:
    """A bare filename is looked up in isochrone_cache/ next to this script,
    so you don't need the full path for a file that's already there -- only
    for one that lives somewhere else. First match wins: as given (relative
    to wherever you're running this from, or absolute), then inside
    isochrone_cache/.
    """
    candidate = Path(raw_path)
    if candidate.exists():
        return candidate
    in_cache = ISOCHRONE_CACHE_DIR / raw_path
    if in_cache.exists():
        return in_cache
    return candidate  # doesn't exist either way; let the caller's own error path report it


def _fix_windows_console_encoding() -> None:
    """Claude's replies can contain characters (e.g. U+2212 "-", a typographic
    minus sign, common in negative percent-difference figures) that Windows'
    default console codepage (cp1252) can't encode, crashing print() with a
    UnicodeEncodeError right as the answer is about to be shown. Reconfigure
    stdout/stderr to UTF-8 if the interpreter supports it (3.7+); harmless,
    and a no-op, on platforms that already default to UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def ask(path: str | None = None, question: str | None = None) -> str:
    """Call this directly from a Python session / REPL / notebook -- it
    prompts (via input()) for whatever you didn't pass in, then runs the
    agent and prints + returns the answer:

        >>> import ask_hr_diagram
        >>> ask_hr_diagram.ask()
        Path to a FITS frame or photometry CSV: ChristianNGC1893Photometry_Feb23 (1).csv
        What do you want to know? ...

    Pass either or both arguments to skip that particular prompt --
    ask("myfile.csv") only prompts for the question, ask("myfile.csv", "...")
    doesn't prompt at all.
    """
    _fix_windows_console_encoding()

    path = path or input("Path to a FITS frame or photometry CSV: ").strip()
    resolved = _resolve_path(path)
    if not resolved.exists():
        print(f"Warning: {path!r} does not exist on disk -- the agent will report this itself.\n", file=sys.stderr)
    path = str(resolved)

    question = question or input(
        "What do you want to know? (blank = build the HR diagram and compare to literature) "
    ).strip()
    if not question:
        question = "Create an HR diagram from this file and compare it to literature values."

    full_question = f"Using the file at {path!r}: {question}"

    logging.basicConfig(level=logging.INFO)
    print(f"\n> {full_question}\n")
    answer = hr_agent.run_agent(full_question)
    print("\n=== ANSWER ===\n" + answer)
    return answer


def main() -> None:
    args = sys.argv[1:]
    if args:
        ask(path=args[0], question=" ".join(args[1:]).strip() or None)
    else:
        ask(path=DEFAULT_PATH, question=DEFAULT_QUESTION)


if __name__ == "__main__":
    main()

