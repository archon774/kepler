"""
hr_agent.py - conversational front end for tools.hr_diagram.

Lets you ask things like:

    "Given ngc2168_R.fits, of NGC 2168, create an HR diagram and compare to
    literature values."

    "Using afterglow_photometry_ngc1851.csv, create an HR diagram for NGC 1851
    in B-R vs V and compare to literature."

and have Claude call the pipeline stages itself, in order, retrying with wider
match radii / looser membership cuts if a step comes back empty. Works for
open clusters (Cantat-Gaudin & Anders 2020) and globular clusters (Harris 2010
+ Vasiliev & Baumgardt 2021) alike, and for either a FITS frame or an existing
photometry table as the starting point. Same tool-calling shape as
gaia_pulsars.py (system prompt, TOOLS schema, TOOL_DISPATCH, a run_agent loop)
-- extended with the HR-diagram pipeline.

The actual algorithm/tool logic lives in algorithms.hrdiagram (algorithm package)
and tools.hr_diagram (thin wrappers returning Pydantic models from
tools.models) -- this file is only the conversational wiring around it, per
the design doc's "no orchestration framework" stance (docs/tool-architecture.md
SS6): a serving/agent surface should be generated from the same plain
functions and models, not hand-duplicate their logic.

Every stage function returns compact JSON (counts, paths, a few example rows)
rather than a full source table, so a frame with thousands of detections
doesn't blow the conversation's context; intermediate results are handed
between tools as CSV paths.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from anthropic import Anthropic

from tools import hr_diagram as hp

logger = logging.getLogger(__name__)

client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "You are a general-purpose assistant. You also have tools for building HR "
    "(colour-magnitude) diagrams from photometry -- either measured yourself "
    "from a FITS frame, or an existing photometry table -- and comparing them "
    "to published star-cluster parameters, for open OR globular clusters. Use "
    "those tools when a question actually calls for them; for anything else, "
    "just answer normally, the way you would with no tools at all -- don't "
    "preface an unrelated answer with a note about what you're specialized in "
    "or redirect back to HR diagrams unless the person's actual question is "
    "about one. "
    "Two parallel pipelines depending on the input: "
    "(1) FITS frame: extract_photometry_from_fits -> crossmatch_gaia -> "
    "get_literature_cluster_params -> select_cluster_members -> "
    "fit_and_compare_hr_diagram, or run_full_hr_pipeline in one call. "
    "(2) Existing photometry table (e.g. an Afterglow export): "
    "load_photometry_table -> crossmatch_gaia -> get_literature_cluster_params -> "
    "select_cluster_members -> fit_and_compare_hr_diagram (with blue/red/lum set "
    "to the table's own filters, e.g. B/R/V), or "
    "run_full_hr_pipeline_from_photometry_table in one call. In both cases, "
    "crossmatch_gaia is what makes select_cluster_members' field-star removal "
    "possible -- it's the only thing that attaches parallax/proper motion, "
    "whether or not you end up using Gaia's own G/BP/RP magnitudes for the "
    "diagram itself. get_literature_cluster_params tries the open-cluster catalog "
    "first, then the globular-cluster catalogs; check 'cluster_type' in what it "
    "returns, since globular results carry a real 'feh' metallicity (used "
    "automatically by fit_and_compare_hr_diagram unless you override mh) and "
    "typically 'age_is_literature_default': true (Harris doesn't publish "
    "per-cluster ages for globulars, so a ~12.6 Gyr default is used -- say so "
    "when reporting a globular-cluster age comparison, since the 'literature' "
    "age isn't really cluster-specific). When starting from an existing "
    "photometry table (path 2), ask whether its magnitudes already had "
    "interstellar reddening (E(B-V)) removed as part of an earlier calibration "
    "step, before running fit_and_compare_hr_diagram -- don't assume they "
    "haven't. If they have, pass that value as pre_dereddened_ebv; otherwise "
    "the fitted E(B-V) only reflects the residual left in the magnitudes you "
    "were given, not the true total, and comparing it directly to literature "
    "(always a total, foreground value) understates it. "
    "Fall back to the individual steps when something needs diagnosing or "
    "tuning: zero Gaia matches means widen radius_arcsec or check the frame's "
    "WCS; zero cluster members means widen plx_sigma / pm_tol_mas_yr, or double "
    "check get_literature_cluster_params resolved the intended cluster (aliases "
    "like 'M35' -> NGC 2168 or '47 Tuc' -> NGC 104 are resolved automatically, "
    "but say so if you had to guess one); if get_literature_cluster_params fails "
    "entirely (name not in either catalog) but a diagram is still wanted, use "
    "plot_observed_cmd for a plain (uncorrected, unfitted) CMD instead of giving "
    "up. If the cluster is very young (roughly under a few hundred Myr, still "
    "on or near the pre-main-sequence) or the person mentions starspots/spot "
    "coverage, consider isochrone_source='spots' (Somers, Pinsonneault & Cao "
    "2019) instead of the default 'mist' -- standard spot-free grids (MIST, "
    "PARSEC) are known to systematically mismatch active, spotted pre-main-"
    "sequence stars, which 'spots' models via a starspot covering-fraction "
    "axis (Fspot) that's scanned alongside age/distance/E(B-V) and reported as "
    "fitted['fspot'] in the result -- a fit result, not a literature-known "
    "property, so phrase it that way ('the fit preferred a covering fraction "
    "of ~X%'), and note it's solar-metallicity only. An isochrone fetch "
    "failure with isochrone_source='mist' (the default) means the one-time "
    "~150MB grid download from mist.science failed -- likely a network issue, "
    "retry. With isochrone_source='parsec' it means stev.oapd.inaf.it is "
    "unreachable or rate-limiting; try 'mist' instead, which downloads once "
    "and runs off a local cache from then on. With isochrone_source='spots' "
    "it means the one-time download from Zenodo (zenodo.org) failed -- also "
    "likely a network issue, retry. Either way, "
    "report the failure plainly rather than inventing numbers. The fit itself "
    "matches every band a member star actually has (not just blue/red/lum) -- "
    "a Gaia-crossmatched member table's G/BP/RP count too, alongside whatever "
    "the original photometry was. When a fit "
    "succeeds, always state the fitted distance/E(B-V)/age alongside the "
    "literature values and by how much they differ, and give the path to the "
    "saved HR-diagram PNG. Always check the result's 'warnings' list too -- "
    "isochrone_source='spots' fits report there whenever member stars were "
    "excluded for falling outside the SPOTS grid's coverage (it only models "
    "up to ~1.3 Msun pre-main-sequence stars, so a young cluster's more "
    "massive members are often simply unrepresentable by it); say how many "
    "were excluded and note the fit only covers the remaining lower-mass "
    "members, not the whole photometric catalogue. For a globular-cluster "
    "MIST fit, the horizontal branch is included in the isochrone match, but "
    "a single isochrone can only draw one specific track through it -- real "
    "horizontal-branch stars scatter across a range of colours (from star-to-"
    "star differences in red-giant-branch mass loss) that one deterministic "
    "track cannot reproduce, so don't treat close agreement (or disagreement) "
    "there as validating the fit the way main-sequence agreement would. Base "
    "every number on tool output, not prior knowledge of the cluster.\n\n"
    "Two things are required in every final answer that reports HR-diagram "
    "results, not just when something looks wrong:\n"
    "1. Name every catalogue a number came from: literature['source'] for "
    "cluster parameters (say 'Cantat-Gaudin & Anders 2020' for open clusters; "
    "for globulars say BOTH 'Harris 2010' for distance/E(B-V)/[Fe/H] AND "
    "'Vasiliev & Baumgardt 2021' for parallax/proper motion -- they're "
    "different catalogues, don't collapse them into one name), and which "
    "isochrone grid produced the plot (MIST v1.2, PARSEC, or the SPOTS grid -- "
    "Somers, Pinsonneault & Cao 2019 -- from isochrone_source). If a cluster "
    "name was resolved through a SIMBAD alias, say what it resolved to.\n"
    "2. Flag uncertainty and phrase unresolved numbers as a working estimate, "
    "not a settled fact, whenever any of: age_is_literature_default is true "
    "(the globular-cluster 'literature' age is a fabricated placeholder, not a "
    "measurement -- never treat a fit's agreement or disagreement with it as "
    "meaningful); n_stars_fitted is small (rough guide: under ~50-100); the "
    "photometry has no main-sequence turnoff (giant-branch-only data barely "
    "constrains age at all, regardless of what number the fit returns); "
    "isochrone_source is 'spots' (fitted['fspot'] is a fit result scanned over "
    "6 discrete grid values, not a literature-known cluster property, and the "
    "grid is solar-metallicity only); the result's 'warnings' list is non-empty "
    "(e.g. members excluded for falling outside an isochrone grid's coverage); "
    "pre_dereddened_ebv might be nonzero but "
    "wasn't confirmed; n_gaia_matched "
    "is much smaller than n_detected or membership cuts are loose (crowded-"
    "field fits are known to land on visibly different numbers run to run); "
    "or a literature comparison shows a large percent difference. In those "
    "cases use language like 'the fit suggests', 'consistent with', 'not well "
    "constrained by this data' -- not a bare 'the distance is X kpc'."
)


# ---------------------------------------------------------------------------
# Tool dispatch -- direct calls into tools.hr_diagram; each function
# already returns the right (Pydantic-model) shape, so no local wrapping is
# needed beyond pulling arguments out of the tool_use input dict.
# ---------------------------------------------------------------------------
TOOL_DISPATCH = {
    "extract_photometry_from_fits": lambda i: hp.extract_photometry_from_fits(
        i["fits_path"], i.get("threshold", 2.5)
    ),
    "load_photometry_table": lambda i: hp.load_photometry_table(
        i["csv_path"], i.get("mag_col", "calibrated_mag"), i.get("err_col", "mag_error")
    ),
    "crossmatch_gaia": lambda i: hp.crossmatch_gaia(
        i["csv_path"], i.get("radius_arcsec", 2.0), i.get("mag_limit", 20.0)
    ),
    "get_literature_cluster_params": lambda i: hp.get_literature_cluster_params(i["cluster_name"]),
    "select_cluster_members": lambda i: hp.select_cluster_members(
        i["csv_path"], i["cluster_name"], i.get("plx_sigma", 3.0), i.get("pm_tol_mas_yr", 1.0)
    ),
    "fit_and_compare_hr_diagram": lambda i: hp.fit_hr_diagram(
        i["members_csv_path"], i["cluster_name"],
        i.get("blue", "BP"), i.get("red", "RP"), i.get("lum", "G"),
        i.get("mh"), i.get("max_error", 0.1), i.get("logage_half_width", 0.3),
        i.get("isochrone_source", "mist"), i.get("pre_dereddened_ebv", 0.0),
    ),
    "plot_observed_cmd": lambda i: hp.plot_observed_cmd(
        i["csv_path"], i["blue"], i["red"], i["lum"], i.get("max_error"), i.get("title"),
    ),
    "run_full_hr_pipeline": lambda i: hp.run_hr_diagram_pipeline(
        i["fits_path"], i["cluster_name"],
        i.get("gaia_match_radius_arcsec", 2.0), i.get("gaia_mag_limit", 20.0),
        i.get("plx_sigma", 3.0), i.get("pm_tol_mas_yr", 1.0),
        i.get("isochrone_source", "mist"),
    ),
    "run_full_hr_pipeline_from_photometry_table": lambda i: hp.run_hr_diagram_pipeline_from_photometry(
        i["csv_path"], i["cluster_name"],
        i.get("blue", "B"), i.get("red", "R"), i.get("lum", "V"),
        i.get("mag_col", "calibrated_mag"), i.get("err_col", "mag_error"),
        i.get("gaia_match_radius_arcsec", 2.0), i.get("gaia_mag_limit", 21.0),
        i.get("plx_sigma", 3.0), i.get("pm_tol_mas_yr", 1.0),
        i.get("isochrone_source", "mist"), i.get("pre_dereddened_ebv", 0.0),
    ),
}


TOOLS = [
    {
        "name": "extract_photometry_from_fits",
        "description": (
            "Detect sources in a plate-solved FITS frame and measure their instrumental "
            "photometry (position, magnitude). The frame must already have a WCS in its "
            "header. Returns a summary + a CSV path for the next step."
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
        "name": "load_photometry_table",
        "description": (
            "Load an existing calibrated photometry table (e.g. an Afterglow export) instead "
            "of measuring photometry from a FITS frame. Afterglow exports are long-format: one "
            "row per source per filter. This reshapes it to one row per source with a magnitude "
            "(+ error) column per filter, ready for crossmatch_gaia(). Use this as the first "
            "step whenever you already have a photometry CSV rather than a raw FITS frame."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "Path to the photometry CSV."},
                "mag_col": {"type": "string", "description": "Column holding the calibrated magnitude (default 'calibrated_mag', i.e. mag + zero_point_correction -- not the raw 'mag' column)."},
                "err_col": {"type": "string", "description": "Column holding the magnitude error (default 'mag_error')."},
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "crossmatch_gaia",
        "description": (
            "Match sources (from extract_photometry_from_fits OR load_photometry_table) to "
            "Gaia DR3 by sky position, attaching Gaia's G/BP/RP magnitudes, parallax and proper "
            "motion. For FITS-frame input this is what supplies the colour for the HR diagram, "
            "since a single frame is only one filter. For an existing photometry table (which "
            "already has its own filters), this is instead how you get parallax/proper motion "
            "onto sources that didn't have any -- i.e. it's the field-star-removal prerequisite; "
            "the table's own magnitude columns pass through unchanged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "CSV path from extract_photometry_from_fits or load_photometry_table."},
                "radius_arcsec": {"type": "number", "description": "Match radius in arcsec (default 2.0). Widen if n_matched comes back 0 or low."},
                "mag_limit": {"type": "number", "description": "Only consider Gaia sources brighter than this G magnitude (default 20)."},
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "get_literature_cluster_params",
        "description": (
            "Look up a named cluster's published age (or a typical old-cluster default for "
            "globulars), distance, E(B-V), and metallicity. Tries the open-cluster catalog "
            "first (Cantat-Gaudin & Anders 2020, Gaia-DR2-based), then falls back to globular-"
            "cluster catalogs (Harris 2010 + Vasiliev & Baumgardt 2021 for Gaia astrometry) if "
            "not found there. Resolves common aliases (e.g. 'M35' -> NGC 2168, '47 Tuc' -> "
            "NGC 104) through SIMBAD automatically. Check the returned 'cluster_type' ('open' "
            "or 'globular'); globular results carry a 'feh' metallicity and may have "
            "'age_is_literature_default': true (Harris doesn't publish per-cluster ages, so a "
            "typical ~12.6 Gyr default is used unless you know better for this specific cluster)."
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
                "csv_path": {"type": "string", "description": "CSV path from crossmatch_gaia."},
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
            "Fetch an isochrone near the cluster's published age, fit distance and "
            "E(B-V) to the cluster members' photometry, and plot the HR diagram with "
            "the fitted isochrone overlaid. Returns the fitted values, the literature "
            "values, and their percent/absolute differences, plus the saved PNG path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "members_csv_path": {"type": "string", "description": "CSV path from select_cluster_members."},
                "cluster_name": {"type": "string", "description": "Cluster name, for its literature comparison values."},
                "blue": {"type": "string", "description": "Blue-band column name in members_csv_path (default 'BP', the Gaia band; use e.g. 'B' for a B/V/R/I photometry table)."},
                "red": {"type": "string", "description": "Red-band column name (default 'RP'; e.g. 'R')."},
                "lum": {"type": "string", "description": "Magnitude/luminosity column name for the y-axis (default 'G'; e.g. 'V')."},
                "mh": {"type": "number", "description": "Isochrone metallicity [M/H], solar=0.0. Leave unset to auto-use the literature value: globular clusters carry a real 'feh' from Harris; open clusters have none, so solar is used."},
                "max_error": {"type": "number", "description": "Drop stars with photometric error above this many mag (default 0.1)."},
                "logage_half_width": {"type": "number", "description": "Half-width in log10(age/yr) of the isochrone age grid to scan around the literature age (default 0.3)."},
                "isochrone_source": {
                    "type": "string",
                    "enum": ["mist", "parsec", "spots"],
                    "description": (
                        "Where the isochrone grid comes from. 'mist' (default): downloaded whole and "
                        "cached locally, so it doesn't depend on a live per-request service. 'parsec': "
                        "stev.oapd.inaf.it's web form, fetched per request -- try this as a cross-check, "
                        "or if you specifically need a PARSEC-based comparison; that service has been "
                        "observed to rate-limit or reset connections under repeated automated use. "
                        "'spots': the Somers/Pinsonneault/Cao (2019) SPOTS grid of pre-main-sequence "
                        "isochrones with a starspot covering-fraction axis (Fspot) -- use this for young "
                        "clusters (roughly under a few hundred Myr, pre-main-sequence) where standard "
                        "spot-free grids like MIST/PARSEC are known to mismatch active, spotted stars. "
                        "The fit also scans Fspot and reports the winning covering fraction as "
                        "fitted['fspot'] -- a fit result, not a literature-known property, and the grid "
                        "is solar-metallicity only so 'mh' has no effect with this source."
                    ),
                },
                "pre_dereddened_ebv": {
                    "type": "number",
                    "description": (
                        "Set this if members_csv_path's magnitudes already had E(B-V) removed "
                        "upstream (e.g. baked into a photometric calibration/zero-point step before "
                        "this file was produced). The fit itself always solves for whatever residual "
                        "colour excess remains in the magnitudes it's given; this value gets added to "
                        "that residual to report a *total* E(B-V) comparable to literature (which is "
                        "always a total, foreground value) -- leaving it at 0 when it shouldn't be "
                        "makes the fitted E(B-V) look artificially small next to the literature number."
                    ),
                },
            },
            "required": ["members_csv_path", "cluster_name"],
        },
    },
    {
        "name": "run_full_hr_pipeline",
        "description": (
            "Run the entire pipeline in one call: extract photometry from a FITS frame, "
            "cross-match to Gaia, look up literature cluster parameters, remove field "
            "stars, fit an isochrone, and plot the HR diagram against the literature "
            "values. Use this for a plain 'build the HR diagram for X from Y' request; "
            "fall back to the individual tools only if this needs tuning or diagnosing."
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
                "isochrone_source": {
                    "type": "string",
                    "enum": ["mist", "parsec", "spots"],
                    "description": "Isochrone grid source; 'mist' (default) is cached locally after a one-time download, 'parsec' fetches per-request from stev.oapd.inaf.it, 'spots' is the Somers/Pinsonneault/Cao (2019) starspot-inflated pre-main-sequence grid for young clusters (also scans starspot covering fraction Fspot, reported as fitted['fspot']).",
                },
            },
            "required": ["fits_path", "cluster_name"],
        },
    },
    {
        "name": "run_full_hr_pipeline_from_photometry_table",
        "description": (
            "Run the entire pipeline in one call starting from an existing photometry table "
            "(e.g. an Afterglow export) instead of a FITS frame: load it, cross-match to Gaia "
            "for parallax/proper motion, look up literature cluster parameters (open or "
            "globular), remove field stars, fit an isochrone, and plot the HR diagram against "
            "the literature values. Use this for a plain 'build the HR diagram for X from "
            "<photometry CSV>' request; fall back to load_photometry_table / crossmatch_gaia / "
            "select_cluster_members / fit_and_compare_hr_diagram individually if this needs "
            "tuning or diagnosing (e.g. n_gaia_matched or n_members coming back very low)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "Path to the photometry CSV (Afterglow-style long format)."},
                "cluster_name": {"type": "string", "description": "Cluster name or alias -- open or globular, e.g. 'NGC 2168' or 'NGC 1851'."},
                "blue": {"type": "string", "description": "Blue-band column name (default 'B')."},
                "red": {"type": "string", "description": "Red-band column name (default 'R')."},
                "lum": {"type": "string", "description": "Magnitude column name for the y-axis (default 'V')."},
                "mag_col": {"type": "string", "description": "Calibrated-magnitude column in the source CSV (default 'calibrated_mag')."},
                "err_col": {"type": "string", "description": "Magnitude-error column in the source CSV (default 'mag_error')."},
                "gaia_match_radius_arcsec": {"type": "number", "description": "Gaia cross-match radius in arcsec (default 2.0)."},
                "gaia_mag_limit": {"type": "number", "description": "Gaia G magnitude limit (default 21.0 -- looser than the FITS pipeline's 20.0, since globular-cluster members are often fainter/farther)."},
                "plx_sigma": {"type": "number", "description": "Membership parallax cut width (default 3.0)."},
                "pm_tol_mas_yr": {"type": "number", "description": "Membership proper-motion cut radius, mas/yr (default 1.0)."},
                "isochrone_source": {
                    "type": "string",
                    "enum": ["mist", "parsec", "spots"],
                    "description": "Isochrone grid source; 'mist' (default) is cached locally after a one-time download, 'parsec' fetches per-request from stev.oapd.inaf.it, 'spots' is the Somers/Pinsonneault/Cao (2019) starspot-inflated pre-main-sequence grid for young clusters (also scans starspot covering fraction Fspot, reported as fitted['fspot']).",
                },
                "pre_dereddened_ebv": {
                    "type": "number",
                    "description": (
                        "Set this if mag_col's magnitudes already had E(B-V) removed as part of an "
                        "earlier calibration step, so the reported E(B-V) is a true total comparable "
                        "to literature rather than understating it. Ask the user if they applied a "
                        "reddening/extinction correction before producing this file -- don't assume 0."
                    ),
                },
            },
            "required": ["csv_path", "cluster_name"],
        },
    },
    {
        "name": "plot_observed_cmd",
        "description": (
            "Plot a plain observed colour-magnitude diagram (blue - red vs lum) with no "
            "distance-modulus or reddening correction -- apparent magnitudes as measured, not "
            "an absolute-magnitude HR diagram. Use this when get_literature_cluster_params "
            "can't resolve the cluster at all (so there's nothing to fit against), or when the "
            "goal is just the raw diagram rather than a literature comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "CSV path with blue/red/lum magnitude columns (e.g. from load_photometry_table)."},
                "blue": {"type": "string", "description": "Blue-band column name, e.g. 'B'."},
                "red": {"type": "string", "description": "Red-band column name, e.g. 'R'."},
                "lum": {"type": "string", "description": "Magnitude column name for the y-axis, e.g. 'V'."},
                "max_error": {"type": "number", "description": "Optional: drop stars with photometric error above this many mag."},
                "title": {"type": "string", "description": "Optional plot title."},
            },
            "required": ["csv_path", "blue", "red", "lum"],
        },
    },
]


def _run_one_tool(block):
    """Execute one tool_use block; exceptions come back as an is_error tool_result
    so the agent can see what failed and adjust, instead of crashing the run."""
    try:
        result = TOOL_DISPATCH[block.name](block.input)
        # tools.hr_diagram functions return KeplerToolModel instances,
        # not dicts -- most failures surface as a populated `errors` field on
        # the model rather than a raised exception (see docs/tool-architecture.md),
        # so this still needs to serialize cleanly even on the "expected failure" path.
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        return {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(payload)}
    except Exception as exc:
        return {
            "type": "tool_result", "tool_use_id": block.id,
            "content": f"ERROR running {block.name}: {exc}", "is_error": True,
        }


def run_agent(question: str, max_turns: int = 10, verbose: bool = True) -> str:
    """Send a question and let Claude call the HR-diagram pipeline tools until it answers."""
    messages = [{"role": "user", "content": question}]

    for turn in range(1, max_turns + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            tool_choice={"type": "auto", "disable_parallel_tool_use": False},
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if verbose:
            called = ", ".join(f"{b.name}({json.dumps(b.input)})" for b in tool_uses)
            print(f"[turn {turn}] {len(tool_uses)} tool call(s): {called}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_run_one_tool, tool_uses))

        messages.append({"role": "user", "content": results})

    return "Stopped: reached max_turns without a final answer."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    answer = run_agent(
        "Given ngc2168_test.fits, of NGC 2168, create an HR diagram "
        "and compare it to literature values."
    )
    print("\n=== FINAL ANSWER ===\n" + answer)
