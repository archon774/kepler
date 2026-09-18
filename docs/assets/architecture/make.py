#!/usr/bin/env python3
"""Generate the architecture-layer figures for ``docs/architecture-layers.md``.

Twelve files, two per figure: the repository renders theme-aware assets as a
``-light``/``-dark`` pair behind a ``<picture>`` element (see the README
banner), not as one file with an internal ``prefers-color-scheme`` query.
GitHub picks between the two from *its own* theme setting, which an SVG's
internal media query cannot see -- it follows the operating system instead,
so a reader on GitHub's dark theme with a light OS would get black text on a
dark plate.

One geometry, two palettes. Each figure's body is written once, in terms of
the classes :data:`STYLE` defines; only the colour literals differ between the
two renders. Re-run after editing a figure:

    python3 docs/assets/architecture/make.py

Line counts quoted inside the figures come from ``wc -l`` over tracked
sources at dev @ aa93c87. Re-measure before changing them.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent

SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "DejaVu Sans Mono", monospace'

PALETTES = {
    "light": {
        "bg": "#FFFFFF", "surface2": "#F5F8F7",
        "ink": "#0F1619", "ink2": "#38474E", "muted": "#6B7C84",
        "rule": "#CBD5D3",
        "accent": "#0C6B78", "accentSoft": "#D9EDEF",
        "warn": "#A8500C", "warnSoft": "#F6E6D7",
    },
    "dark": {
        "bg": "#0D1117", "surface2": "#151F24",
        "ink": "#E7EDEB", "ink2": "#B3C2C7", "muted": "#7E9097",
        "rule": "#25343B",
        "accent": "#4FBECA", "accentSoft": "#0E3238",
        "warn": "#DE9A52", "warnSoft": "#38281A",
    },
}

STYLE = """
  svg {{ color: {ink}; }}
  text {{ font-family: {sans}; fill: {ink}; }}
  .d-box {{ fill: {surface2}; stroke: {rule}; stroke-width: 1.4; }}
  .d-boxA {{ fill: {accentSoft}; stroke: {accent}; stroke-width: 1.4; }}
  .d-boxW {{ fill: {warnSoft}; stroke: {warn}; stroke-width: 1.4; }}
  .d-frame {{ fill: none; stroke: {rule}; stroke-width: 1.4; opacity: .6; }}
  .d-panel {{ fill: none; stroke: {rule}; stroke-width: 1.2; stroke-dasharray: 5 4; }}
  .d-plane {{ fill: {accentSoft}; stroke: none; opacity: .5; }}
  .d-line {{ stroke: {ink}; stroke-width: 1.4; fill: none; opacity: .55; }}
  .d-lineA {{ stroke: {accent}; stroke-width: 1.6; fill: none; }}
  .d-lineW {{ stroke: {warn}; stroke-width: 1.4; fill: none; stroke-dasharray: 4 3; }}
  .d-lineW.solid {{ stroke-dasharray: 0; }}
  .d-rule {{ stroke: {ink}; stroke-width: 1; fill: none; opacity: .25; }}
  .mk {{ fill: {ink}; opacity: .55; }}
  .mkA {{ fill: {accent}; }}
  .t {{ font-size: 13px; font-weight: 500; }}
  .ts {{ font-family: {mono}; font-size: 10.5px; fill: {muted}; }}
  .tm {{ font-family: {mono}; font-size: 12px; font-weight: 500; }}
  .tl {{ font-size: 10px; font-weight: 600; letter-spacing: .1em; fill: {muted}; }}
  .tla {{ font-size: 10px; font-weight: 600; letter-spacing: .1em; fill: {accent}; }}
  .tlw {{ font-size: 10px; font-weight: 600; letter-spacing: .1em; fill: {warn}; }}
  .tn {{ font-family: {mono}; font-size: 10.5px; fill: {muted}; }}
  .tn.ink {{ fill: {ink}; }}
  .tn.ink2 {{ fill: {ink2}; }}
  .tn.accent {{ fill: {accent}; }}
  .tn.warn {{ fill: {warn}; }}
  .mid {{ text-anchor: middle; }}
  .end {{ text-anchor: end; }}
"""

HEAD = """<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" \
viewBox="0 0 {w} {h}" role="img" aria-label="{alt}">
  <title>{alt}</title>
  <style>{style}  </style>
  <defs>
    <marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" \
orient="auto-start-reverse"><path class="mk" d="M 0 1 L 9 5 L 0 9 z"/></marker>
    <marker id="aa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" \
orient="auto-start-reverse"><path class="mkA" d="M 0 1 L 9 5 L 0 9 z"/></marker>
  </defs>
  <rect width="{w}" height="{h}" fill="{bg}"/>
"""


# --- Fig. 1 -- the five strata ------------------------------------------

FIG1_ALT = (
    "Five layers: two harnesses -- the kepler console and kepler-bench -- drive "
    "run_session, which branches left into the model port and its four adapters "
    "and right into the tool registry, the tool modules and the algorithms. The "
    "right branch runs with no model, no key and no socket. The adapters never "
    "import the registry."
)
FIG1 = """
  <rect class="d-plane" x="514" y="230" width="336" height="282"/>

  <text class="tl mid" x="450" y="16">THE HARNESSES &#8212; TWO CONSUMERS, ONE LOOP</text>

  <rect class="d-box" x="70" y="28" width="300" height="62"/>
  <text class="t" x="86" y="52">kepler &#8212; the console</text>
  <text class="ts" x="86" y="72">tools/tui/ &#183; 2,944 lines &#183; Textual</text>

  <rect class="d-box" x="530" y="28" width="300" height="62"/>
  <text class="t" x="546" y="52">kepler-bench &#8212; the benchmark</text>
  <text class="ts" x="546" y="72">tools/bench/ &#183; 7,383 lines</text>

  <line class="d-line" x1="220" y1="90" x2="320" y2="140" marker-end="url(#a)"/>
  <line class="d-line" x1="680" y1="90" x2="580" y2="140" marker-end="url(#a)"/>
  <text class="tn mid" x="200" y="124">a human in the loop</text>
  <text class="tn mid" x="700" y="124">a recorder in the loop</text>

  <text class="tla mid" x="450" y="132">THE TURN-TAKING LAYER</text>
  <rect class="d-boxA" x="270" y="142" width="360" height="62"/>
  <text class="tm mid" x="450" y="170">run_session()</text>
  <text class="ts mid" x="450" y="189">tools/agent/ &#183; 1,206 lines &#8212; engine.py is 547 of them</text>

  <line class="d-line" x1="350" y1="204" x2="240" y2="244" marker-end="url(#a)"/>
  <line class="d-line" x1="550" y1="204" x2="660" y2="244" marker-end="url(#a)"/>
  <text class="tn end" x="330" y="234">complete()</text>
  <text class="tn" x="572" y="234">schemas + callables</text>

  <rect class="d-box" x="70" y="246" width="300" height="62"/>
  <text class="t" x="86" y="270">tools/llm/ &#8212; the model port</text>
  <text class="ts" x="86" y="290">2,568 lines &#183; provider-neutral</text>

  <rect class="d-box" x="530" y="246" width="300" height="62"/>
  <text class="t" x="546" y="270">tools/registry.py &#8212; the tool surface</text>
  <text class="ts" x="546" y="290">1,623 lines &#183; 55 schemas &#8596; 55 callables</text>

  <line class="d-lineW" x1="374" y1="277" x2="526" y2="277"/>
  <line class="d-lineW solid" x1="442" y1="269" x2="458" y2="285"/>
  <line class="d-lineW solid" x1="458" y1="269" x2="442" y2="285"/>
  <text class="tn warn mid" x="450" y="301">never imports</text>

  <line class="d-line" x1="220" y1="308" x2="220" y2="342" marker-end="url(#a)"/>
  <rect class="d-box" x="70" y="344" width="300" height="52"/>
  <text class="t" x="86" y="366">anthropic &#183; openai &#183; ollama &#183; gemini</text>
  <text class="ts" x="86" y="384">+ replay, test-only &#183; raw httpx, zero new deps</text>

  <line class="d-line" x1="680" y1="308" x2="680" y2="342" marker-end="url(#a)"/>
  <rect class="d-box" x="530" y="344" width="300" height="52"/>
  <text class="t" x="546" y="366">tools/*.py &#8212; 21 tool modules</text>
  <text class="ts" x="546" y="384">10,606 lines &#183; thin, typed, stateless</text>

  <line class="d-line" x1="680" y1="396" x2="680" y2="426" marker-end="url(#a)"/>
  <rect class="d-box" x="530" y="428" width="300" height="62"/>
  <text class="t" x="546" y="452">algorithms/ &#8212; the science</text>
  <text class="ts" x="546" y="472">26,891 lines &#183; 20,578 Python + 6,313 TypeScript</text>

  <text class="tla mid" x="682" y="506">NO MODEL &#183; NO KEY &#183; NO SOCKET</text>
"""


# --- Fig. 2 -- one turn --------------------------------------------------

FIG2_ALT = (
    "The control flow of one turn in run_session. Shaded as harness: drain "
    "pending input, the stop check, fault recording, argument validation, "
    "approval, the interrupt check, the cache lookup and the manifest save. "
    "Unshaded as turn-taking: the model call, the stop-reason branch, the tool "
    "dispatch, result serialisation and appending results to the conversation. "
    "Eight of the fourteen steps are harness steps."
)
FIG2 = """
  <rect class="d-box" x="180" y="6" width="13" height="13"/>
  <text class="tn" x="200" y="17">turn-taking &#8212; the irreducible part</text>
  <rect class="d-boxA" x="450" y="6" width="13" height="13"/>
  <text class="tn" x="470" y="17">harness &#8212; what this loop adds</text>

  <rect class="d-boxA" x="180" y="40" width="500" height="42"/>
  <text class="t" x="196" y="59">drain pending_input()</text>
  <text class="ts" x="196" y="75">a note typed mid-run is merged into the trailing user message</text>

  <line class="d-line" x1="430" y1="82" x2="430" y2="94" marker-end="url(#a)"/>
  <rect class="d-boxA" x="180" y="96" width="500" height="38"/>
  <text class="t" x="196" y="114">should_stop()</text>
  <text class="ts" x="196" y="128">&#8594; SessionFinished(interrupted)</text>

  <line class="d-line" x1="430" y1="134" x2="430" y2="146" marker-end="url(#a)"/>
  <rect class="d-box" x="180" y="148" width="500" height="54"/>
  <text class="tm" x="196" y="172">backend.complete(messages, tools, system, max_tokens)</text>
  <text class="ts" x="196" y="191">streams into on_text / on_thinking &#8212; reasoning is never merged into text</text>

  <line class="d-line" x1="430" y1="202" x2="430" y2="214" marker-end="url(#a)"/>
  <rect class="d-boxA" x="180" y="216" width="500" height="38"/>
  <text class="t" x="196" y="234">response.faults &#8594; ProtocolFault</text>
  <text class="ts" x="196" y="248">a max_tokens stop carrying tool calls means truncated arguments</text>

  <line class="d-line" x1="430" y1="254" x2="430" y2="266" marker-end="url(#a)"/>
  <rect class="d-box" x="180" y="268" width="500" height="42"/>
  <text class="t" x="196" y="294">stop_reason?</text>

  <line class="d-line" x1="680" y1="289" x2="736" y2="289" marker-end="url(#a)"/>
  <rect class="d-box" x="740" y="266" width="128" height="46"/>
  <text class="tn ink mid" x="804" y="285">end_turn &#8594;</text>
  <text class="tn ink mid" x="804" y="300">SessionFinished</text>

  <line class="d-line" x1="430" y1="310" x2="430" y2="328" marker-end="url(#a)"/>
  <text class="tn" x="440" y="324">tool_use</text>

  <rect class="d-panel" x="180" y="330" width="500" height="254"/>
  <text class="ts" x="196" y="350">for each call in response.tool_calls:</text>

  <rect class="d-boxA" x="196" y="358" width="468" height="26"/>
  <text class="tn ink" x="208" y="375">validate_tool_call(...) &#8212; a bad argument never reaches the function</text>
  <rect class="d-boxA" x="196" y="388" width="468" height="26"/>
  <text class="tn ink" x="208" y="405">approver(proposed) &#8212; DENY returns an error result instead</text>
  <rect class="d-boxA" x="196" y="418" width="468" height="26"/>
  <text class="tn ink" x="208" y="435">should_stop() &#8212; an interrupted call still answers its tool_use</text>
  <rect class="d-boxA" x="196" y="448" width="468" height="26"/>
  <text class="tn ink" x="208" y="465">make_cache_key(name, args) &#8212; a repeat costs no second call</text>
  <rect class="d-box" x="196" y="478" width="468" height="26"/>
  <text class="tn ink" x="208" y="495">functions[name](**arguments)</text>
  <rect class="d-box" x="196" y="508" width="468" height="26"/>
  <text class="tn ink" x="208" y="525">model_dump() &#8594; json &#8594; ToolResultBlock</text>
  <rect class="d-boxA" x="196" y="538" width="468" height="26"/>
  <text class="tn ink" x="208" y="555">session.save() &#8212; after every single call</text>

  <line class="d-line" x1="430" y1="584" x2="430" y2="602" marker-end="url(#a)"/>
  <rect class="d-box" x="180" y="604" width="500" height="42"/>
  <text class="t" x="196" y="630">messages.append(user, blocks = every tool_result)</text>

  <path class="d-line" d="M 430 646 L 430 668 L 130 668 L 130 61 L 176 61" marker-end="url(#a)"/>
  <text class="tn" x="14" y="336">next turn &#8212;</text>
  <text class="tn" x="14" y="350">max_turns = 20</text>
"""


# --- Fig. 3 -- what one tool call crosses --------------------------------

FIG3_ALT = (
    "One tool call descends through five layers: the model emits JSON, the loop "
    "validates approves and caches it, the registry maps the name to a callable, "
    "the tool module normalises inputs, and the algorithm computes. The result "
    "climbs back as a typed model, a dict, JSON text and a tool_result block. "
    "Nothing survives the call."
)
FIG3 = """
  <text class="tl end" x="138" y="62">THE MODEL</text>
  <rect class="d-box" x="150" y="30" width="580" height="54"/>
  <text class="tn ink" x="166" y="54">{"name": "compute_pulsar_periodogram",</text>
  <text class="tn ink" x="166" y="70"> "arguments": {"path": "...", "start": 0.2, "stop": 3.0, "steps": 20000}}</text>

  <text class="tl end" x="138" y="146">THE LOOP</text>
  <rect class="d-boxA" x="150" y="114" width="580" height="54"/>
  <text class="t" x="166" y="138">validate &#183; approve &#183; cache &#183; dispatch</text>
  <text class="ts" x="166" y="156">tools/agent/engine.py &#8212; nothing below runs if any gate refuses</text>

  <text class="tl end" x="138" y="230">THE REGISTRY</text>
  <rect class="d-box" x="150" y="198" width="580" height="54"/>
  <text class="tm" x="166" y="222">TOOL_FUNCTIONS[name]</text>
  <text class="ts" x="166" y="240">a dict of 55 names to 55 plain callables &#8212; no framework in between</text>

  <text class="tl end" x="138" y="314">THE TOOL</text>
  <rect class="d-box" x="150" y="282" width="580" height="54"/>
  <text class="t" x="166" y="306">tools/pulsar.py</text>
  <text class="ts" x="166" y="324">resolve the scan path, bound the frequency grid, build settings objects</text>

  <text class="tl end" x="138" y="398">THE ALGORITHM</text>
  <rect class="d-box" x="150" y="366" width="580" height="54"/>
  <text class="t" x="166" y="390">algorithms/pulsar/periodogram.py</text>
  <text class="ts" x="166" y="408">Lomb&#8211;Scargle over the scan &#8212; numpy, scipy, astropy</text>

  <line class="d-line" x1="250" y1="84" x2="250" y2="112" marker-end="url(#a)"/>
  <text class="tn" x="262" y="103">JSON arguments</text>
  <line class="d-line" x1="250" y1="168" x2="250" y2="196" marker-end="url(#a)"/>
  <text class="tn" x="262" y="187">a validated dict</text>
  <line class="d-line" x1="250" y1="252" x2="250" y2="280" marker-end="url(#a)"/>
  <text class="tn" x="262" y="271">**kwargs</text>
  <line class="d-line" x1="250" y1="336" x2="250" y2="364" marker-end="url(#a)"/>
  <text class="tn" x="262" y="355">ndarray, settings</text>

  <line class="d-lineA" x1="640" y1="364" x2="640" y2="338" marker-end="url(#aa)"/>
  <text class="tn accent end" x="626" y="355">peaks, snr, warnings</text>
  <line class="d-lineA" x1="640" y1="280" x2="640" y2="254" marker-end="url(#aa)"/>
  <text class="tn accent end" x="626" y="271">PeriodogramResult</text>
  <line class="d-lineA" x1="640" y1="196" x2="640" y2="170" marker-end="url(#aa)"/>
  <text class="tn accent end" x="626" y="187">model_dump() &#8594; dict</text>
  <line class="d-lineA" x1="640" y1="112" x2="640" y2="86" marker-end="url(#aa)"/>
  <text class="tn accent end" x="626" y="103">a tool_result block</text>

  <text class="tn warn mid" x="440" y="452">Nothing survives the call. The next one re-opens the file.</text>
"""


# --- Fig. 4 -- the tool plane -------------------------------------------

FIG4_ALT = (
    "The 55 registered tools split into 26 local, 22 remote and 7 mixed. Local "
    "tools run live because replaying a periodogram would let the task author "
    "rather than the data decide what the model got wrong. Remote tools are "
    "always replayed because every one opens a socket. Mixed tools are decided "
    "per call from the arguments. The classification is closed: an unclassified "
    "tool raises."
)
FIG4 = """
  <text class="tl" x="40" y="34">55 REGISTERED TOOLS, OVER 21 MODULES</text>

  <rect class="d-box" x="40" y="46" width="378" height="46"/>
  <text class="t mid" x="229" y="75">26 local</text>
  <rect class="d-boxA" x="418" y="46" width="320" height="46"/>
  <text class="t mid" x="578" y="75">22 remote</text>
  <rect class="d-boxW" x="738" y="46" width="102" height="46"/>
  <text class="t mid" x="789" y="75">7</text>

  <line class="d-line" x1="229" y1="92" x2="165" y2="118" marker-end="url(#a)"/>
  <line class="d-line" x1="578" y1="92" x2="440" y2="118" marker-end="url(#a)"/>
  <line class="d-line" x1="789" y1="92" x2="715" y2="118" marker-end="url(#a)"/>

  <text class="tl" x="40" y="140">CLASS L &#8212; RUN LIVE</text>
  <text class="tn ink2" x="40" y="162">Local and deterministic: they read the</text>
  <text class="tn ink2" x="40" y="178">bundled fixture tree and compute.</text>
  <text class="tn ink2" x="40" y="200">Replaying a periodogram would let the</text>
  <text class="tn ink2" x="40" y="216">task author, not the data, decide</text>
  <text class="tn ink2" x="40" y="232">whether a model's mistake is visible.</text>

  <text class="tla" x="315" y="140">CLASS R &#8212; ALWAYS REPLAYED</text>
  <text class="tn ink2" x="315" y="162">Every one opens a socket, so none is</text>
  <text class="tn ink2" x="315" y="178">ever executed inside a benchmark run;</text>
  <text class="tn ink2" x="315" y="200">each is replayed from a recorded</text>
  <text class="tn ink2" x="315" y="216">fixture. Includes one that merely looks</text>
  <text class="tn ink2" x="315" y="232">local: get_literature_cluster_params.</text>

  <text class="tlw" x="590" y="140">CLASS M &#8212; DECIDED PER CALL</text>
  <text class="tn ink2" x="590" y="162">Local code behind a network-capable</text>
  <text class="tn ink2" x="590" y="178">argument. A task must pin the offline</text>
  <text class="tn ink2" x="590" y="200">path in the call's own arguments</text>
  <text class="tn ink2" x="590" y="216">(use_field_cal=false; catalog_fixture</text>
  <text class="tn ink2" x="590" y="232">with compare_to) or it is replayed.</text>

  <line class="d-rule" x1="40" y1="256" x2="840" y2="256"/>
  <text class="tn ink2" x="40" y="278">The plane is closed: an unclassified tool raises rather than defaulting, and a test asserts it covers the whole registry.</text>
  <text class="tn ink2" x="40" y="294">A new registry tool must be classified in the same commit that adds it &#8212; otherwise the first new remote tool runs live, inside a run that believes it is offline.</text>
"""


# --- Fig. 5 -- wrapper vs. gated loop ------------------------------------

FIG5_ALT = (
    "Two panels side by side. On the left a plain turn-taking wrapper: the "
    "conversation, the model call, dispatch, append the result, repeat, with "
    "nothing between the steps. On the right Kepler's loop: the same four steps "
    "with seven gates sitting on the wires between them -- drain notes, the stop "
    "check, protocol faults, validate arguments, approve, cache, and save the "
    "manifest."
)
FIG5 = """
  <text class="tl" x="30" y="20">A TURN-TAKING WRAPPER</text>
  <text class="tn" x="30" y="38">about 80 lines &#183; unbounded, ungated</text>
  <rect class="d-frame" x="30" y="48" width="380" height="392"/>

  <rect class="d-box" x="110" y="60" width="240" height="44"/>
  <text class="t mid" x="230" y="87">the conversation</text>
  <rect class="d-box" x="110" y="150" width="240" height="44"/>
  <text class="t mid" x="230" y="177">model.complete()</text>
  <rect class="d-box" x="110" y="280" width="240" height="44"/>
  <text class="t mid" x="230" y="307">dispatch the call</text>
  <rect class="d-box" x="110" y="370" width="240" height="44"/>
  <text class="t mid" x="230" y="397">append the result</text>

  <line class="d-line" x1="230" y1="104" x2="230" y2="148" marker-end="url(#a)"/>
  <line class="d-line" x1="230" y1="194" x2="230" y2="278" marker-end="url(#a)"/>
  <line class="d-line" x1="230" y1="324" x2="230" y2="368" marker-end="url(#a)"/>
  <path class="d-line" d="M 110 392 L 60 392 L 60 82 L 106 82" marker-end="url(#a)"/>

  <text class="tla" x="470" y="20">KEPLER'S LOOP &#8212; engine.py, 547 LINES</text>
  <text class="tn" x="470" y="38">bounded at max_turns = 20 &#183; every call recorded</text>
  <rect class="d-frame" x="470" y="48" width="380" height="392"/>

  <rect class="d-box" x="550" y="60" width="240" height="44"/>
  <text class="t mid" x="670" y="87">the conversation</text>
  <rect class="d-box" x="550" y="150" width="240" height="44"/>
  <text class="t mid" x="670" y="177">model.complete()</text>
  <rect class="d-box" x="550" y="280" width="240" height="44"/>
  <text class="t mid" x="670" y="307">dispatch the call</text>
  <rect class="d-box" x="550" y="370" width="240" height="44"/>
  <text class="t mid" x="670" y="397">append the result</text>

  <line class="d-line" x1="670" y1="104" x2="670" y2="148" marker-end="url(#a)"/>
  <line class="d-line" x1="670" y1="194" x2="670" y2="278" marker-end="url(#a)"/>
  <line class="d-line" x1="670" y1="324" x2="670" y2="368" marker-end="url(#a)"/>
  <path class="d-line" d="M 550 392 L 500 392 L 500 82 L 546 82" marker-end="url(#a)"/>

  <rect class="d-boxA" x="600" y="106" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="119">drain notes</text>
  <rect class="d-boxA" x="600" y="128" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="141">stop?</text>

  <rect class="d-boxA" x="600" y="198" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="211">protocol faults</text>
  <rect class="d-boxA" x="600" y="220" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="233">validate arguments</text>
  <rect class="d-boxA" x="600" y="242" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="255">approve</text>
  <rect class="d-boxA" x="600" y="264" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="277">cache</text>

  <rect class="d-boxA" x="600" y="336" width="140" height="18" rx="9"/>
  <text class="tn ink mid" x="670" y="349">save the manifest</text>
"""


# --- Fig. 6 -- two harnesses, three seams --------------------------------

FIG6_ALT = (
    "run_session in the centre with three parameter seams: backend, approver and "
    "tool_functions. The console fills them with a live switchable backend, a "
    "policy approver backed by a modal a person answers, and all 55 tools live. "
    "The benchmark fills them with the model under test or a replay backend, "
    "auto-approve, and a tool plane of 26 live, 22 replayed and 7 decided per "
    "call."
)
FIG6 = """
  <text class="tl" x="30" y="52">KEPLER &#8212; THE CONSOLE</text>
  <text class="tn" x="30" y="72">a human in the loop</text>

  <text class="tl end" x="870" y="52">KEPLER-BENCH</text>
  <text class="tn end" x="870" y="72">a recorder in the loop</text>

  <rect class="d-boxA" x="330" y="90" width="240" height="252"/>
  <text class="tm mid" x="450" y="120">run_session()</text>
  <text class="ts mid" x="450" y="136">unchanged in both</text>

  <rect class="d-box" x="346" y="148" width="208" height="40"/>
  <text class="tn ink mid" x="450" y="173">backend =</text>
  <rect class="d-box" x="346" y="200" width="208" height="40"/>
  <text class="tn ink mid" x="450" y="225">approver =</text>
  <rect class="d-box" x="346" y="252" width="208" height="40"/>
  <text class="tn ink mid" x="450" y="277">tool_functions =</text>
  <text class="ts mid" x="450" y="318">+ on_delta &#183; pending_input</text>
  <text class="ts mid" x="450" y="333">&#183; should_stop</text>

  <rect class="d-box" x="30" y="148" width="270" height="40"/>
  <text class="tn ink" x="42" y="165">build_backend(spec)</text>
  <text class="ts" x="42" y="180">live; switchable mid-session with /backend</text>
  <rect class="d-box" x="30" y="200" width="270" height="40"/>
  <text class="tn ink" x="42" y="217">policy_approver(SessionPolicy)</text>
  <text class="ts" x="42" y="232">a modal &#8212; a person answers it</text>
  <rect class="d-box" x="30" y="252" width="270" height="40"/>
  <text class="tn ink" x="42" y="269">the default 55</text>
  <text class="ts" x="42" y="284">every tool runs live, against the real thing</text>

  <rect class="d-box" x="600" y="148" width="270" height="40"/>
  <text class="tn ink" x="612" y="165">the model under test</text>
  <text class="ts" x="612" y="180">or ReplayBackend, for a recorded transcript</text>
  <rect class="d-box" x="600" y="200" width="270" height="40"/>
  <text class="tn ink" x="612" y="217">auto_approve</text>
  <text class="ts" x="612" y="232">no human is present to ask</text>
  <rect class="d-box" x="600" y="252" width="270" height="40"/>
  <text class="tn ink" x="612" y="269">build_tool_plane(...)</text>
  <text class="ts" x="612" y="284">26 live &#183; 22 replayed &#183; 7 decided per call</text>

  <line class="d-lineA" x1="300" y1="168" x2="342" y2="168" marker-end="url(#aa)"/>
  <line class="d-lineA" x1="300" y1="220" x2="342" y2="220" marker-end="url(#aa)"/>
  <line class="d-lineA" x1="300" y1="272" x2="342" y2="272" marker-end="url(#aa)"/>
  <line class="d-lineA" x1="600" y1="168" x2="558" y2="168" marker-end="url(#aa)"/>
  <line class="d-lineA" x1="600" y1="220" x2="558" y2="220" marker-end="url(#aa)"/>
  <line class="d-lineA" x1="600" y1="272" x2="558" y2="272" marker-end="url(#aa)"/>

  <text class="tn ink2 mid" x="165" y="366">renders events; blocks the worker on a modal;</text>
  <text class="tn ink2 mid" x="165" y="382">queues mid-run notes; escape stops the turn</text>
  <text class="tn ink2 mid" x="735" y="366">writes events.jsonl, answer.txt, run.json;</text>
  <text class="tn ink2 mid" x="735" y="382">grades afterwards, separately from running</text>

  <text class="tn accent mid" x="450" y="418">Same function. Same 547 lines. The loop cannot tell which one called it.</text>
"""


FIGURES = [
    ("fig-1-strata", 900, 548, FIG1_ALT, FIG1),
    ("fig-2-one-turn", 880, 702, FIG2_ALT, FIG2),
    ("fig-3-tool-call", 880, 472, FIG3_ALT, FIG3),
    ("fig-4-tool-plane", 880, 304, FIG4_ALT, FIG4),
    ("fig-5-gates", 880, 472, FIG5_ALT, FIG5),
    ("fig-6-seams", 900, 446, FIG6_ALT, FIG6),
]


def main() -> None:
    for name, width, height, alt, body in FIGURES:
        for theme, palette in PALETTES.items():
            style = STYLE.format(sans=SANS, mono=MONO, **palette)
            head = HEAD.format(
                w=width, h=height, alt=alt, style=style, bg=palette["bg"]
            )
            path = OUT / f"{name}-{theme}.svg"
            path.write_text(head + body + "</svg>\n", encoding="utf-8")
            print(f"wrote {path.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
