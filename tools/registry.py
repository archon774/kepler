"""Kepler: tool schemas for wiring ``tools`` into an agent loop.

Each entry is an Anthropic tool-use schema (``name``, ``description``,
``input_schema``) plus the callable it maps to. ``tools.runner`` is the only
consumer that needs this; importing ``tools.<module>`` directly and calling a
function is simpler for ordinary Python use.
"""

from __future__ import annotations

from typing import Any, Callable

from tools.ads import (
    build_literature_review,
    get_citing_papers,
    get_referenced_papers,
    search_ads,
)
from tools.atnf import search_atnf
from tools.casda import search_casda
from tools.hr_diagram import (
    crossmatch_gaia,
    crossmatch_gaia_by_position,
    extract_photometry_from_fits,
    fit_and_compare_hr_diagram,
    get_literature_cluster_params,
    run_full_hr_pipeline,
    run_full_hr_pipeline_from_catalog,
    select_cluster_members,
)
from tools.mast import search_mast
from tools.mpc import search_mpc
from tools.ned import search_ned
from tools.pulsar import (
    compute_pulsar_periodogram,
    plot_pulsar,
    list_pulsar_scans,
    resolve_pulsar_scan,
    fold_pulsar_lightcurve,
    load_pulsar_lightcurve,
    sonify_pulsar,
)
from tools.photometry import list_photometry_targets, run_photometry_on_target
from tools.resolve import resolve_target
from tools.simbad import (
    get_paper_abstract,
    search_simbad,
    search_simbad_bibliography,
    search_simbad_measurements,
)
from tools.vizier import list_vizier_catalogs, search_vizier

__all__ = ["TOOL_SCHEMAS", "TOOL_FUNCTIONS"]

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "resolve_target",
        "description": "Resolve a free-text object name to sky coordinates and an "
        "object type via SIMBAD.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name, e.g. 'Cas A'."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_simbad",
        "description": "Look up an object on SIMBAD: its current best-value "
        "properties (coordinates, object type, and any requested fields). "
        "Confirmed live: SIMBAD's own resolver handles common/colloquial names "
        "well (e.g. 'cat's paw nebula' resolves directly to NGC 6334) -- no "
        "translation needed before calling this one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra SIMBAD VOTable fields to add, e.g. "
                    "['otype', 'allfluxes'].",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_simbad_measurements",
        "description": "Return every historical per-paper measurement SIMBAD has for "
        "an object from one measurement table (flux, proper motion, diameter, "
        "variability, etc.) -- not a single best value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "table": {
                    "type": "string",
                    "description": "SIMBAD measurement table name, e.g. 'flux', "
                    "'mesPM', 'mesDiameter'. Defaults to 'flux'.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_simbad_bibliography",
        "description": "Return every paper SIMBAD has on file that discusses an "
        "object. A partial substitute for literature search, not equivalent to ADS.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Object name."}},
            "required": ["name"],
        },
    },
    {
        "name": "get_paper_abstract",
        "description": "Fetch title/year/journal/abstract text for one bibcode. This "
        "is the ONLY way this tool set can ground a specific quantitative literature "
        "claim (a decline rate, a measured value, a discovery date) in text that was "
        "actually retrieved. Confirmed live: without this, an agent asked to confirm "
        "a decline rate attributed a specific figure to a real paper by name that the "
        "paper's actual abstract does not contain -- a fabricated-sounding number from "
        "training data, not from any tool result. If you are about to state a specific "
        "number and attribute it to a named paper, fetch that paper's abstract first "
        "with this tool, or say plainly that the figure is from general background "
        "knowledge and was not verified against the source this session. Get bibcodes "
        "from search_simbad_bibliography or search_ned (table='references'). Not every "
        "bibcode has an abstract on file -- that returns not_found, not an error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bibcode": {
                    "type": "string",
                    "description": "ADS-style bibcode, e.g. '2017MNRAS.469.1299T'.",
                }
            },
            "required": ["bibcode"],
        },
    },
    {
        "name": "search_ads",
        "description": "Search NASA/SAO ADS for literature. ADS is NOT a natural-language "
        "search engine -- its own documentation warns that unfielded, bare-word queries "
        "'may not produce the expected results.' Use the structured parameters "
        "(author, title, abstract, year, bibcode, object_name, doctype) rather than "
        "stuffing a plain-English question into `query`; they combine with AND and are "
        "assembled into ADS's fielded syntax for you (e.g. author='Trotter, K.' becomes "
        "author:\"Trotter, K.\"). `year` accepts a single year or a range ('2015-2020'). "
        "Set first_author_only=true to restrict an author search to first-authored papers "
        "only. `query` is a raw ADS query string for anything the structured parameters "
        "don't cover -- second-order operators like similar(bibcode:...) or "
        "trending(topic), proximity search, wildcards -- and is ANDed with the others if "
        "both are given. Results already include abstract text (no need for a separate "
        "get_paper_abstract call for papers this returns). Requires ADS_DEV_KEY to be "
        "configured; returns dependency_missing if it isn't.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Raw ADS query string, for syntax the structured "
                    "parameters don't cover. Never a plain-English question.",
                },
                "author": {"type": "string", "description": "e.g. 'Trotter, K.'."},
                "first_author_only": {"type": "boolean", "description": "Defaults to false."},
                "title": {"type": "string"},
                "abstract": {"type": "string", "description": "Phrase to find in the abstract."},
                "year": {"type": "string", "description": "'2017' or '2015-2020'."},
                "bibcode": {"type": "string"},
                "object_name": {"type": "string", "description": "Astronomical object name."},
                "doctype": {"type": "string", "description": "e.g. 'article', 'catalog'."},
                "sort": {
                    "type": "string",
                    "description": "e.g. 'date desc' (default) or 'citation_count desc'.",
                },
                "max_results": {"type": "integer", "description": "Defaults to 20."},
            },
        },
    },
    {
        "name": "get_citing_papers",
        "description": "Return papers that cite a given bibcode (ADS's citations() "
        "operator) -- use this to trace how a finding has been used or challenged since "
        "publication, or to find the most recent work building on an older paper.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bibcode": {"type": "string", "description": "e.g. '2017MNRAS.469.1299T'."},
                "sort": {"type": "string", "description": "Defaults to 'citation_count desc'."},
                "max_results": {"type": "integer", "description": "Defaults to 20."},
            },
            "required": ["bibcode"],
        },
    },
    {
        "name": "get_referenced_papers",
        "description": "Return papers a given bibcode cites (ADS's references() "
        "operator) -- use this to find the earlier foundational work behind a paper.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bibcode": {"type": "string", "description": "e.g. '2017MNRAS.469.1299T'."},
                "sort": {"type": "string", "description": "Defaults to 'date desc'."},
                "max_results": {"type": "integer", "description": "Defaults to 20."},
            },
            "required": ["bibcode"],
        },
    },
    {
        "name": "build_literature_review",
        "description": "Search ADS and write a Markdown literature review to disk -- "
        "one numbered entry per paper with a full citation (authors, year, journal, "
        "volume, page, bibcode, DOI, citation count) and its abstract. Takes the same "
        "structured search parameters as search_ads (author, title, abstract, year, "
        "object_name, doctype, or a raw query=). Defaults to sort='citation_count desc' "
        "so the most-cited/foundational papers lead the review -- pass "
        "sort='date desc' for a chronological one instead. Use this whenever the user "
        "asks for a literature review, bibliography, or 'papers on X with citations' -- "
        "it saves the full formatted review as a file rather than listing papers inline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Raw ADS query string."},
                "author": {"type": "string"},
                "first_author_only": {"type": "boolean", "description": "Defaults to false."},
                "title": {"type": "string"},
                "abstract": {"type": "string"},
                "year": {"type": "string", "description": "'2017' or '2015-2020'."},
                "object_name": {"type": "string"},
                "doctype": {"type": "string"},
                "sort": {
                    "type": "string",
                    "description": "Defaults to 'citation_count desc'.",
                },
                "max_papers": {"type": "integer", "description": "Defaults to 30."},
            },
        },
    },
    {
        "name": "search_ned",
        "description": "Return NED's full historical data table for an object -- "
        "photometry (every published flux measurement, any band, with reference), "
        "positions, diameters, redshifts, references, or object notes. Confirmed "
        "live: NED's own name resolver is unreliable with colloquial names -- "
        "'cat's paw nebula' times out repeatedly where 'NGC 6334' resolves "
        "instantly. Always pass the formal catalog designation (NGC/IC/M/PGC/UGC "
        "number, or another standard identifier) here, never a common nickname -- "
        "resolve it yourself from general knowledge, or via search_simbad/"
        "resolve_target first, before calling this tool. NED itself has no band "
        "filter -- 'photometry' always returns the full SED, X-ray through radio, "
        "in one table. If the caller asked for one band only (e.g. radio), pass "
        "max_frequency_hz (radio continuum is conventionally below ~3e11 Hz / "
        "300 GHz) so the result and saved file are actually scoped to it, rather "
        "than reporting the full multi-band table as if it were radio-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "table": {
                    "type": "string",
                    "enum": [
                        "photometry",
                        "positions",
                        "diameters",
                        "redshifts",
                        "references",
                        "object_notes",
                    ],
                    "description": "Defaults to 'photometry'.",
                },
                "min_frequency_hz": {
                    "type": "number",
                    "description": "photometry only: drop rows below this frequency.",
                },
                "max_frequency_hz": {
                    "type": "number",
                    "description": "photometry only: drop rows above this frequency. "
                    "Use ~3e11 (300 GHz) to restrict to radio continuum.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_vizier_catalogs",
        "description": "Discover VizieR catalog IDs matching free-text keywords, "
        "with descriptions. Metadata only, no object data fetched. Every word is "
        "ANDed against catalog TITLES, not object names or topics -- use 1-2 broad "
        "terms (a survey name, instrument, or science category like 'pulsar' or "
        "'radio continuum'), never a multi-word natural-language phrase or a "
        "target object name, and never combine a topic word with the object name "
        "(e.g. 'Cassiopeia flux' is wrong for the same reason 'Cassiopeia A "
        "secular decrease' is -- VizieR catalog titles are named for surveys/"
        "instruments/authors, never for the target object, so including the "
        "object name guarantees zero matches). For 'everything about object X', "
        "prefer search_vizier with category= directly -- this tool is only for "
        "finding an unfamiliar catalog by topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "1-2 broad, distinctive words, ANDed, e.g. "
                    "'radio continuum' or 'pulsar timing'. Not a target name or "
                    "a long descriptive phrase.",
                }
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "search_vizier",
        "description": "Query any VizieR catalog (any of its ~20,000 tables, any "
        "spectrum) around a target in ONE call. Pass target= alone (it resolves "
        "the name itself, like SIMBAD/NED/MAST tools do -- do not call "
        "resolve_target first just for this). Use category='radio' (or 'optical', "
        "'infrared', 'xray', ...) for a whole spectrum with no catalog IDs needed "
        "-- prefer this over looping catalog= one ID at a time. The response's "
        "preview shows a couple of tagged rows per matched catalog; only call "
        "again with a specific catalog= if you need more rows from one of them "
        "than max_catalogs/row_limit already returned. Pass target= OR "
        "ra_hours+dec_degs, not both -- if both are given, coordinates win and "
        "target is not used for the query. IMPORTANT, confirmed live: category= "
        "tags whole catalogs, not individual rows -- 'radio' also matches "
        "multi-wavelength cross-match catalogs (titles like 'cross-matched radio/"
        "infrared/X-ray sources' or 'Optical Radio/X-ray Associations') where only "
        "some columns are radio-derived. Before reporting a matched catalog's rows "
        "as radio observations, check its artifact's columns/the catalog's own "
        "name for other-band indicators (X-ray, optical, IR) and exclude or caveat "
        "ones that are not primarily radio.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Object name."},
                "ra_hours": {"type": "number"},
                "dec_degs": {"type": "number"},
                "radius_arcmin": {"type": "number", "description": "Defaults to 2.0."},
                "catalog": {
                    "type": "string",
                    "description": "A specific VizieR catalog ID, e.g. 'VIII/65'.",
                },
                "category": {
                    "type": "string",
                    "description": "VizieR spectrum category: 'radio', 'optical', "
                    "'infrared', 'xray', 'gamma-ray', 'uv', 'millimeter'.",
                },
                "max_catalogs": {
                    "type": ["integer", "null"],
                    "description": "How many matched catalogs to write out and "
                    "summarize; the true match count is always reported. Pass null "
                    "for no cap when the user asked for all/every/complete data.",
                },
            },
        },
    },
    {
        "name": "search_atnf",
        "description": "Return every ATNF Pulsar Catalogue parameter available for a "
        "named pulsar. Confirmed live: this catalogue does zero name resolution -- "
        "even a famous nickname like 'Crab' matches nothing. `name` must be the "
        "pulsar's formal designation: J2000 form preferred (e.g. 'J0534+2200' for "
        "the Crab pulsar), B1950 form also accepted (e.g. 'B0531+21'). Translate "
        "any common pulsar nickname to its designation yourself before calling "
        "this. Pulsar-only -- never pass a nebula, galaxy, or remnant name; a "
        "name that resolves but isn't a pulsar returns not_found, not an error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Formal pulsar designation, e.g. 'J0534+2200'. "
                    "Not a common name.",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_mast",
        "description": "Search the MAST archive for observations of an object and "
        "list their data products. Set download=true to fetch matched products "
        "to local disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name."},
                "radius_arcmin": {"type": "number", "description": "Defaults to 12.0."},
                "max_observations": {
                    "type": ["integer", "null"],
                    "description": "How many matched observations to fetch products "
                    "for; the true observation count is always reported. Pass null "
                    "for no cap when the user asked for all/every/complete data -- "
                    "expect this to take a while for a heavily-observed object.",
                },
                "mrp_only": {
                    "type": "boolean",
                    "description": "Only Minimum Recommended Products.",
                },
                "extension": {"type": "string", "description": "e.g. 'fits'."},
                "product_type": {"type": "string", "description": "e.g. 'SCIENCE'."},
                "download": {"type": "boolean", "description": "Defaults to false."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "extract_photometry_from_fits",
        "description": (
            "Detect sources in a plate-solved FITS frame and measure their instrumental "
            "photometry (position, magnitude). The frame must already have a WCS in its "
            "header. Returns a summary + an artifact CSV path for the next step. This is "
            "the HR-diagram pipeline's own extraction step (Kron-like auto apertures, no "
            "zero-point calibration -- the frame's own magnitude is discarded once Gaia's "
            "is fetched). For a scientifically calibrated photometry report of a frame on "
            "its own (not toward an HR diagram), use run_photometry_on_target instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fits_path": {"type": "string", "description": "Path to the FITS file."},
                "threshold": {"type": "number", "description": "Detection threshold in background sigma (default 2.5)."},
            },
            "required": ["fits_path"],
        },
    },
    {
        "name": "crossmatch_gaia",
        "description": (
            "Match detected sources (from extract_photometry_from_fits) to Gaia DR3 by sky "
            "position, attaching Gaia's G/BP/RP magnitudes, parallax and proper motion -- "
            "this is what supplies the colour for the HR diagram, since a single FITS frame "
            "is only one filter. Requires a FITS frame to have been detected first -- if the "
            "user has no FITS file, use crossmatch_gaia_by_position instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "CSV artifact path from extract_photometry_from_fits."},
                "radius_arcsec": {"type": "number", "description": "Match radius in arcsec (default 2.0). Widen if n_matched comes back 0 or low."},
                "mag_limit": {"type": "number", "description": "Only consider Gaia sources brighter than this G magnitude (default 20)."},
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "crossmatch_gaia_by_position",
        "description": (
            "Fetch Gaia DR3 photometry directly around a named cluster's own resolved "
            "position -- no FITS frame needed. Use this (instead of "
            "extract_photometry_from_fits + crossmatch_gaia) whenever the user asks about "
            "a cluster's HR diagram without supplying their own FITS file: Gaia's own "
            "G/BP/RP photometry stands in for a frame's instrumental photometry, so there "
            "is nothing to detect first. Returns the same column shape crossmatch_gaia "
            "does, so its artifact feeds directly into select_cluster_members and "
            "fit_and_compare_hr_diagram."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string", "description": "Cluster name or alias, e.g. 'NGC 2168' or 'M35'."},
                "radius_arcmin": {"type": "number", "description": "Cone-search radius around the cluster (default 20.0)."},
                "mag_limit": {"type": "number", "description": "Only consider Gaia sources brighter than this G magnitude (default 17.0)."},
            },
            "required": ["cluster_name"],
        },
    },
    {
        "name": "get_literature_cluster_params",
        "description": (
            "Look up a named open cluster's published age, distance and E(B-V) "
            "(Cantat-Gaudin & Anders 2020, Gaia-DR2-based, via VizieR). Resolves common "
            "aliases (e.g. 'M35' -> NGC 2168) through VizieR's own name resolver "
            "automatically, the same way target= does for search_vizier."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"cluster_name": {"type": "string", "description": "Cluster name or alias, e.g. 'NGC 2168' or 'M35'."}},
            "required": ["cluster_name"],
        },
    },
    {
        "name": "select_cluster_members",
        "description": (
            "Remove field-star contamination from Gaia-matched sources by cutting on "
            "parallax and proper motion relative to the cluster's published values. "
            "A simplified stand-in for full elliptical field-star removal -- widen "
            "plx_sigma / pm_tol_mas_yr if too few (or too many) stars survive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "CSV artifact path from crossmatch_gaia (or crossmatch_gaia_by_position, or a run_photometry_on_target source table)."},
                "cluster_name": {"type": "string", "description": "Cluster name, for its literature parallax/PM."},
                "plx_sigma": {"type": "number", "description": "Parallax cut width in units of each star's own parallax error (default 3.0)."},
                "pm_tol_mas_yr": {"type": "number", "description": "Proper-motion cut radius in mas/yr around the cluster's mean PM (default 1.0)."},
            },
            "required": ["csv_path", "cluster_name"],
        },
    },
    {
        "name": "fit_and_compare_hr_diagram",
        "description": (
            "Fetch a PARSEC isochrone near the cluster's published age, fit distance and "
            "E(B-V) to the cluster members' Gaia photometry, and plot the HR diagram with "
            "the fitted isochrone overlaid. Returns the fitted values, the literature "
            "values, and their percent/absolute differences, plus the saved PNG artifact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "members_csv_path": {"type": "string", "description": "CSV artifact path from select_cluster_members."},
                "cluster_name": {"type": "string", "description": "Cluster name, for its literature comparison values."},
                "mh": {"type": "number", "description": "Isochrone metallicity [M/H], solar=0.0 (default; the literature source doesn't publish per-cluster metallicity)."},
                "max_error": {"type": "number", "description": "Drop stars with photometric error above this many mag (default 0.1)."},
                "logage_half_width": {"type": "number", "description": "Half-width in log10(age/yr) of the isochrone age grid to scan around the literature age (default 0.3)."},
            },
            "required": ["members_csv_path", "cluster_name"],
        },
    },
    {
        "name": "run_full_hr_pipeline",
        "description": (
            "Run the entire HR-diagram pipeline in one call FROM AN EXISTING FITS FRAME: "
            "extract photometry from it, cross-match to Gaia, look up literature cluster "
            "parameters, remove field stars, fit an isochrone, and plot the HR diagram "
            "against the literature values. Requires the user to have already supplied a "
            "plate-solved FITS file -- if they have not, and just asked for a cluster's HR "
            "diagram by name, use run_full_hr_pipeline_from_catalog instead; do not ask the "
            "user for a FITS file when a catalog-only answer already covers the request. "
            "Fall back to the individual tools only if this needs tuning or diagnosing. If "
            "the user also wants citations or a literature review for the cluster, pair "
            "this with build_literature_review rather than reciting the Cantat-Gaudin "
            "numbers as if they were the whole literature."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fits_path": {"type": "string", "description": "Path to the plate-solved FITS file."},
                "cluster_name": {"type": "string", "description": "Cluster name or alias, e.g. 'NGC 2168'."},
                "gaia_match_radius_arcsec": {"type": "number", "description": "Gaia cross-match radius in arcsec (default 2.0)."},
                "gaia_mag_limit": {"type": "number", "description": "Gaia G magnitude limit (default 20.0)."},
                "plx_sigma": {"type": "number", "description": "Membership parallax cut width (default 3.0)."},
                "pm_tol_mas_yr": {"type": "number", "description": "Membership proper-motion cut radius, mas/yr (default 1.0)."},
            },
            "required": ["fits_path", "cluster_name"],
        },
    },
    {
        "name": "run_full_hr_pipeline_from_catalog",
        "description": (
            "Build an HR diagram for a named cluster in one call, straight from Gaia DR3 "
            "and literature catalogs -- NO FITS FRAME NEEDED. Looks up the cluster's own "
            "published position/age/distance/E(B-V) (Cantat-Gaudin & Anders 2020, open "
            "clusters only), pulls Gaia DR3 sources around it, removes field stars, and "
            "fits/plots the isochrone. Use this for a plain 'give me information about X "
            "and produce an HR diagram' or 'show me the HR diagram for X' request -- this "
            "is the common case and should be tried before assuming a FITS file is "
            "required. Only fall back to run_full_hr_pipeline if the user has explicitly "
            "supplied their own FITS frame and wants that frame's own photometry used. If "
            "the cluster does not resolve (e.g. it is a globular rather than open cluster, "
            "which this literature source does not cover), this returns not_found rather "
            "than silently substituting a different cluster."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {"type": "string", "description": "Cluster name or alias, e.g. 'NGC 6124' or 'M35'."},
                "radius_arcmin": {"type": "number", "description": "Gaia cone-search radius around the cluster (default 20.0)."},
                "gaia_mag_limit": {"type": "number", "description": "Gaia G magnitude limit (default 17.0)."},
                "plx_sigma": {"type": "number", "description": "Membership parallax cut width (default 3.0)."},
                "pm_tol_mas_yr": {"type": "number", "description": "Membership proper-motion cut radius, mas/yr (default 1.5)."},
                "mh": {"type": "number", "description": "Isochrone metallicity [M/H], solar=0.0 (default)."},
                "max_error": {"type": "number", "description": "Drop stars with photometric error above this many mag (default 0.2)."},
                "logage_half_width": {"type": "number", "description": "Half-width in log10(age/yr) of the isochrone age grid to scan around the literature age (default 0.4)."},
            },
            "required": ["cluster_name"],
        },
    },
    {
        "name": "search_mpc",
        "description": "Return the full reported observation history for one minor "
        "planet from the Minor Planet Center. Confirmed live: this API does zero "
        "name resolution -- 'Halley' raises an error outright, where the formal "
        "designation '1P' succeeds immediately (8273 observations). `designation` "
        "must be one of: an asteroid number (e.g. '1' for Ceres, '433' for Eros); "
        "a periodic comet number with a trailing 'P' (e.g. '1P' for Halley's "
        "Comet); or a full comet designation starting with its type letter (e.g. "
        "'C/2018 E1'). Common/proper names for asteroids and comets are never "
        "accepted -- translate to the formal designation yourself first, from "
        "general knowledge. Single target only, no batching.",
        "input_schema": {
            "type": "object",
            "properties": {
                "designation": {
                    "type": "string",
                    "description": "Formal MPC designation only, e.g. '1' or '1P' "
                    "or 'C/2018 E1'. Never a common name like 'Halley'.",
                }
            },
            "required": ["designation"],
        },
    },
    {
        "name": "search_casda",
        "description": "Search CASDA (the ASKAP radio archive) for data products "
        "around a target. `target` is resolved via SIMBAD internally (which "
        "handles common/colloquial names well), so no translation is needed here "
        "either. ASKAP is a Southern Hemisphere instrument -- northern targets "
        "typically return no results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Object name."},
                "ra_deg": {"type": "number"},
                "dec_deg": {"type": "number"},
                "radius_arcmin": {"type": "number", "description": "Defaults to 2.0."},
                "dataproduct_type": {
                    "type": "string",
                    "description": "'image', 'cube', 'catalogue', 'spectrum', or "
                    "'visibility'.",
                },
                "download": {"type": "boolean", "description": "Defaults to false."},
            },
        },
    },
    {
        "name": "list_pulsar_scans",
        "description": "PULSAR PIPELINE STAGE 0 of 4. List the pulsar observations "
        "available on local disk. There is NO archive query behind the pulsar "
        "tools -- every stage takes a file path, and a path only resolves if the "
        "scan is already on this machine. Call this (or resolve_pulsar_scan) "
        "first when asked to work on a pulsar, instead of guessing a path. "
        "Returns each scan's path, source name, pointing and receiver, read from "
        "the file header.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "resolve_pulsar_scan",
        "description": "PULSAR PIPELINE STAGE 0 of 4. Find the local scan file for a "
        "pulsar name. Accepts any usual spelling ('B0329+54', 'PSR B0329+54', "
        "'psr_b0329_54'), a bare filename, or a full path; matching ignores "
        "punctuation and the declination sign, which Skynet filenames do not "
        "preserve. Use the returned 'path' as the input to "
        "load_pulsar_lightcurve, compute_pulsar_periodogram, "
        "fold_pulsar_lightcurve and sonify_pulsar. An unmatched or ambiguous "
        "name comes back with the available scans listed, so pick from those "
        "rather than inventing a path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Pulsar designation, filename, or path.",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "load_pulsar_lightcurve",
        "description": "PULSAR PIPELINE STAGE 1 of 4. Read a Green Bank / Skynet "
        "pulsar scan from local disk into a light curve: drop the leading "
        "noise-diode calibration block, rebase the time axis, and subtract the "
        "running-median baseline. Handles both file flavours (a '.cal.txt' "
        "continuum scan with two polarizations, or a prefolded 'standard' file "
        "with one). Local only -- no network. Start here: the artifact this "
        "writes is the input to compute_pulsar_periodogram, "
        "fold_pulsar_lightcurve and sonify_pulsar, and passing it on is cheaper "
        "and more consistent than re-reading the raw scan at each stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Local path to a pulsar text file.",
                },
                "back_scale": {
                    "type": "number",
                    "description": "Running-median baseline window in seconds, "
                    "default 3.0. Values under ~2.2x the sample spacing subtract "
                    "the signal along with the baseline.",
                },
                "subtract_background": {
                    "type": "boolean",
                    "description": "Default true, and should stay on -- the "
                    "later stages are far less sensitive without it.",
                },
                "output_name": {"type": "string", "description": "Artifact filename stem."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "compute_pulsar_periodogram",
        "description": "PULSAR PIPELINE STAGE 2 of 4. Lomb-Scargle a pulsar light "
        "curve to FIND ITS PERIOD. This is the only tool that produces a period "
        "from data, so it comes before folding and before folded sonification. "
        "Defaults search the observation's own Nyquist bounds (twice the mean "
        "sample interval, up to 3 s). Local only -- no network. "
        "IMPORTANT: check 'peak_fold_snr' before using 'peak_period_s'. It folds "
        "the data at the peak and measures the resulting pulse -- above ~8 the "
        "peak is real, near 1 it is not. Do NOT rely on 'peak_confidence' for "
        "this: its false-alarm threshold assumes white noise, so mains "
        "interference and baseline red noise routinely read '99.73% Confidence' "
        "while folding to nothing. Also check 'top_peaks': pulsars produce "
        "strong harmonics, so a peak at an integer multiple or fraction of the "
        "reported period may be the real fundamental. A blind search on a single "
        "60-second scan only succeeds for a bright source; if it fails, vary "
        "back_scale, narrow start/stop away from the artifact, or -- for any "
        "known source -- just use search_atnf, which is more accurate than "
        "anything a short scan can measure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A load_pulsar_lightcurve artifact (.ecsv), or "
                    "a raw pulsar file to ingest first.",
                },
                "start": {
                    "type": "number",
                    "description": "Shortest trial period in seconds (or lowest "
                    "frequency in Hz when freq_mode). Defaults to the Nyquist limit.",
                },
                "stop": {
                    "type": "number",
                    "description": "Longest trial period in seconds. Defaults to 3.0.",
                },
                "steps": {
                    "type": "integer",
                    "description": "Grid step count, default 1000. Raise it to "
                    "refine a period once you know roughly where it is -- a "
                    "narrower start/stop with more steps is the accurate way.",
                },
                "freq_mode": {
                    "type": "boolean",
                    "description": "Search a linear frequency grid instead of a "
                    "logarithmic period grid. Default false.",
                },
                "channel": {
                    "type": "string",
                    "description": "'sum' (default, both polarizations added and "
                    "usually most sensitive), 'source1', or 'source2'.",
                },
                "output_name": {"type": "string", "description": "Artifact filename stem."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fold_pulsar_lightcurve",
        "description": "PULSAR PIPELINE STAGE 3 of 4. Fold a pulsar light curve at "
        "a period into a pulse profile: every rotation is stacked on the others, "
        "so a real pulse adds up while noise averages down. This is what makes a "
        "pulsar that is invisible in the raw scan clearly visible. Needs a period "
        "-- get it from compute_pulsar_periodogram, or search_atnf for a known "
        "source. Local only -- no network. "
        "IMPORTANT: folding at the WRONG period returns a flat profile, not an "
        "error. Read 'pulse_snr' to judge: above ~8 is a real detection, near 1 "
        "means the period is wrong or the source is too faint in this scan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A load_pulsar_lightcurve artifact (.ecsv), or "
                    "a raw pulsar file to ingest first.",
                },
                "period_s": {
                    "type": "number",
                    "description": "Fold period in seconds.",
                },
                "bins": {
                    "type": "integer",
                    "description": "Phase bins per period, default 100. Fewer bins "
                    "raise the per-bin signal-to-noise on a faint source; more "
                    "resolve the pulse shape.",
                },
                "phase": {
                    "type": "number",
                    "description": "Shift the profile by this fraction of a period, "
                    "default 0. Useful when the pulse straddles the wrap point.",
                },
                "display_period": {
                    "type": "integer",
                    "description": "1 (default) or 2 -- emit two cycles side by side.",
                },
                "output_name": {"type": "string", "description": "Artifact filename stem."},
            },
            "required": ["path", "period_s"],
        },
    },
    {
        "name": "plot_pulsar",
        "description": "Plot a pulsar artifact as a PNG image: the light curve, the "
        "periodogram, or the folded pulse profile. Pass any artifact from the "
        "pulsar pipeline (or a raw scan) and the chart is chosen from its "
        "columns. Local only -- no network. "
        "The periodogram plot is the most informative of the three when a "
        "period looks wrong: it shows the whole spectrum on a log axis with the "
        "peak marked and the false-alarm lines drawn, so interference and "
        "harmonic combs are visible immediately in a way the numbers alone do "
        "not convey. Axis labels, series names and styling come from "
        "Astromancer's own chart configuration, not from this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "An artifact from load_pulsar_lightcurve, "
                    "compute_pulsar_periodogram or fold_pulsar_lightcurve, or a raw "
                    "pulsar scan.",
                },
                "kind": {
                    "type": "string",
                    "description": "'auto' (default, inferred from the columns), "
                    "'lightcurve', 'periodogram' or 'folded'.",
                },
                "title": {"type": "string", "description": "Override the chart title."},
                "show_hidden_series": {
                    "type": "boolean",
                    "description": "Draw the folded plot's Difference and Sum series, "
                    "which Astromancer declares hidden by default.",
                },
                "output_name": {"type": "string", "description": "PNG filename stem."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "sonify_pulsar",
        "description": "PULSAR PIPELINE STAGE 4 of 4. Render a pulsar as audio you "
        "can listen to: the light curve becomes the amplitude envelope on white "
        "noise, so pulses arrive as bursts of static, and the two polarizations "
        "become the two stereo channels. Local only -- no network. "
        "PASS 'period_s' WHENEVER YOU HAVE ONE (from compute_pulsar_periodogram "
        "or search_atnf). With it, the scan is folded into a pulse profile and "
        "looped at the true rotation rate -- that is the rendering that actually "
        "sounds like a pulsar, because every rotation reinforces the same pulse. "
        "Without it the raw scan plays through once, which leaves a faint pulsar "
        "buried in noise and drifts a few percent from sky time (reported as "
        "'playback_stretch'). Never read a period off the audio; the synthesis "
        "ignores sample timestamps. Returns the WAV path plus observation "
        "metadata; the audio is never inlined.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A load_pulsar_lightcurve artifact (.ecsv), or "
                    "a raw pulsar file to ingest first.",
                },
                "period_s": {
                    "type": "number",
                    "description": "Fold at this period before rendering, so the "
                    "pulse repeats at its true rate. Strongly preferred.",
                },
                "bins": {
                    "type": "integer",
                    "description": "Phase bins when folding, default 100. Ignored "
                    "without period_s.",
                },
                "speed": {
                    "type": "number",
                    "description": "Playback rate. 1.0 (default) is real time; 2.0 "
                    "plays the observation twice as fast, so it passes twice within "
                    "the same output length.",
                },
                "subtract_background": {
                    "type": "boolean",
                    "description": "Remove the running-median baseline before "
                    "rendering. Defaults to true, and should stay on -- it is what "
                    "makes the pulses stand out against the receiver's drifting "
                    "continuum level.",
                },
                "back_scale": {
                    "type": "number",
                    "description": "Background window width in seconds. Defaults to "
                    "3.0. Values below ~2.2x the sample spacing degenerate and "
                    "subtract the signal along with the baseline.",
                },
                "stereo": {
                    "type": "boolean",
                    "description": "Put the second polarization on the right channel. "
                    "Defaults to true; false renders the first polarization alone.",
                },
                "audio_seconds": {
                    "type": "number",
                    "description": "Length of the rendered file, default 60. Shorter "
                    "data loops to fill it. A minute of stereo audio is ~10 MB.",
                },
                "seed": {
                    "type": "integer",
                    "description": "Seeds the noise carrier, so repeat calls produce "
                    "byte-identical audio. Defaults to 0.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Filename stem for the WAV. Defaults to the "
                    "observation's source name.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_photometry_targets",
        "description": "List the local FITS image library photometry can actually "
        "run on. IMPORTANT: there is no live image archive behind photometry -- "
        "unlike every other tool here, `run_photometry_on_target` cannot fetch or "
        "download anything. It only works on a small, fixed set of bundled test "
        "frames (grouped here by category: e.g. 'cluster', 'galaxy', 'nebula', "
        "'globular', 'pn' for planetary nebula, 'star', 'planet'). ALWAYS call this "
        "first if you are not already certain the user's requested object is one of "
        "these bundled stems -- never assume a plausible-sounding target (e.g. a "
        "real astronomical object name) is actually available, and never claim to "
        "have run photometry on something that isn't in this list. No parameters.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_photometry_on_target",
        "description": "Run aperture photometry (source extraction plus, by "
        "default, a verified zero-point solve) on one bundled FITS target. `target` "
        "must be a stem from `list_photometry_targets` (e.g. "
        "'ngc1846_cluster_r_000') or an explicit local path -- call "
        "list_photometry_targets first if you have not already confirmed the name "
        "is bundled; a target that isn't returns an ordinary error result, not an "
        "exception. `use_field_cal` (default true) independently verifies the zero "
        "point by querying a reference catalog over the network and cross-matching "
        "it against detected sources -- this is the ONLY path that populates the "
        "returned `zero_point`, is the only magnitude basis that may be described as "
        "'calibrated', and can take 30-90 seconds; it can also legitimately fail to "
        "find a solution (no catalog match in the field, no network) and fall back "
        "to instrumental-only magnitudes, which is an ordinary outcome, not an "
        "error. Set `use_field_cal` to false for a fast, offline, "
        "instrumental-magnitude-only run when the user only wants source counts/"
        "positions/relative brightness and does not need a verified zero point. "
        "Always writes a photometry plot (and a zero-point fit/residuals plot too "
        "when `use_field_cal` succeeded) to local artifact files -- report their "
        "paths, do not describe their contents as if you had visually inspected "
        "them. Set `write_source_table` true to also get a CSV of every detected "
        "source's sky position -- if the target is a star cluster and the user "
        "wants an HR diagram, that CSV feeds directly into "
        "tools.hr_diagram.crossmatch_gaia/select_cluster_members with no renaming; "
        "for that goal, though, prefer run_full_hr_pipeline(_from_catalog) directly "
        "since it also plots the isochrone fit, which this tool does not.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "A bundled target stem (see "
                    "list_photometry_targets) or an explicit local FITS path.",
                },
                "use_field_cal": {
                    "type": "boolean",
                    "description": "Defaults to true. Set false to skip the "
                    "network catalog zero-point solve.",
                },
                "catalogs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Reference catalogs to query for field "
                    "calibration (e.g. ['APASS', 'PanSTARRS']). Defaults to "
                    "catalogs that support the image's FITS FILTER keyword.",
                },
                "zero_point_mag": {
                    "type": "number",
                    "description": "An explicit photometric zero point to apply "
                    "instead of solving for one. Overrides both the FITS header "
                    "and field calibration; magnitudes from this path are "
                    "unverified, never describe them as calibrated.",
                },
                "write_source_table": {
                    "type": "boolean",
                    "description": "Defaults to false. Set true to additionally "
                    "write a CSV of every detected source's x/y, ra_deg/dec_deg, "
                    "mag, and flux -- e.g. to feed into the HR-diagram pipeline.",
                },
            },
            "required": ["target"],
        },
    },
]

TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "resolve_target": resolve_target,
    "search_simbad": search_simbad,
    "search_simbad_measurements": search_simbad_measurements,
    "search_simbad_bibliography": search_simbad_bibliography,
    "get_paper_abstract": get_paper_abstract,
    "search_ads": search_ads,
    "get_citing_papers": get_citing_papers,
    "get_referenced_papers": get_referenced_papers,
    "build_literature_review": build_literature_review,
    "search_ned": search_ned,
    "list_vizier_catalogs": list_vizier_catalogs,
    "search_vizier": search_vizier,
    "search_atnf": search_atnf,
    "search_mast": search_mast,
    "extract_photometry_from_fits": extract_photometry_from_fits,
    "crossmatch_gaia": crossmatch_gaia,
    "crossmatch_gaia_by_position": crossmatch_gaia_by_position,
    "get_literature_cluster_params": get_literature_cluster_params,
    "select_cluster_members": select_cluster_members,
    "fit_and_compare_hr_diagram": fit_and_compare_hr_diagram,
    "run_full_hr_pipeline": run_full_hr_pipeline,
    "run_full_hr_pipeline_from_catalog": run_full_hr_pipeline_from_catalog,
    "search_mpc": search_mpc,
    "search_casda": search_casda,
    "list_photometry_targets": list_photometry_targets,
    "run_photometry_on_target": run_photometry_on_target,
    "list_pulsar_scans": list_pulsar_scans,
    "resolve_pulsar_scan": resolve_pulsar_scan,
    "load_pulsar_lightcurve": load_pulsar_lightcurve,
    "compute_pulsar_periodogram": compute_pulsar_periodogram,
    "fold_pulsar_lightcurve": fold_pulsar_lightcurve,
    "plot_pulsar": plot_pulsar,
    "sonify_pulsar": sonify_pulsar,
}
