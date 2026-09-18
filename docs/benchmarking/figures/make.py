"""Regenerate the benchmark figures from the committed report JSON.

    uv run python docs/benchmarking/figures/make.py

Lives beside the figures rather than in ``tools/bench/`` because it is
documentation tooling: it reads a committed report and writes PNG into this
directory, and nothing in the harness imports it. Deliberately outside the
package so it never has to be classified in the tool plane.

Palette and marks follow the validated reference instance -- categorical hues
assigned in fixed order and never cycled, one sequential blue ramp for the
matrix, text in ink tokens rather than series colours, and a non-colour
secondary encoding (the rule under a cell) for the route marks so the matrix
survives a colour-blind reader and a monochrome print.
"""
import json, collections
from pathlib import Path

REPORT = json.loads(Path("docs/benchmarking/report.json").read_text())
OUT = Path("docs/benchmarking/figures")

# Validated palette (dataviz skill reference instance).
SERIES = {"anthropic/claude-sonnet-5": "#2a78d6",      # blue
          "ollama/qwen3.8:27b-mlx":    "#eb6834",      # orange
          "ollama/qwen3.5:9b":         "#1baf7a"}      # aqua
SHORT = {k: k.split("/")[-1] for k in SERIES}
# Sequential blue ramp, light -> dark, for 0..3 correct.
RAMP = ["#e9e9e6", "#9ec5f4", "#5598e7", "#256abf"]
INK, INK2, MUTED, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#fcfcfb"
GRID = "#dededa"

#: The outcome ramp, for "what happened to this session" (figure 1).
#:
#: Deliberately **greys, not a second set of hues**. Every hue in this document
#: means one model and nothing else -- colour follows the entity -- so a stacked
#: bar whose non-correct segments were coloured would ask the reader to hold two
#: colour languages at once. Correct is drawn in the model's own hue and the
#: rest desaturates away from it, which makes "how much of this bar is coloured"
#: readable as "how often it works" with no legend lookup at all.
#:
#: Monotonic in OKLab lightness -- 0.534, 0.659, 0.779, 0.891 against a 0.991
#: surface -- so the ramp survives greyscale and every form of colour blindness
#: by construction. Every segment is direct-labelled regardless.
OUTCOME = {"wrong answer":     "#6e6d69",
           "said nothing":     "#93928d",
           "ran out of turns": "#b8b7b2",
           "harness error":    "#dcdbd6"}

def esc(s): return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")


#: Raster width. Twice the natural viewBox so the figure stays sharp on a
#: high-density display.
PNG_SCALE = 2


def write(stem: str, markup: str) -> None:
    """Rasterise one figure to PNG.

    The SVG is piped to rsvg-convert rather than written out: PNG is the only
    committed format, so an SVG on disk would be an intermediate that could
    drift from the figure beside it without anything noticing.
    """

    import re
    import subprocess

    width = int(re.search(r'width="(\d+)"', markup).group(1))
    png_path = OUT / f"{stem}.png"
    try:
        subprocess.run(
            ["rsvg-convert", "-w", str(width * PNG_SCALE), "-o", str(png_path)],
            input=markup.encode("utf-8"), check=True, capture_output=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - operator's toolchain
        raise SystemExit(
            "rsvg-convert is not on PATH; it is what turns these figures into "
            "the PNGs the document references (dnf install librsvg2-tools)"
        ) from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise SystemExit(
            f"rsvg-convert failed on {stem}: {exc.stderr.decode(errors='replace')}"
        ) from exc
    print(f"wrote {png_path.name}")


def svg(w, h, body, title, desc):
    """One figure's markup. Title and desc are the accessible name and
    description; a reader on a screen reader gets the finding, not "image"."""

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" aria-labelledby="t d" '
            f'font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif">'
            f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>'
            f'<rect width="{w}" height="{h}" fill="{SURFACE}"/>{body}</svg>')


cells = {}
for row in REPORT["per_task"]:
    key = (row["task_id"], row["backend"])
    c = cells.setdefault(key, {"n": 0, "p": 0, "traj": 0, "dev": 0, "inc": 0})
    c["n"] += 1
    if row["incomplete"]: c["inc"] += 1
    elif row["passed"]: c["p"] += 1
    c["traj"] += row["trajectory_failures"] or 0
    c["dev"] += row["trajectory_deviations"] or 0

tasks = sorted({t for t, _ in cells})
backends = [b for b in SERIES if any((t, b) in cells for t in tasks)]


# ---------------------------------------------------------------- figure 1
# Form: one stacked bar per model, parts of a whole. The first question anyone
# asks is "how often does this actually work", and answering it from a 16x3
# matrix means counting cells. A bar answers it without arithmetic.
#
# The denominator is the trap this figure has to disarm rather than hide. The
# correctness board is 37 of *43* for sonnet, not 37 of 48: a session that hit
# an API error or ran out of turns did not answer badly, it did not answer, and
# neither is scored as a low pass rate. So the bar is drawn over all 48
# attempts -- that is what was spent -- the two unscored segments are detached
# with a dashed outline under their own bracket, and the headline percentage
# states its own denominator rather than leaving the reader to divide by 48.
def fig_outcomes():
    order = ["wrong answer", "said nothing", "ran out of turns", "harness error"]
    # Outside the correctness denominator, and drawn dashed to say so.
    UNSCORED = ("ran out of turns", "harness error")
    counts = {b: collections.Counter() for b in backends}
    for row in REPORT["per_task"]:
        if row["passed"]:
            key = "correct"
        elif "empty_answer" in row["answer_failures"]:
            key = "said nothing"
        elif row["outcome"] == "error":
            key = "harness error"
        elif row["incomplete"]:
            key = "ran out of turns"
        else:
            key = "wrong answer"
        counts[row["backend"]][key] += 1

    left, y0, rowh, barh, gap = 152, 112, 68, 34, 2
    plot_w = 560
    w, h = left + plot_w + 132, y0 + len(backends)*rowh + 70
    total = 48
    p = [f'<text x="20" y="32" font-size="16" font-weight="700" fill="{INK}">'
         f'How often does each model reach a correct answer?</text>',
         f'<text x="20" y="53" font-size="12.5" fill="{INK2}">'
         f'All 48 attempts per model: 16 tasks asked 3 times each.</text>']

    # Legend. Correct is shown in grey outline here because it takes the
    # model's own colour in the plot; the swatch would otherwise claim one
    # model's hue for a category shared by all three.
    lx = 20
    p.append(f'<rect x="{lx}" y="{y0-32}" width="11" height="11" rx="2.5" '
             f'fill="none" stroke="{INK2}" stroke-width="1.5"/>')
    p.append(f'<text x="{lx+17}" y="{y0-22}" font-size="11.5" fill="{INK2}">'
             f'correct (model\u2019s colour)</text>')
    lx += 152
    for label in order:
        dash = (' stroke="#b0afaa" stroke-dasharray="2 2"'
                if label in UNSCORED else '')
        p.append(f'<rect x="{lx}" y="{y0-32}" width="11" height="11" rx="2.5" '
                 f'fill="{OUTCOME[label]}"{dash}/>')
        p.append(f'<text x="{lx+17}" y="{y0-22}" font-size="11.5" fill="{INK2}">'
                 f'{esc(label)}</text>')
        lx += 22 + 6.6*len(label)

    for i, b in enumerate(backends):
        y = y0 + i*rowh
        p.append(f'<text x="{left-14}" y="{y+barh/2+5:.0f}" font-size="12.5" '
                 f'font-weight="600" text-anchor="end" fill="{INK}">'
                 f'{esc(SHORT[b])}</text>')
        x = left
        for label in ["correct"] + order:
            v = counts[b][label]
            if not v:
                continue
            seg = v/total*plot_w - gap
            fill = SERIES[b] if label == "correct" else OUTCOME[label]
            extra = (' stroke="#b0afaa" stroke-dasharray="3 3" stroke-width="1"'
                     if label in UNSCORED else '')
            p.append(f'<rect x="{x:.1f}" y="{y}" width="{seg:.1f}" height="{barh}" '
                     f'rx="4" fill="{fill}"{extra}><title>{esc(SHORT[b])}: {v} of '
                     f'{total} sessions \u2014 {esc(label)}</title></rect>')
            # Direct label inside the segment where it fits, under it where it
            # does not. A count on every segment is what makes the grey ramp
            # legible without reading the legend.
            tone = "#ffffff" if label == "correct" else (INK2 if label in UNSCORED else INK)
            if seg > 26:
                p.append(f'<text x="{x+seg/2:.1f}" y="{y+barh/2+5:.0f}" font-size="12" '
                         f'font-weight="600" text-anchor="middle" fill="{tone}">{v}</text>')
            else:
                p.append(f'<text x="{x+seg/2:.1f}" y="{y+barh+13:.0f}" font-size="11" '
                         f'text-anchor="middle" fill="{INK2}">{v}</text>')
            x += seg + gap
        scored = total - sum(counts[b][k] for k in UNSCORED)
        pct = counts[b]["correct"]/scored*100
        p.append(f'<text x="{left+plot_w+14}" y="{y+barh/2:.0f}" font-size="17" '
                 f'font-weight="700" fill="{INK}">{pct:.0f}%</text>')
        p.append(f'<text x="{left+plot_w+14}" y="{y+barh/2+15:.0f}" font-size="10.5" '
                 f'fill="{MUTED}">of {scored} scored</text>')

    base = y0 + len(backends)*rowh + 14
    p.append(f'<text x="20" y="{base}" font-size="11" fill="{MUTED}">'
             f'Correct means it answered and failed no hard check. The dashed '
             f'segments never produced an answer at all and are</text>')
    p.append(f'<text x="20" y="{base+15}" font-size="11" fill="{MUTED}">'
             f'left out of the percentage \u2014 an outage and an exhausted turn cap '
             f'are not wrong answers \u2014 so the denominators differ.</text>')
    return svg(w, h, "".join(p), "How often each model reaches a correct answer",
               "One stacked bar per model over 48 attempts, split into correct, "
               "wrong answer, said nothing, ran out of turns, and harness error.")

write("outcomes", fig_outcomes())

# ---------------------------------------------------------------- figure 1
# Form: a matrix. The data is one bounded count per (task, model) cell and the
# job is comparison in two directions at once, which is what a matrix is for.
def fig_matrix():
    left, top, cw, ch, gap = 300, 78, 132, 30, 2
    w = left + len(backends)*(cw+gap) + 28
    h = top + len(tasks)*(ch+gap) + 76
    p = [f'<text x="20" y="30" font-size="15" font-weight="700" fill="{INK}">'
         f'Correct answers out of 3 repeats</text>',
         f'<text x="20" y="50" font-size="12" fill="{INK2}">'
         f'A bar under a cell marks a wrong route: the answer may still be right.</text>']
    for j, b in enumerate(backends):
        x = left + j*(cw+gap) + cw/2
        p.append(f'<text x="{x:.0f}" y="{top-10}" font-size="12" font-weight="600" '
                 f'text-anchor="middle" fill="{INK}">{esc(SHORT[b])}</text>')
    for i, t in enumerate(tasks):
        y = top + i*(ch+gap)
        p.append(f'<text x="{left-12}" y="{y+ch/2+4}" font-size="11.5" '
                 f'text-anchor="end" fill="{INK2}">{esc(t)}</text>')
        for j, b in enumerate(backends):
            c = cells.get((t, b))
            x = left + j*(cw+gap)
            if c is None:
                p.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="4" '
                         f'fill="none" stroke="{GRID}"/>')
                continue
            fill = RAMP[min(3, c["p"])]
            # Text stays in ink tokens, never the series colour.
            tone = "#ffffff" if c["p"] >= 2 else INK
            p.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="4" fill="{fill}"/>')
            p.append(f'<text x="{x+cw/2:.0f}" y="{y+ch/2+4}" font-size="12.5" '
                     f'font-weight="600" text-anchor="middle" fill="{tone}">'
                     f'{c["p"]}/{c["n"]}</text>')
            marks = []
            if c["traj"]: marks.append("forbidden call or argument rule broken")
            if c["dev"]: marks.append("declared call skipped or out of order")
            if c["inc"]: marks.append("never answered")
            if marks:
                # Secondary encoding, not colour: a bar plus a title for hover.
                # The mark must read on both a pale and a saturated cell, so
                # it flips with the fill rather than sitting at one opacity.
                mark_fill = "#ffffff" if c["p"] >= 2 else INK
                p.append(f'<rect x="{x+6}" y="{y+ch-5}" width="{cw-12}" height="3" '
                         f'rx="1.5" fill="{mark_fill}" opacity="0.9">'
                         f'<title>{esc(", ".join(marks))}</title></rect>')
    ly = top + len(tasks)*(ch+gap) + 24
    p.append(f'<text x="20" y="{ly}" font-size="11.5" fill="{INK2}">Correct:</text>')
    for k, hexv in enumerate(RAMP):
        x = 76 + k*64
        p.append(f'<rect x="{x}" y="{ly-11}" width="16" height="14" rx="3" fill="{hexv}"/>')
        p.append(f'<text x="{x+22}" y="{ly}" font-size="11.5" fill="{INK2}">{k}/3</text>')
    p.append(f'<rect x="{76+4*64}" y="{ly-4}" width="16" height="3" rx="1.5" '
             f'fill="{INK}" opacity="0.72"/>')
    p.append(f'<text x="{76+4*64+22}" y="{ly}" font-size="11.5" fill="{INK2}">'
             f'wrong route</text>')
    return svg(w, h, "".join(p), "Correct answers per task per model",
               "Matrix of 16 tasks by 3 models; each cell is correct answers out of "
               "3 repeats, with a bar marking a wrong tool-calling route.")

write("per-task-matrix", fig_matrix())

# ---------------------------------------------------------------- figure 2
# Form: grouped bars. The data is a count per (check, model) and the job is
# identity -- which failure mode belongs to which model -- so categorical hues,
# assigned in fixed order and never cycled.
def fig_failures():
    counts = collections.defaultdict(collections.Counter)
    for row in REPORT["per_task"]:
        for check in row["answer_failures"]:
            # The grader already records an unanswered session as its own
            # check; naming it twice would double-count the same event.
            label = "did not answer" if check == "incomplete" else check
            counts[label][row["backend"]] += 1
    checks = sorted(counts, key=lambda c: -sum(counts[c].values()))
    top = max(max(c.values()) for c in counts.values())

    left, top_y, rowh, barh, gap = 210, 84, 62, 15, 3
    plot_w = 430
    w, h = left + plot_w + 40, top_y + len(checks)*rowh + 30
    p = [f'<text x="20" y="30" font-size="15" font-weight="700" fill="{INK}">'
         f'Which checks each model failed</text>',
         f'<text x="20" y="50" font-size="12" fill="{INK2}">'
         f'Sessions, out of 48 per model. Shorter is better.</text>']
    for j, b in enumerate(backends):   # legend: >=2 series always gets one
        x = 20 + j*175
        p.append(f'<rect x="{x}" y="{top_y-24}" width="11" height="11" rx="2.5" '
                 f'fill="{SERIES[b]}"/>')
        p.append(f'<text x="{x+17}" y="{top_y-14}" font-size="11.5" fill="{INK2}">'
                 f'{esc(SHORT[b])}</text>')
    for i, check in enumerate(checks):
        y = top_y + i*rowh
        p.append(f'<text x="{left-12}" y="{y+22}" font-size="11.5" '
                 f'text-anchor="end" fill="{INK}">{esc(check)}</text>')
        for j, b in enumerate(backends):
            v = counts[check].get(b, 0)
            by = y + j*(barh+gap)
            bw = max(0.0, v/top*plot_w)
            if v:
                # 4px rounded data-end, anchored to the baseline.
                p.append(f'<rect x="{left}" y="{by}" width="{bw:.1f}" height="{barh}" '
                         f'rx="4" fill="{SERIES[b]}"><title>{esc(SHORT[b])}: '
                         f'{v} session(s) failed {esc(check)}</title></rect>')
                p.append(f'<text x="{left+bw+7:.1f}" y="{by+barh-3}" font-size="11" '
                         f'fill="{INK2}">{v}</text>')
            else:
                p.append(f'<text x="{left+3}" y="{by+barh-3}" font-size="11" '
                         f'fill="{MUTED}">0</text>')
        if i:
            p.insert(2, f'<line x1="{left}" y1="{y-6}" x2="{left+plot_w}" y2="{y-6}" '
                        f'stroke="{GRID}" stroke-width="1"/>')
    return svg(w, h, "".join(p), "Failure modes by model",
               "Grouped bars: how many sessions each model failed each answer check.")

write("failure-modes", fig_failures())

# ---------------------------------------------------------------- figure 3
# Form: small multiples -- three panels, one measure each, models in the same
# order in every panel. This is the shape of the result, so it is the shape of
# the figure: three boards that are never blended, because only correctness has
# a baseline. A second and a token do not, so those two are rankings among these
# backends and nothing more.
#
# Three panels rather than one chart with three bars per model, because the
# measures share no scale. Putting a percentage, a duration and a token count on
# one axis is the dual-axis mistake wearing a disguise; normalising them into a
# composite would hide that two of the three have no zero to be measured from.
#
# The point the figure exists to make is the rank flip. Model order is fixed
# down every panel and each bar carries its standing, so "first here, last
# there" is visible without reading a number.
#: ``full`` is the axis maximum, or ``None`` to scale the panel to its own
#: largest bar. Correctness pins it to 1.0 **because it is the one measure with
#: a baseline**: 86% drawn as a full-width bar would read as a perfect score,
#: and the whole reason the three boards are kept apart is that this one means
#: something on its own. Speed and cost have no ceiling to draw, so they scale
#: to the field -- which is exactly what "a standing among these backends" is.
BOARDS = [
    ("Correctness", "share of scored sessions", "higher is better",
     lambda m: m["pass_rate"], lambda v: f"{v*100:.0f}%", True, 1.0),
    ("Speed", "seconds to an answer", "lower is better",
     lambda m: m["seconds_per_answer"], lambda v: f"{v:,.0f}s", False, None),
    ("Cost", "tokens to an answer", "lower is better",
     lambda m: m["tokens_per_answer"], lambda v: f"{v/1000:,.0f}k", False, None),
]


def fig_boards():
    left, y0, panel_w, panel_gap = 150, 128, 236, 34
    rowh, barh = 58, 28
    w = left + len(BOARDS)*panel_w + (len(BOARDS)-1)*panel_gap + 24
    h = y0 + len(backends)*rowh + 92
    p = [f'<text x="20" y="32" font-size="16" font-weight="700" fill="{INK}">'
         f'Three measurements, three boards \u2014 and no overall winner</text>',
         f'<text x="20" y="53" font-size="12.5" fill="{INK2}">'
         f'Each model is first on one board and last on another. The '
         f'disagreement is the result, not a tie to break.</text>']

    for i, b in enumerate(backends):
        y = y0 + i*rowh
        p.append(f'<text x="{left-16}" y="{y+barh/2+5:.0f}" font-size="12.5" '
                 f'font-weight="600" text-anchor="end" fill="{INK}">'
                 f'{esc(SHORT[b])}</text>')

    for j, (name, measure, sense, get, fmt, higher, full) in enumerate(BOARDS):
        px = left + j*(panel_w + panel_gap)
        values = {b: get(REPORT["matrix"][b]) for b in backends}
        top = full or max(values.values())
        ranking = sorted(backends, key=lambda b: -values[b] if higher else values[b])

        p.append(f'<text x="{px}" y="{y0-46}" font-size="13" font-weight="700" '
                 f'fill="{INK}">{esc(name)}</text>')
        p.append(f'<text x="{px}" y="{y0-30}" font-size="11" fill="{INK2}">'
                 f'{esc(measure)}</text>')
        # A longer bar is better in one panel and worse in two, which is the
        # honest drawing -- length is the value -- and also the one thing a
        # reader can get backwards at a glance. So the sense carries an arrow
        # and sits in ink, not in the muted note tone.
        arrow = "\u25b2" if higher else "\u25bc"
        p.append(f'<text x="{px}" y="{y0-16}" font-size="11" font-weight="600" '
                 f'fill="{INK2}">{arrow} {esc(sense)}</text>')
        if full:
            # The ceiling, drawn as an axis rule: without it a panel scaled to
            # its own maximum says the leader is perfect.
            fx = px + panel_w - 96
            p.append(f'<line x1="{fx}" y1="{y0-6}" x2="{fx}" '
                     f'y2="{y0+(len(backends)-1)*rowh+barh+4}" stroke="{GRID}" '
                     f'stroke-width="1" stroke-dasharray="3 3"/>')
            p.append(f'<text x="{fx}" y="{y0+(len(backends)-1)*rowh+barh+18}" '
                     f'font-size="10" text-anchor="middle" fill="{MUTED}">100%</text>')
        p.append(f'<line x1="{px}" y1="{y0-8}" x2="{px+panel_w-20}" y2="{y0-8}" '
                 f'stroke="{GRID}" stroke-width="1"/>')

        for i, b in enumerate(backends):
            y = y0 + i*rowh
            v = values[b]
            bw = max(3.0, v/top*(panel_w-96))
            place = ranking.index(b) + 1
            p.append(f'<rect x="{px}" y="{y}" width="{bw:.1f}" height="{barh}" '
                     f'rx="4" fill="{SERIES[b]}"><title>{esc(SHORT[b])} \u2014 '
                     f'{esc(name)}: {esc(fmt(v))}, {place} of {len(backends)}'
                     f'</title></rect>')
            p.append(f'<text x="{px+bw+9:.1f}" y="{y+barh/2+5:.0f}" font-size="12.5" '
                     f'font-weight="700" fill="{INK}">{esc(fmt(v))}</text>')
            # The standing, as a word rather than a colour: this is what the
            # figure is for, and it has to survive greyscale.
            chip = {1: "best", 2: "2nd", 3: "3rd"}[place]
            weight = "700" if place == 1 else "400"
            p.append(f'<text x="{px+bw+9:.1f}" y="{y+barh/2+19:.0f}" font-size="10.5" '
                     f'font-weight="{weight}" fill="{INK2 if place == 1 else MUTED}">'
                     f'{chip}</text>')

    base = y0 + len(backends)*rowh + 26
    for k, line in enumerate([
        "Only correctness has a baseline: 100% means every question answered, whoever else was measured. "
        "There is no",
        "perfectly fast and no free token, so speed and cost are standings among these three backends and "
        "move if a fourth",
        "is added. Speed counts first attempts only \u2014 a repeat reuses the provider\u2019s prefix cache. Both "
        "count only sessions",
        "that reached a correct answer; tokens spent without one are reported separately.",
    ]):
        p.append(f'<text x="20" y="{base + k*15}" font-size="11" fill="{MUTED}">'
                 f'{line}</text>')
    return svg(w, h, "".join(p), "Three boards: correctness, speed and cost",
               "Small multiples. Each model is ranked first on one measure and "
               "last on another, so no single ordering of the three exists.")


write("three-boards", fig_boards())


# ---------------------------------------------------------------- figure 4
# Form: a sorted bar, one per task. Not a model comparison at all -- it is the
# shape of the *corpus*, and it is here so a reader does not read 86% as a
# property of a model when it is partly a property of what was asked.
#
# No colour judgement: every bar is one hue and the reading ("nobody is
# separated by these four", "this one defeats everybody") is carried by text.
# Encoding that verdict in a hue would bake an opinion about the corpus into
# the palette, where it could not be argued with.
def fig_difficulty():
    total = collections.Counter()
    runs = collections.Counter()
    for row in REPORT["per_task"]:
        runs[row["task_id"]] += 1
        if row["passed"]:
            total[row["task_id"]] += 1
    order = sorted(runs, key=lambda t: (-total[t], t))
    n = max(runs.values())

    left, y0, rowh, barh = 292, 96, 26, 17
    plot_w = 300
    w, h = left + plot_w + 210, y0 + len(order)*rowh + 74
    p = [f'<text x="20" y="32" font-size="16" font-weight="700" fill="{INK}">'
         f'What the 16 tasks actually separate</text>',
         f'<text x="20" y="53" font-size="12.5" fill="{INK2}">'
         f'Correct sessions per task, all three models pooled \u2014 out of 9 '
         f'(3 models \u00d7 3 repeats).</text>']
    for k in range(0, n+1, 3):
        x = left + k/n*plot_w
        p.append(f'<line x1="{x:.1f}" y1="{y0-10}" x2="{x:.1f}" '
                 f'y2="{y0+len(order)*rowh-6}" stroke="{GRID}" stroke-width="1"/>')
        p.append(f'<text x="{x:.1f}" y="{y0-16}" font-size="10.5" '
                 f'text-anchor="middle" fill="{MUTED}">{k}</text>')

    for i, t in enumerate(order):
        y = y0 + i*rowh
        p.append(f'<text x="{left-12}" y="{y+barh-4}" font-size="11.5" '
                 f'text-anchor="end" fill="{INK}">{esc(t)}</text>')
        bw = total[t]/n*plot_w
        if bw:
            p.append(f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{barh}" '
                     f'rx="4" fill="{RAMP[3]}"><title>{esc(t)}: {total[t]} of '
                     f'{runs[t]} sessions correct</title></rect>')
            p.append(f'<text x="{left+bw+8:.1f}" y="{y+barh-4}" font-size="11" '
                     f'fill="{INK2}">{total[t]}</text>')
        else:
            p.append(f'<text x="{left+4}" y="{y+barh-4}" font-size="11" '
                     f'font-weight="700" fill="{INK}">0</text>')

    # Brackets, drawn where the groups actually fall rather than at fixed rows.
    def bracket(first, last, label, detail):
        x = left + plot_w + 26
        y1, y2 = y0 + first*rowh - 2, y0 + last*rowh + barh + 2
        p.append(f'<path d="M{x} {y1} h7 V{y2} h-7" fill="none" stroke="{GRID}" '
                 f'stroke-width="1.5"/>')
        mid = (y1 + y2)/2
        p.append(f'<text x="{x+13}" y="{mid-1}" font-size="11.5" '
                 f'font-weight="600" fill="{INK}">{esc(label)}</text>')
        p.append(f'<text x="{x+13}" y="{mid+13}" font-size="10.5" fill="{MUTED}">'
                 f'{esc(detail)}</text>')

    perfect = [t for t in order if total[t] == runs[t]]
    zero = [t for t in order if total[t] == 0]
    if perfect:
        bracket(0, len(perfect)-1, f"{len(perfect)} separate nobody",
                "every model, every repeat")
    if zero:
        bracket(len(order)-len(zero), len(order)-1,
                f"{len(zero)} defeats everybody", "no model, any repeat")
    middle = len(order) - len(perfect) - len(zero)
    if middle:
        bracket(len(perfect), len(order)-len(zero)-1,
                f"{middle} do the separating", "this is the measurement")

    base = y0 + len(order)*rowh + 30
    p.append(f'<text x="20" y="{base}" font-size="11" fill="{MUTED}">'
             f'These are hand-picked probes of documented failure modes, not a '
             f'sample of everyday tool calls, so a rate over them is</text>')
    p.append(f'<text x="20" y="{base+15}" font-size="11" fill="{MUTED}">'
             f'not a rate over those. The four at the top still measure real '
             f'behaviours \u2014 they just do not tell these three models apart.</text>')
    return svg(w, h, "".join(p), "What the 16 tasks separate",
               "Tasks sorted by how many of the 9 pooled sessions were correct: "
               "four are passed by every model, one by none, eleven discriminate.")


write("task-difficulty", fig_difficulty())
