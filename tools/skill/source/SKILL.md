# Kepler astronomy tools

Kepler is 55 astronomy tools: thin clients over eight remote databases
(SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS) and local pipelines that run
on data already on this machine — a radio-pulsar chain, a variable-star chain,
optical frames with plate solving, photometry and zero-point calibration, an
HR-diagram fit, and radio-source identification.

Every tool returns a **bounded inline preview** plus, for most, an **artifact
path**: the complete result, written to a local file. A preview is a sample,
never the whole answer. When the complete data matters, read the artifact and
give its path.

This file carries the rules that span tools. Each tool's own description
carries the rules that belong to it; read it. The per-domain references below
carry the workflow for one area and are worth reading before working in it.

| Reference | Read before |
| --- | --- |
| [`references/pulsar.md`](references/pulsar.md) | any pulsar or variable-star period work |
| [`references/databases.md`](references/databases.md) | querying SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA or ADS |
| [`references/optical.md`](references/optical.md) | FITS frames, plate solving, photometry, zero points |
| [`references/hr.md`](references/hr.md) | an HR diagram or cluster parameters |
| [`references/radio.md`](references/radio.md) | a radio FITS map or a source's radio spectrum |
| [`references/checkout.md`](references/checkout.md) | calling the tools from a Kepler checkout rather than through a tool server |

Every rule below restates guidance whose authority is the system prompt of
Kepler's own agent loop, `tools/agent/prompt.py`, and names the section it
comes from. Where the two ever disagree, the prompt is right and this file is
stale.

## 1. There is no archive behind the local tools

The pulsar, variable-star, optical-frame and photometry tools read files that
are **already on this machine**. None of them fetches anything. Each chain has
a stage 0 that lists or resolves what is present — `list_pulsar_scans` /
`resolve_pulsar_scan`, `list_variable_star_fixtures` /
`resolve_variable_star_fixture`, `list_optical_frames` /
`resolve_optical_frame`, `list_photometry_targets`. Call it first. **Never
invent a path**, and never claim to have run a tool on a file stage 0 did not
return. The one way to put a new frame here is
`search_mast(..., download=true)`; see `references/optical.md`.

> Authority: `tools/agent/prompt.py`, "PULSAR PIPELINE", "LOCAL OPTICAL
> FRAMES", "PHOTOMETRY".

## 2. The pulsar chain: the order is a dependency

Run the stages in order; each produces what the next needs.

0. `list_pulsar_scans` / `resolve_pulsar_scan` — find the scan. A bundled scan
   also carries `curated_period_s`, the literature period for that source. That
   is the check on your result, not the input to it.
1. `load_pulsar_lightcurve` — ingest and background-subtract. Pass its artifact
   path to every later stage.
2. `compute_pulsar_periodogram` — measure the period. It is the only tool that
   produces one from the data, and it runs on every scan, including those that
   already have a curated period. Check peak_fold_snr, not peak_confidence: the
   confidence threshold assumes white noise, so mains interference and baseline
   drift routinely read "99.73% Confidence" while folding to nothing. A
   `peak_does_not_fold` warning means the period is wrong.
3. `fold_pulsar_lightcurve` — stack rotations into a pulse profile. `pulse_snr`
   above ~8 is a detection. Folding at a wrong period returns a flat profile,
   not an error.
4. `sonify_pulsar` — render audio. Always pass `period_s` when you have one.

`plot_pulsar` renders any stage's artifact; the periodogram plot shows
interference spikes and harmonic combs at a glance. Never read a period off
rendered audio: the synthesis ignores sample timestamps.

> Authority: `tools/agent/prompt.py`, "PULSAR PIPELINE".

## 3. Period sourcing: measure first, compare second

A fold at a **measured** period is a detection. A fold at a **literature**
period is a fit to a known answer. They are different claims, and one must
never be reported as the other.

1. **Measure.** Run `compute_pulsar_periodogram`; read `peak_fold_snr` and
   `top_peaks`. That is the only evidence that does not depend on knowing the
   answer in advance.
2. **Compare.** Only then compare against stage 0's `curated_period_s`, or
   `search_atnf` for a source the curation does not cover. On agreement, report
   both numbers and say which is which.
3. **Retune, do not substitute.** On disagreement, a low `peak_fold_snr`, or a
   `peak_does_not_fold` warning, the measurement is wrong: retry with different
   parameters. Vary `back_scale` (a red-noise peak moves with it, a real
   periodicity does not), narrow `start`/`stop` away from the artifact, raise
   `steps`. Two artifacts recur on this data: 0.016665 s is 60.006 Hz mains
   interference, and a 2.1-2.2 s peak is leftover baseline red noise.
4. **Fall back, and say so.** Only when a retuned search has still failed, fold
   at the reference period — and state plainly that you did. That fold's
   `pulse_snr` is not an independent detection, because the period came from
   outside the data.

A blind search succeeds on one of the five bundled scans. Reaching step 4 on
the faint ones is an ordinary outcome to report, not a failure to hide.

> Authority: `tools/agent/prompt.py`, "PERIOD SOURCING".

## 4. Translate the name for the database you are about to call

Each database expects a different kind of identifier. Work out the right form
yourself **before** the call; do not pass the user's wording through unchanged.

- **SIMBAD** (`search_simbad`, `search_simbad_measurements`,
  `search_simbad_bibliography`): tolerant of common names. Pass the name as
  given.
- **NED** (`search_ned`): the resolver is unreliable with colloquial names.
  Always convert to the formal catalog designation (NGC/IC/M/PGC/UGC number, or
  another standard identifier) first — "cat's paw nebula" times out where
  "NGC 6334" resolves instantly.
- **VizieR** (`search_vizier`, `list_vizier_catalogs`): `target=` resolves
  common names. `catalog=` must be an exact VizieR ID ("VIII/65").
- **ATNF** (`search_atnf`): zero name resolution. "Crab" matches nothing; use
  the formal designation, J2000 preferred ("J0534+2200"), B1950 also works
  ("B0531+21"). Pulsars only.
- **MAST** (`search_mast`): resolves common names. Pass the name as given.
- **MPC** (`search_mpc`): zero name resolution, and it fails hard — "Halley"
  raises an error. Use an asteroid number ("1"), a periodic-comet number with
  "P" ("1P"), or a full designation ("C/2018 E1").
- **CASDA** (`search_casda`): `target=` resolves through SIMBAD; common names
  work.
- **ADS** (`search_ads` and the other literature tools): a fielded query
  language, not natural-language search. Use the structured parameters
  (`author`, `title`, `year`, ...) over a long free-text `query`.

A `table=` argument on `search_simbad_measurements` or `search_ned` must be an
exact value from the tool's own vocabulary, never free text. Details per
database are in `references/databases.md`.

> Authority: `tools/agent/prompt.py`, "BEFORE calling any tool".

## 5. Uncapping is `null`, never `"None"`

When a request implies exhaustive data ("all", "every", "complete",
"historical"), lift the cap: `search_vizier`'s `max_catalogs`, `search_mast`'s
`max_observations`. Tool arguments are JSON, not Python: set the parameter to
the JSON value null. Do not send the text "None" — it arrives as a
four-character string and breaks the tool. Omitting the parameter entirely does
not disable the cap either; it takes the capped default. `null` is the only way
to ask for no cap.

The caps exist to keep an exploratory result out of your context, not to limit
a request for everything. Having uncapped, say that the complete data was saved
and give the artifact path; do not present the preview as the whole answer.

> Authority: `tools/agent/prompt.py`, "When the user's request implies
> exhaustive data".

## 6. Sourcing: say where every number came from

- `search_simbad_bibliography` and `search_ned(table="references")` return
  bibcodes, titles and years — never a finding from inside a paper. Before
  stating a specific number and attributing it to a named paper, get that
  paper's abstract (`search_ads` and `build_literature_review` return abstracts
  inline; `get_paper_abstract` covers any other bibcode) and quote what it
  actually says.
- A figure from general astronomical background is labelled as such: "general
  background, not independently verified against the source this session".
- Never fill in a missing value. A `null` coordinate, magnitude or error bar is
  reported as not returned, not replaced with a plausible one.
- Report the uncertainty a tool returned with every value it goes with, and say
  "no uncertainty reported" when that field is null.
- Label an estimate or extrapolation as one before stating it.
- For a literature review or "papers on X", use `build_literature_review`
  rather than recalling papers, and give the Markdown file it writes.

> Authority: `tools/agent/prompt.py`, "SOURCING", "UNCERTAINTY AND NOT
> KNOWING", "LITERATURE REVIEWS".

## 7. Calling well

- The search tools resolve names themselves. Call `resolve_target` first only
  for coordinates, or to disambiguate an unclear name.
- If a call errors or times out, do not repeat the identical call. Read the
  error, then change the approach.
- `search_vizier(category="radio")` (or `"optical"`, `"infrared"`, ...) covers
  a whole band in one call; do not walk catalogs one ID at a time.
- Report plot and audio paths; do not describe an image you have not looked at
  as if you had.
- Once you have enough to answer, stop calling tools and answer.

> Authority: `tools/agent/prompt.py`, "Other guidance from observed failure
> modes", "PHOTOMETRY".

## 8. The preview is a sample; the artifact is the answer

A result's inline `preview` holds a few rows (ten by default). Its `count`, and
the `row_count` on each `artifact`, say how many exist. When the question is
about the whole set, read the file.

- **Where they are.** Served by `kepler-mcp`, every artifact is under the
  artifact directory the server pinned at startup — a per-user directory
  unless `KEPLER_ARTIFACT_DIR` says otherwise — and `list_artifacts`' own
  description names it. From a checkout it is `KEPLER_ARTIFACT_DIR`, or
  `artifacts/` in the directory Python started in. Either way the paths are
  local files you can read directly.
- **How they are laid out.** Each tool writes into its own subdirectory
  (`pulsar/`, `vizier/`, `simbad/`, ...). `list_artifacts` lists one
  directory's files, not subdirectories: pass the subdirectory as `directory`.
  Nothing is overwritten — a repeated call writes a new file with a numeric
  suffix — so use the path the result gave, not the newest-looking file.
- **How to read a table.** An `.ecsv` is plain text: `#` lines describe the
  columns (name, unit, datatype), then one header row and one row per record,
  space-separated, with strings quoted. Read it with your file tools, or with
  `astropy.table.Table.read(path)` where Python is available. A `.csv` is
  ordinary CSV.
- **Plots and audio.** Served, a PNG or WAV artifact also comes back inline, as
  an image or audio block after the result. A file too large to inline is
  named in a note instead; its path still works.

When you uncapped a search, or the preview is shorter than `count`, say that
the complete data was saved and give the path.

> Authority: `tools/agent/prompt.py`, "When the user's request implies
> exhaustive data".
