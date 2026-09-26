<!-- Rendered from tools/skill/source/references/pulsar.md by `python -m tools.skill`. Edit the source, not this file. -->

# Time series: the pulsar and variable-star chains

Both chains are local: they read files already on this machine and open no
socket, except `search_atnf` when you reach for it as a reference. The cross-
tool rules — the stage order and period sourcing — are in `SKILL.md` §§2-3 and
are not repeated here. This file is how to carry them out.

## Pulsar: the bundled scans

`list_pulsar_scans` returns five Green Bank 20 m scans, about a minute each.
Each carries `curated_period_s`, `curated_difficulty` and `period_source`, which
names the curation the period came from. The scans themselves carry **no
period**; that is exactly why a fold at a measured period is an independent
detection. Recorded outcomes of a blind search at default settings:

| Scan | Curated difficulty | Blind search at defaults |
| --- | --- | --- |
| B0329+54 | Easy | the pulsar, 0.7148 s, within 0.04% of the reference |
| B1133+16 | Lightly Challenging | 0.016665 s — 60 Hz mains |
| B1933+16 | More Challenging | ~2.18 s — baseline red noise |
| B2021+51 | Lightly Challenging | ~2.14 s — baseline red noise |
| B2045-16 | Most Challenging | 0.016665 s — 60 Hz mains |

That is what a minute on a 20 m dish supports, not a defect. Four of the five
peaks above clear the "99.73% Confidence" line anyway, which is why
`peak_confidence` is not the check. B1933+16 resists even a tuned search: its
dispersion smears the pulse across ~11% of the period, and this pipeline has no
dedispersion. Expect the fallback there.

> Authority: `docs/pulsar-tool-pipeline.md` §4, "What a blind search actually
> achieves"; `tools/agent/prompt.py`, "PERIOD SOURCING".

## Pulsar: a run, step by step

1. `resolve_pulsar_scan(name=...)` — any usual spelling works ("B0329+54",
   "PSR B0329+54"). Keep `curated_period_s` aside; do not use it yet.
2. `load_pulsar_lightcurve(path=...)` — keep the `.ecsv` artifact path; every
   later stage takes it.
3. `compute_pulsar_periodogram(path=<artifact>)` — read `peak_period_s`,
   `peak_fold_snr`, `top_peaks`, and the warnings.
   - `peak_fold_snr` above ~8 and no `peak_does_not_fold` warning: a candidate.
     Check `top_peaks` for harmonics — pulsars put power at P/2, P/3, ..., so
     an entry at an integer fraction of another may share one fundamental.
   - Otherwise: the peak is an artifact. Recognise which one (0.016665 s is
     mains; 2.1-2.2 s is red noise) and retune.
4. **Retune** before reaching for the reference:
   - rerun `load_pulsar_lightcurve` with a different `back_scale` (e.g. 1 and 6
     against the default 3) and search again — a red-noise peak moves with it,
     a real periodicity does not;
   - narrow `start`/`stop` to exclude the artifact (e.g. `start=0.05` drops
     mains), and raise `steps` once you know roughly where the period is.
   `plot_pulsar(path=<periodogram artifact>)` shows at a glance whether the
   spectrum is a harmonic comb or a forest of interference spikes.
5. **Compare** the measured period with `curated_period_s` (or `search_atnf`
   for an unbundled source). Agreement: fold at the **measured** period.
6. `fold_pulsar_lightcurve(path=<artifact>, period_s=<measured>)` — read
   `pulse_snr`. A faint source may need fewer `bins`.
7. **Fallback**, only if every retuned search failed: fold at the reference
   period and say so in the answer.
8. `sonify_pulsar(path=<artifact>, period_s=<the period you folded at>)` —
   folded audio is what sounds like a pulsar. Without `period_s` it warns
   `unfolded_rendering` and plays the raw scan once.

## Pulsar: reporting the period

The answer must let a reader tell a detection from a fit. State, for every
scan:

- the **measured** period, from `compute_pulsar_periodogram`, with its
  `peak_fold_snr` and the parameters that produced it;
- the **reference** period and where it came from (`period_source`, or ATNF);
- their agreement, as a percentage;
- which period the fold used, and the fold's `pulse_snr`.

When the fold used the reference, say that the period came from outside the
data and that the `pulse_snr` is therefore not an independent detection — and
say what the blind search found instead (mains, red noise). "Detected at the
literature period" is exactly the sentence this rule forbids.

> Authority: `tools/agent/prompt.py`, "PERIOD SOURCING".

## Variable stars

The variable-star chain has the same shape and the same discipline, over
compact paired-source CSV fixtures rather than radio scans:

0. `list_variable_star_fixtures` / `resolve_variable_star_fixture` — offline
   fixtures only; never invent a path.
1. `load_variable_star_lightcurve` — validates and merges the pair into an
   ECSV artifact.
2. `compute_variable_star_periodogram` — the error-weighted periodogram; this
   is where the period comes from.
3. `fold_variable_star_lightcurve` — folds at an explicit `period`.

A period you fold at came from step 2 or from somewhere else, and the answer
says which.

> Authority: `tools/registry.py`, the `list_variable_star_fixtures` through
> `fold_variable_star_lightcurve` descriptions. `tools/agent/prompt.py` does
> not yet cover this chain; the period-sourcing rule is applied to it by
> analogy.
