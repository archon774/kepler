<!-- Rendered from tools/skill/source/references/optical.md by `python -m tools.skill`. Edit the source, not this file. -->

# Optical: frames, plate solving, photometry, zero points

Everything here reads a FITS frame already on this machine (`SKILL.md` §1).
Three calls can reach the network: `run_photometry_on_target` with
`use_field_cal` on, `calibrate_zeropoint` without `catalog_fixture`, and
`search_mast(download=true)` to bring a frame here in the first place.

## Stage 0: find a frame

- `list_optical_frames` — every frame in the bundled library and the archive
  download directory, with object, filter, telescope, geometry and whether it
  carries a WCS. It reads a bounded number of frames per root; over the bound
  it warns `listing_truncated`. On an installed Kepler the frame library is an
  optional bundle; without it the frame tools warn `bundle_not_installed`, and
  an empty listing is that, not an empty sky — say so, and name
  `kepler-mcp fetch-data optical`.
- `resolve_optical_frame` — one frame by object name, stem or path. A field
  observed in more than one band returns an `ambiguous` error with the
  candidates: pick a band, do not guess.
- A frame not listed can be fetched with `search_mast(..., download=true)`. It
  is then listed on the next call — unless the listing was truncated, in which
  case pass `directory=` naming where `search_mast` said the product landed,
  rather than concluding the download failed.

> Authority: `tools/agent/prompt.py`, "LOCAL OPTICAL FRAMES".

## WCS

- `describe_image_wcs` — pointing, pixel scale and rotation from the header. A
  frame with no WCS returns `has_wcs=false` with a warning, not an error.
- `solve_astrometry` — plate-solve. It needs astrometry.net index files or a
  local UCAC catalogue that are **not** bundled; without them it reports the
  backend unavailable, which is an answer to relay, not a failure to retry. An
  all-sky solve (the default) can run for many minutes to a miss.
  `search_radius_deg` and a `min_scale_arcsec`/`max_scale_arcsec` pair narrow
  it — set them only from something you know, because a wrong window is a
  silent miss. `write_header=true` writes the solution back into the file, and
  it refuses to write into a bundled fixture.

## Photometry

- `list_photometry_targets` — the bundled stems photometry can run on. Call it
  first unless you already know the stem is there; never claim photometry on a
  frame not listed.
- `run_photometry_on_target` — source extraction plus aperture photometry.
  `use_field_cal` (default true) solves the zero point against a reference
  catalog over the network, 30-90 s. It is the **only** path whose magnitudes
  may be called calibrated. When it is off, or finds no catalog match, the
  magnitudes are instrumental and are reported as such. Turn it off yourself
  when only counts, positions or relative brightness are wanted. An explicit
  `zero_point_mag` yields unverified magnitudes, never calibrated ones.

Reading the result:

- `source_count` is sources with a **photometric measurement** — not reliable
  or good sources. Say "obtained a photometric measurement for N sources".
- `flux` is a raw per-exposure aperture sum, so
  `mag = -2.5*log10(flux / exposure_seconds) + zero_point`. Quote
  `exposure_seconds`, labelled as the exposure time in seconds, before anyone
  checks `mag` against `flux` by hand. Off the field-cal path a small
  aperture-correction constant also sits in `mag`; a residual of hundredths to
  tenths of a magnitude is expected.
- `zero_point_error_mag` is the solve's statistical scatter, not the accuracy
  of the magnitudes. Never say "accurate to" it.
- Report the plot paths; do not describe plots you have not looked at.

> Authority: `tools/agent/prompt.py`, "PHOTOMETRY", "Confirmed live, and worth
> stating plainly", "Two more precision distinctions".

## Zero points and the recorded references

Zero points here are **absolute** magnitudes. Afterglow's API reports 20.0 plus
a correction instead; never compare the two without adding Afterglow's base.

- `list_photometric_catalogs`, `resolve_reference_band` — which catalog band a
  filter calibrates against, and how. An unfiltered frame (Open/Clear/Lum)
  resolves through a substitute band, which is why it has no published zero
  point of its own. Declaration only, no network.
- `solve_zeropoint_from_measurements` — a zero point from paired instrumental
  and catalog magnitudes you already have.
- `calibrate_zeropoint` — the whole solve from a frame's own pixels.
  `compare_to` names a recorded solve to place the result against;
  `catalog_fixture` (which needs `compare_to`) replays the recorded catalog rows
  and opens no socket. Today only `ngc5128_galaxy_b_001.fits` with
  `compare_to="ngc5128_b_002"` runs end to end offline.
- `list_zeropoint_references`, `load_zeropoint_reference`,
  `replay_field_calibration`, `compare_zeropoint_to_reference` — the recorded
  Skynet solves bundled as ground truth, a bit-exact offline replay of one, and
  a check of any computed zero point against them.

> Authority: `tools/registry.py`, the `calibrate_zeropoint`,
> `replay_field_calibration` and `compare_zeropoint_to_reference`
> descriptions.

## Artifacts

`list_artifacts` and `describe_artifact` enumerate what the tools have written
to the artifact directory. Use them when you have a result but not the file.
