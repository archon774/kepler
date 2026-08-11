"""Kepler: optional agentic loop over the ``tools`` schemas.

Uses ``tools.registry.TOOL_SCHEMAS`` -- one schema per database instead of a
single schema with a ``database`` enum switch -- and returns
``tools.models.ToolResult`` payloads via ``.model_dump()``.

Per ``docs/tool-architecture.md`` section 5, serving/agent-loop code is
optional: every tool works from ordinary Python without this module.
"""

from __future__ import annotations

import json
import os
import sys

from tools import artifacts
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS
from tools.sessions import AgentSession, make_cache_key

__all__ = ["run", "main"]

#: Confirmed live, from real transcripts and direct API testing, not written
#: speculatively. Two classes of finding drove this:
#:
#: 1. A transcript where a model burned half a 6-turn budget re-issuing an
#:    identical failing NED call, and probed individual VizieR catalogs one
#:    at a time after a broad category="radio" call returned a large count
#:    with (at the time) an empty preview. That preview gap is fixed at the
#:    tool level (tools.vizier); the rest is strategy tool responses
#:    alone can't convey.
#: 2. Direct testing of every database's name resolution: SIMBAD and VizieR's
#:    target= resolve colloquial names correctly ("cat's paw nebula" -> NGC
#:    6334); NED's resolver is unreliable with them (the same query times out
#:    repeatedly); MPC and ATNF do *zero* name resolution and hard-fail on
#:    anything but a formal designation ("Halley" -> ValueError, "Crab" -> 0
#:    pulsars matched, where "1P" and "J0534+2200" succeed immediately).
#:
#: The ADS section below is the one exception to "confirmed live": no
#: ADS_DEV_KEY is configured in this environment, so its search-syntax
#: guidance is grounded in ADS's own published documentation
#: (https://ui.adsabs.harvard.edu/help/search/search-syntax) and
#: astroquery.nasa_ads's source code, not an actual query against the
#: service. Treat it as documentation-grounded, not empirically confirmed,
#: until it has been run against the real API.
SYSTEM_PROMPT = """You are an astronomy research assistant with tools over SIMBAD, NED, \
VizieR, ATNF, MAST, MPC, CASDA, and ADS (tools).

BEFORE calling any tool, work out the correct search term for that specific database from \
the user's request -- do not pass the user's wording through unchanged by default. Each \
database expects a different kind of identifier; use your own astronomical knowledge to \
translate a common/colloquial name to the right form for whichever database you are about \
to call, per the table below. Confirmed by direct testing, not assumed:

- SIMBAD (search_simbad, search_simbad_measurements, search_simbad_bibliography): tolerant \
of common names and multi-word identifiers ("cat's paw nebula" resolves correctly). Pass \
the name as given. search_simbad_measurements' `table` and search_ned's `table` must still \
be an exact value from the tool's own enum/vocabulary, never free text.
- NED (search_ned): resolver is unreliable with colloquial names -- the same query that \
times out for "cat's paw nebula" resolves instantly for "NGC 6334". Always convert to the \
formal catalog designation (NGC/IC/M/PGC/UGC number, or another standard identifier) \
yourself first; use search_simbad or your own knowledge if you don't already know it. Also, \
NED has no band filter of its own -- "photometry" always returns the full SED, X-ray \
through radio, in one table. If the user asked for one band only, pass max_frequency_hz \
(and/or min_frequency_hz) so both the result and the saved file are actually scoped to it \
-- radio continuum is conventionally below ~3e11 Hz (300 GHz). Do not report a multi-band \
table as if it were single-band just because that's what you were asked for.
- VizieR (search_vizier, list_vizier_catalogs): `target=` resolves common names like \
SIMBAD does. `catalog=` must be an exact VizieR ID ("VIII/65"), never a description. \
list_vizier_catalogs ANDs every word against catalog TITLES, not topics or object names -- \
use 1-2 broad words ("radio continuum", "pulsar"), never a multi-word phrase and never the \
object name even combined with a topic word ("Cassiopeia A secular decrease" and \
"Cassiopeia flux" both fail for the same reason: catalog titles are named for surveys/\
instruments/authors, never for the target object). VizieR has no per-object monitoring \
catalogs to find this way regardless. For "everything about object X" use search_vizier \
with category= directly instead of searching for a catalog. IMPORTANT: category= tags \
whole catalogs, not rows -- "radio" also matches multi-wavelength cross-match catalogs \
(confirmed live: e.g. a catalog titled "cross-matched radio/infrared/X-ray sources") where \
only some columns are actually in that band. Check each matched catalog's own title/columns \
before reporting its rows as pure radio (or any single-band) data -- the tool result flags \
this with a warning every time category= is used, but still verify per catalog.
- ATNF (search_atnf): zero name resolution. A famous nickname like "Crab" matches nothing. \
`name` must be the pulsar's formal designation -- J2000 form preferred ("J0534+2200" for \
the Crab pulsar), B1950 also works ("B0531+21"). Translate any pulsar nickname yourself \
first. Pulsar-only; never pass a nebula or remnant name.
- MAST (search_mast): resolver handles common names reasonably well, similar to SIMBAD/NED \
combined. Pass the name as given.
- MPC (search_mpc): zero name resolution, and it fails hard, not just poorly -- "Halley" \
raises an error outright. `designation` must be a formal MPC identifier: an asteroid \
number ("1" for Ceres), a periodic comet number with trailing "P" ("1P" for Halley's \
Comet), or a full comet designation ("C/2018 E1"). Translate any common name yourself \
first, from general knowledge.
- CASDA (search_casda): `target=` is resolved via SIMBAD internally, so common names are \
fine here too, same as SIMBAD.
- ADS (search_ads, get_citing_papers, get_referenced_papers, build_literature_review): the \
one database here that is genuinely hard to search well, including for a human -- ADS's own \
documentation warns that unfielded, bare-word queries "may not produce the expected \
results." It is a fielded query language (author:"Last, F.", title:"...", year:2015-2020), \
not natural-language search. Use search_ads's structured parameters (author, title, \
abstract, year, bibcode, object_name, doctype) -- they get assembled into correct ADS \
syntax for you -- rather than putting the user's question, or several unrelated keywords, \
into `query`. A query with too many loosely-related terms tends to return nothing or \
irrelevant results, the same way "Cassiopeia flux" returns nothing on VizieR: prefer one or \
two well-chosen fielded terms (e.g. title="Cassiopeia A" + year="2015-2020") over a long \
list of keywords. `query=` is a raw ADS string for syntax the structured parameters don't \
cover -- second-order operators (similar(bibcode:...), trending(topic)), proximity search, \
wildcards -- and combines with the structured parameters via AND if both are given. \
`object_name=` is the least ordinary field here: per ADS's own documentation it isn't a \
plain text match but a special SIMBAD/NED-tagged lookup combined with a text search, and \
combining it with other fielded terms has been observed to fail with a 400 error (query \
rejected by ADS's parser) in a way not yet root-caused. If a search_ads/\
build_literature_review call errors, read the error message -- it now includes ADS's own \
response body, which names the actual problem -- and retry with a simplified query rather \
than repeating the identical call: drop object_name first and rely on title=/abstract= for \
the object instead, or fall back to a hand-written query= with just one or two fielded terms.

When the user's request implies exhaustive data ("all", "every", "complete", "historical", \
or similar), disable the cap on search_vizier's max_catalogs and/or search_mast's \
max_observations so nothing is capped -- the defaults exist only to keep an unscoped \
exploratory query fast, not to limit a request for everything. IMPORTANT, confirmed live: \
tool call arguments are JSON, not Python -- set the parameter to the JSON value null, the \
same way you would omit it to accept a default. Do NOT send the text "None" (that is a \
Python literal, not a JSON one, and arrives as the four-character string "None", which \
breaks the tool). Omitting the parameter entirely does NOT disable the cap either -- that \
uses the tool's normal capped default; null is the only way to request no cap. Every tool \
already writes its full result to a local file regardless of the size of the inline \
preview; when you answer such a request, say explicitly that the complete data was saved \
and give the artifact path(s) from the tool result -- do not present the inline preview as \
if it were the whole answer.

SOURCING, confirmed live as a real failure mode: search_simbad_bibliography and search_ned \
(table="references") only give you bibcodes, titles, years -- never a specific finding, \
number, or rate from inside a paper. An agent asked to confirm a decline rate once \
answered "0.3-0.7%/yr depending on frequency" and attributed it by name to a real paper \
(Trotter et al. 2017) -- the actual abstract says "0.670 +/- 0.019%/yr" averaged over six \
decades, explicitly non-constant. That figure came from training data, not from any tool \
call, and was presented as if the pipeline had verified it. search_ads and \
build_literature_review already return abstract text inline for every paper they find \
(no separate fetch needed for those); get_paper_abstract covers a bibcode found some other \
way (search_simbad_bibliography, search_ned references). Before stating a specific number \
and attributing it to a named paper, get that paper's abstract via one of these and quote \
what it actually says. If you state a figure from general astronomical background instead, \
say so explicitly ("this is general background, not independently verified against the \
source this session") rather than presenting it as a confirmed result of the search.

LITERATURE REVIEWS: when the user asks for a literature review, bibliography, or "papers \
on X" with citations, use build_literature_review rather than listing papers you already \
know about from training data -- it searches ADS for real matches and writes a Markdown \
file with full citations and abstracts to disk, which is what makes the review verifiable \
rather than recalled. Report the artifact path(s) it returns.

Other guidance from observed failure modes:

- search_simbad, search_ned, search_vizier, search_atnf, and search_mast all resolve an \
object name themselves. Only call resolve_target first if you specifically need \
coordinates for search_casda, or need to disambiguate an unclear name.
- search_vizier's category="radio" (or "optical"/"infrared"/"xray"/...) covers a whole \
spectrum in ONE call. Do not call it once per catalog ID unless you already found a \
specific catalog's preview interesting and want more rows than max_catalogs/row_limit \
gave you.
- If a tool call errors or times out, do not immediately repeat the identical call. \
Either the error already reflects an internal retry (see the tool's own description) \
or a different approach is needed.
- Once you have enough data to answer the question, stop calling tools and write the \
answer. You do not need to exhaust every tool."""


def run(
    user_message: str,
    *,
    max_turns: int = 20,
    model: str = "claude-sonnet-5",
    system: str = SYSTEM_PROMPT,
) -> str | None:
    """Run a bounded agentic loop answering ``user_message`` with the
    ``tools`` schemas.

    Returns the session manifest path when a session runs. The CLI ignores the
    return value, but tests and Python callers can use it to inspect the saved
    tool-call trace.
    """
    import anthropic

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Set your ANTHROPIC_API_KEY environment variable to execute queries.")
        return

    client = anthropic.Anthropic(api_key=anthropic_key)

    print(f"User: {user_message}\n" + "=" * 50)
    messages = [{"role": "user", "content": user_message}]
    session = AgentSession(
        user_message=user_message,
        model=model,
        max_turns=max_turns,
        system=system,
    )

    # Confirmed live: the model can re-issue an exactly identical tool call
    # (same name, same arguments) across turns, presumably not recognizing a
    # prior result as still current. Cached here so a repeat costs no extra
    # network round trip and returns the same answer rather than a fresh,
    # possibly differently-paginated one.
    call_cache: dict[str, dict] = {}

    try:
        with artifacts.scoped_artifacts(session.artifact_subdir):
            session.save()

            for turn in range(max_turns):
                with client.messages.stream(
                    model=model,
                    max_tokens=128000,
                    system=system,
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                ) as stream:
                    text_parts: list[str] = []
                    for text in stream.text_stream:
                        text_parts.append(text)
                        print(text, end="", flush=True)

                    response = stream.get_final_message()
                    assistant_text = "".join(text_parts)

                if response.stop_reason == "end_turn":
                    session.record_turn(
                        turn=turn + 1,
                        stop_reason=response.stop_reason,
                        assistant_text=assistant_text,
                        tool_call_sequences=[],
                    )
                    manifest_path = session.save(
                        outcome="end_turn", current_turn=turn + 1
                    )
                    print("\n\n[Task Complete]")
                    print(f"[Session Manifest] {manifest_path}")
                    return str(manifest_path)

                if response.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})
                    tool_results = []
                    tool_call_sequences: list[int] = []

                    for content_block in response.content:
                        if content_block.type != "tool_use":
                            continue

                        tool_name = content_block.name
                        tool_args = content_block.input
                        tool_use_id = content_block.id
                        cache_key = make_cache_key(tool_name, tool_args)

                        print(
                            f"\n\n[*] [Turn {turn + 1}] Executing {tool_name} "
                            f"with {tool_args}"
                        )

                        cache_hit = cache_key in call_cache
                        if cache_hit:
                            result = call_cache[cache_key]
                            print("(repeated call -- returning cached result)")
                        else:
                            func = TOOL_FUNCTIONS.get(tool_name)
                            if func is None:
                                result = {
                                    "status": "error",
                                    "errors": [
                                        {
                                            "code": "invalid_input",
                                            "message": f"Unknown tool: {tool_name}",
                                        }
                                    ],
                                }
                            else:
                                result = func(**tool_args).model_dump()
                            call_cache[cache_key] = result

                        sequence = session.record_tool_call(
                            turn=turn + 1,
                            tool_use_id=tool_use_id,
                            tool_name=tool_name,
                            arguments=tool_args,
                            cache_key=cache_key,
                            cache_hit=cache_hit,
                            result=result,
                        )
                        tool_call_sequences.append(sequence)
                        session.save(current_turn=turn + 1)

                        print("Tool Output JSON Preview:")
                        print(json.dumps(result, indent=2, default=str)[:400] + "...\n")

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(result, default=str),
                            }
                        )

                    session.record_turn(
                        turn=turn + 1,
                        stop_reason=response.stop_reason,
                        assistant_text=assistant_text,
                        tool_call_sequences=tool_call_sequences,
                    )
                    session.save(current_turn=turn + 1)
                    messages.append({"role": "user", "content": tool_results})
                else:
                    session.record_turn(
                        turn=turn + 1,
                        stop_reason=response.stop_reason,
                        assistant_text=assistant_text,
                        tool_call_sequences=[],
                    )
                    session.save(current_turn=turn + 1)

            print("\n\n[Max turns reached]")
            manifest_path = session.save(outcome="max_turns", current_turn=max_turns)
            print(f"[Session Manifest] {manifest_path}")
            return str(manifest_path)
    except Exception:
        manifest_path = session.save(outcome="error")
        print(f"\n\n[Session Manifest] {manifest_path}", file=sys.stderr)
        raise


def main() -> None:
    user_message = " ".join(sys.argv[1:])
    run(user_message)


if __name__ == "__main__":
    main()
