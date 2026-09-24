<!-- Rendered from tools/skill/source/references/radio.md by `python -m tools.skill`. Edit the source, not this file. -->

# Radio sources

Three tools over a processed radio FITS map, VizieR's radio catalogs and NED's
photometry. All three reach the network.

- `plot_field_sed` — **the main radio tool.** Identifies the sources in the map
  against VizieR's radio catalogs, fetches each one's spectrum from NED, fits
  it, and draws every source on one labelled plot. Use it for "what's in this
  radio image" or "plot the SED for this field".
- `identify_radio_sources` — the source table alone (positions, flux, match
  counts), no plot.
- `analyze_source_spectrum` — one already-named source, or your own
  frequency/flux arrays or CSV: a power law and a log-parabola, reporting
  whichever the data supports.

## Reading the result

- A source with no catalogued name, or no usable NED photometry, is skipped and
  named in the warnings. That is an ordinary outcome for an uncatalogued
  source, not a failure.
- `spectral_index` follows S_nu ~ nu**spectral_index, so optically thin
  synchrotron is negative (about -0.5 to -1.0). Always call it "spectral index"
  and never give it as a bare number.
- On a wide map, the catalog search centres on the field but caps its radius at
  60' by default, and warns. Say that catalog coverage was limited to a
  sub-region of the frame. Pass `max_field_radius_arcmin=null` only when the
  user explicitly wants the full, much slower search (`SKILL.md` §5).

> Authority: `tools/agent/prompt.py`, "RADIO SOURCES".
