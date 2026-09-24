# Databases: SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS

Sixteen tools, all remote. Each is a thin client over one service, with a
schema of its own — one tool per database is deliberate, not a missing
dispatcher. `SKILL.md` §4 has the identifier-form table; this file is the
detail behind each row.

`ADS_DEV_KEY` must be set for the ADS tools. The others need no key.

## Resolving a name

`search_simbad`, `search_ned`, `search_vizier`, `search_atnf` and
`search_mast` resolve a name themselves. `resolve_target` (SIMBAD) is for when
you need coordinates — for `search_casda` by position, or to disambiguate an
unclear name — not a step before every search.

## SIMBAD

- `search_simbad` — current best-value properties. Tolerant of colloquial names.
- `search_simbad_measurements` — every per-paper measurement from one table
  (`flux`, `mesPM`, `mesDiameter`, ...). `table` must be SIMBAD's exact table
  name.
- `search_simbad_bibliography` — every paper SIMBAD has on the object: bibcodes,
  titles, years. **Not** findings; see `SKILL.md` §6.
- `get_paper_abstract` — the abstract for one bibcode. The way to ground a
  specific number in a named paper.

## NED

`search_ned` returns a whole historical table: `photometry` (default),
`positions`, `diameters`, `redshifts`, `references`, `object_notes`.

- Pass the **formal designation**. The resolver times out on colloquial names.
- `photometry` is the full SED, X-ray through radio, in one table. NED has no
  band filter: scope it with `min_frequency_hz` / `max_frequency_hz` (radio
  continuum is conventionally below ~3e11 Hz). Never report a multi-band table
  as if it were single-band because that is what was asked for.

> Authority: `tools/agent/prompt.py`, "BEFORE calling any tool" (the NED item).

## VizieR

- `search_vizier` — any of VizieR's ~20,000 tables around a target in one call.
  `category="radio"` (or `optical`, `infrared`, `xray`, `gamma-ray`, `uv`,
  `millimeter`) sweeps a whole band. `catalog=` must be an exact ID ("VIII/65").
- `category=` tags whole **catalogs**, not rows. A cross-match catalog tagged
  radio may carry only some radio columns. The result warns every time; check
  each matched catalog's title and columns before calling its rows pure radio.
- `list_vizier_catalogs` ANDs every keyword against catalog **titles**. Use one
  or two broad words ("radio continuum", "pulsar"), never an object name —
  catalog titles name surveys, instruments and authors, never targets. For
  "everything about X", use `search_vizier(category=...)` instead.
- `max_catalogs` caps how many matched catalogs are written out; the true match
  count is always reported. `null` uncaps (`SKILL.md` §5).

> Authority: `tools/agent/prompt.py`, "BEFORE calling any tool" (the VizieR
> item).

## ATNF

`search_atnf` returns every ATNF Pulsar Catalogue parameter for one pulsar.
Zero name resolution: "Crab" matches nothing, "J0534+2200" or "B0531+21" does.
Pulsars only; a non-pulsar name returns `not_found`. Its `P0` is a reference to
check a measured period against, never a substitute for one (`SKILL.md` §3).

## MAST

`search_mast` lists observations and their products. `max_observations` caps
how many observations have products fetched; `null` uncaps, and takes a while
on a heavily observed object. `download=true` fetches products into the local
download root, where `list_optical_frames` / `resolve_optical_frame` find them
(`references/optical.md`).

## MPC

`search_mpc` returns one minor planet's full observation history. Zero name
resolution, and it errors rather than returning nothing: "1" (Ceres), "433"
(Eros), "1P" (Halley), "C/2018 E1". Translate the common name yourself.

## CASDA

`search_casda` searches the ASKAP radio archive. `target=` resolves through
SIMBAD. ASKAP is a southern instrument: a northern target usually returns
nothing, and that is an answer, not an error.

## ADS

ADS is a fielded query language. Use `search_ads`'s structured parameters —
`author` ("Last, F."), `title`, `abstract`, `year` ("2017" or "2015-2020"),
`bibcode`, `object_name`, `doctype` — rather than a question in `query`. Prefer
one or two well-chosen fields over many loose keywords; a long keyword list
returns nothing or noise.

- `query=` is raw ADS syntax for what the fields do not cover (`similar(...)`,
  `trending(...)`, proximity, wildcards), ANDed with any fields given.
- `object_name=` is a SIMBAD/NED-tagged lookup, not plain text, and combining
  it with other fields has been seen to fail with a 400. If a call errors, read
  the error — it carries ADS's own response body — then drop `object_name`
  first and put the object in `title=` or `abstract=`.
- `get_citing_papers` / `get_referenced_papers` walk the citation graph from a
  bibcode.
- `build_literature_review` searches and writes a Markdown review with full
  citations and abstracts. Use it for any literature review or bibliography,
  and give the path.

> Authority: `tools/agent/prompt.py`, "BEFORE calling any tool" (the ADS item),
> "LITERATURE REVIEWS". The ADS guidance is grounded in ADS's published
> documentation rather than confirmed against the live service, and the prompt
> says so.
