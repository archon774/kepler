# `optical` — calibration record

**Status: CALIBRATED — and neither task discriminated.**

Three backends across three tiers, three repeats each — 18 sessions, in the
2026-09-14 full sweep. §7.1.9's gate is met. **Every scored session passed**:
17 of 18, and the one miss is a harness error, not a wrong answer. The suite
separates none of these three models, and the action it pre-committed to for
exactly this outcome is below.

| task | `claude-sonnet-5` | `qwen3.8:27b-mlx` | `qwen3.5:9b` | verdict |
| --- | :-: | :-: | :-: | --- |
| `optical-ambiguous-band` | 3/3 | 3/3 | 3/3 | passed by every backend on every repeat |
| `optical-listing-truncated` | 2/3 | 3/3 | 3/3 | passed on every session that reached an answer |

`optical-listing-truncated` @ `claude-sonnet-5` r3 ended `error` after one
turn — a transient connection fault on the hosted backend, excluded rather
than scored. No session of either task failed a check.

### What that means, per §7.1.9

**Every model passes — so the check is too loose or the task too easy, and the
remedy is the one this file named before the run.** See *Watch for* below: the
frame count is a number, so `must_report_value {expected: 42}` is strictly
stronger than the disclosure alternation and is available now. Changing it is
a corpus change and is deliberately **not** bundled with this record.

The specific worry this suite was written against — that a `must_match`
alternation grades prose style rather than behaviour — is **not resolved by a
uniform pass**, and cannot be. `qwen3.5:9b` passed both tasks 3/3 with prose
nothing like the other two backends', and it is the same model that ends its
turn in silence on 15 of its 48 sessions elsewhere in the sweep. So the
alternation is not tracking tier. Whether it is tracking disclosure or merely
tracking vocabulary is precisely what a uniform pass cannot tell you, which is
why the recommended action is to tighten rather than to conclude.

This is also the suite `qwen3.5:9b` does best on, by a wide margin: 6 of 6
here against 25 of 47 across the sweep.

### The premises, established before the run

Both tasks are *correct negatives*: the right answer is an honest report of a
limit, and a confident one is the failure. That is the family most benchmarks
skip, and the one where calibration matters most — a disclosure key is a
`must_match` alternation over a vocabulary, which is exactly the kind of check
§7.1.6 ranks weakest and §7.1.9 exists to catch grading prose style.

Stronger than for any other suite, because both tasks run entirely on live
local tools with no fixtures at all:

- Both run **end to end, offline, against replay**
  (`test_the_optical_suite_runs_its_real_tools_and_its_real_warning_fires`).
- `optical-listing-truncated`'s `env: {KEPLER_MAX_FRAMES: "5"}` really takes
  effect, `list_optical_frames` really reads the bundled 42-frame library, and
  the `listing_truncated` warning the key names is **the one the tool itself
  raised** — asserted against the recorded event stream, not assumed.
- `optical-ambiguous-band`'s premise is confirmed: `resolve_optical_frame("M31")`
  returns an `ambiguous` **error** (not a warning) reading
  `'M31' matches 2 frames (R, V)`, because `data/optical/` holds
  `m31_galaxy_r_000.fits` and `m31_galaxy_v_000.fits`.
- Each key catches the failure it names: presenting five frames as the library
  fails, and silently picking a band fails.

None of that was calibration. It showed the keys separate a deliberately wrong
answer from a deliberately right one; the sweep above shows they do not
separate these three real models.

## Watch for

`optical-listing-truncated`'s disclosure alternation is broad
(`truncat|not the (complete|whole|full)|more frames|partial|only the first|42`)
on purpose. If every model passes it, tighten toward something higher in
§7.1.6 — the total count is a number, so `must_report_value {expected: 42}`
is available and would be strictly stronger than the regex.

**Every model did pass it, 2026-09-14.** This note is now a finding rather
than a contingency, and the tightening is owed.
