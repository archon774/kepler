# `fieldcal` — calibration record

**Status: NOT CALIBRATED.** Not run against any real model; see
`../core/calibration.md` for why that is a gate rather than a formality.

These two tasks carry the strongest keys in the repository, and their strength
is independent of calibration: `fieldcal-offline-solve` is graded by
`compare_zeropoint_to_reference.within_tolerance`, a boolean the repository's
own code computes against a recorded Skynet solve whose preservation the test
suite already pins. No phrasing can pass or fail it.

What calibration would still establish is whether the tasks are *reachable* by
a real model — whether a model asked this question finds
`catalog_fixture` + `compare_to` without being told, and whether the
provenance `must_not_call` catches a model that instead reads the reference
and hands its number back.

**Neither task has been run end to end even against replay.** Both need
`calibrate_zeropoint` to execute its offline path over
`data/optical/ngc5128_galaxy_b_001.fits`, which is real compute, and no
transcript has been authored for them. `tests/test_bench_corpus.py` asserts
they load and that their fixtures and checks validate; it does not run them.

| task | frontier | mid | local | verdict |
| --- | --- | --- | --- | --- |
| `fieldcal-offline-solve` | — | — | — | not run |
| `fieldcal-not-an-accuracy-figure` | — | — | — | not run |

The recorded truth these grade against:

- `data/fieldcal/zp_solutions/ngc5128_b_002/fit_summary.json` — zero point
  21.147659857998637 mag, formal error 0.011615705331140265 mag, 35 matched
  APASS sources, 26 accepted by the fit.
- The other three recorded solves (`ngc5286_b_000/001/002`) are **not usable**:
  their frames are the three this repository does not carry, pending
  `optical-tools.md` P8.
