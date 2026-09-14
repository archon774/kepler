"""Regenerate the benchmark figures from the committed report JSON.

    uv run python docs/working/figures/make.py

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

REPORT = json.loads(Path("docs/working/benchmark-report.json").read_text())
OUT = Path("docs/working/figures")

# Validated palette (dataviz skill reference instance).
SERIES = {"anthropic/claude-sonnet-5": "#2a78d6",      # blue
          "ollama/qwen3.8:27b-mlx":    "#eb6834",      # orange
          "ollama/qwen3.5:9b":         "#1baf7a"}      # aqua
SHORT = {k: k.split("/")[-1] for k in SERIES}
# Sequential blue ramp, light -> dark, for 0..3 correct.
RAMP = ["#e9e9e6", "#9ec5f4", "#5598e7", "#256abf"]
INK, INK2, MUTED, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#fcfcfb"
GRID = "#dededa"

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

# ------------------------------------------------------------ figures 3 & 4
# Form: bars. One measure, one axis. Speed and cost are two prices for the same
# answer and get a chart each -- putting them on shared axes would be the
# dual-axis mistake, and normalising them into one score would hide that only
# correctness has a baseline.
def fig_cost(key, title, subtitle, fmt, note, filename):
    rows = [(b, REPORT["matrix"][b][key]) for b in backends
            if REPORT["matrix"].get(b, {}).get(key)]
    rows.sort(key=lambda r: r[1])
    top = max(v for _, v in rows)
    left, y0, rowh, barh = 190, 84, 46, 26
    plot_w = 400
    import textwrap
    note_lines = textwrap.wrap(note, 96)
    w = left + plot_w + 130
    h = y0 + len(rows)*rowh + 26 + 15*len(note_lines)
    p = [f'<text x="20" y="30" font-size="15" font-weight="700" fill="{INK}">'
         f'{esc(title)}</text>',
         f'<text x="20" y="50" font-size="12" fill="{INK2}">{esc(subtitle)}</text>']
    for i, (b, v) in enumerate(rows):
        y = y0 + i*rowh
        p.append(f'<text x="{left-12}" y="{y+barh-8}" font-size="12" '
                 f'text-anchor="end" fill="{INK}">{esc(SHORT[b])}</text>')
        bw = v/top*plot_w
        p.append(f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{barh}" rx="4" '
                 f'fill="{SERIES[b]}"><title>{esc(SHORT[b])}: {fmt(v)}</title></rect>')
        p.append(f'<text x="{left+bw+9:.1f}" y="{y+barh-8}" font-size="12" '
                 f'font-weight="600" fill="{INK}">{esc(fmt(v))}</text>')
        if i:
            ratio = v / rows[0][1]
            p.append(f'<text x="{left+bw+9:.1f}" y="{y+barh+7}" font-size="10.5" '
                     f'fill="{MUTED}">{ratio:.1f}x the best</text>')
    base = y0 + len(rows)*rowh + 20
    for k, line in enumerate(note_lines):
        p.append(f'<text x="20" y="{base + k*15}" font-size="11" '
                 f'fill="{MUTED}">{esc(line)}</text>')
    write(filename, svg(w, h, "".join(p), title, subtitle + " " + note))

fig_cost("seconds_per_answer", "Seconds to a correct answer",
         "First attempt at each task. Lower is better.",
         lambda v: f"{v:,.0f}s",
         "A repeat of the same task reuses the provider's prefix cache, so only "
         "first attempts are counted. Hosted API against a local daemon: this "
         "measures where a model runs as much as the model.",
         "speed")

fig_cost("tokens_per_answer", "Tokens to a correct answer",
         "Input plus output, on sessions that reached a passing answer. Lower is better.",
         lambda v: f"{v:,.0f}",
         "Tokens spent on sessions that never reached an answer are excluded here "
         "and reported separately.",
         "cost")
