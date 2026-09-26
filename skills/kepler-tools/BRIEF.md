<!-- Rendered from tools/skill/source/BRIEF.md by `python -m tools.skill`. Edit the source, not this file. -->

Kepler: astronomy tools. Before first use read `SKILL.md`; per-domain guides are `references/pulsar.md`, `references/databases.md`, `references/optical.md`, `references/hr.md`, `references/radio.md`.

1. Local tools read only files already here. List or resolve first; never invent a path.
2. Pulsar: load -> compute_pulsar_periodogram -> fold -> sonify. Measure first, compare second. Judge peak_fold_snr, not peak_confidence. On a mismatch, retune (back_scale, start/stop, steps) before folding at the curated or ATNF period, and say you did: that fold is not an independent detection. 0.016665 s is mains; 2.1-2.2 s is red noise.
3. NED needs a formal designation. ATNF and MPC do zero name resolution (J0534+2200, 1P).
4. Uncap with JSON null, never the text "None".
5. Quote an abstract before attributing a number to a paper; label background knowledge.
6. A preview is a sample; the artifact file is the full result.
