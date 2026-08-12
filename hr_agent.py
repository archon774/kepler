"""
hr_agent.py - conversational front end for hr_pipeline.py.

Lets you ask things like:

    "Given ngc2168_R.fits, of NGC 2168, create an HR diagram and compare to
    literature values."

and have Claude call the pipeline stages itself, in order, retrying with wider
match radii / looser membership cuts if a step comes back empty. Same
tool-calling shape as gaia_pulsars.py (system prompt, TOOLS schema,
TOOL_DISPATCH, a run_agent loop) -- extended with the HR-diagram pipeline.

Every stage function returns compact JSON (counts, paths, a few example rows)
rather than a full source table, so a frame with thousands of detections
doesn't blow the conversation's context; intermediate results are handed
between tools as CSV paths.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from anthropic import Anthropic

import hr_pipeline as hp

logger = logging.getLogger(__name__)

client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

MODEL = "claude-haiku-4-5-20251001"

WORK_DIR = Path(__file__).parent / "isochrone_cache"
WORK_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = (
    "You build HR (colour-magnitude) diagrams from FITS photometry and compare "
    "them to published star-cluster parameters. The pipeline is: "
    "extract_photometry_from_fits -> crossmatch_gaia -> get_literature_cluster_params "
    "-> select_cluster_members -> fit_and_compare_hr_diagram. run_full_hr_pipeline "
    "does all five steps in one call and is the right choice for a plain request "
    "like 'build the HR diagram for <cluster> from <file>'. Fall back to the "
    "individual steps when something needs diagnosing or tuning: zero Gaia matches "
    "means widen radius_arcsec or check the frame's WCS; zero cluster members "
    "means widen plx_sigma / pm_tol_mas_yr, or double check "
    "get_literature_cluster_params resolved the intended cluster (aliases like "
    "'M35' are resolved automatically, but say so if you had to guess one); a "
    "failed isochrone fetch means the external PARSEC service "
    "(stev.oapd.inaf.it) is unreachable right now -- report that plainly rather "
    "than inventing numbers. Always state the fitted distance/E(B-V)/age "
    "alongside the literature values and by how much they differ, and give the "
    "path to the saved HR-diagram PNG. Base every number on tool output, not "
    "prior knowledge of the cluster."
)


# ---------------------------------------------------------------------------
# Tool implementations (thin wrappers around hr_pipeline.py)
# ---------------------------------------------------------------------------
def _save_csv(df: pd.DataFrame, stem: str) -> str:
    path = WORK_DIR / f"{stem}.csv"
    df.to_csv(path, index=False)
    return str(path)


def tool_extract_photometry(fits_path: str, threshold: float = 2.5) -> dict:
    df = hp.extract_photometry_from_fits(fits_path, threshold=threshold)
    csv_path = _save_csv(df, f"{Path(fits_path).stem}_photometry")
    return {
        "n_sources": len(df),
        "csv_path": csv_path,
        "ra_center_deg": round(float(df["ra_deg"].mean()), 5),
        "dec_center_deg": round(float(df["dec_deg"].mean()), 5),
        "filter": (df["filter"].dropna().iloc[0] if df["filter"].notna().any() else None),
    }


def tool_crossmatch_gaia(csv_path: str, radius_arcsec: float = 2.0, mag_limit: float = 20.0) -> dict:
    df = pd.read_csv(csv_path)
    matched = hp.crossmatch_gaia(df, radius_arcsec=radius_arcsec, mag_limit=mag_limit)
    out_path = _save_csv(matched, f"{Path(csv_path).stem}_gaia")
    return {
        "n_matched": len(matched),
        "n_input": len(df),
        "csv_path": out_path,
        "median_separation_arcsec": round(float(matched["sep_arcsec"].median()), 3),
    }


def tool_get_literature_params(cluster_name: str) -> dict:
    return hp.get_literature_cluster_params(cluster_name)


def tool_select_members(
    csv_path: str, cluster_name: str, plx_sigma: float = 3.0, pm_tol_mas_yr: float = 1.0
) -> dict:
    df = pd.read_csv(csv_path)
    literature = hp.get_literature_cluster_params(cluster_name)
    members = hp.select_cluster_members(df, literature, plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr)
    out_path = _save_csv(members, f"{Path(csv_path).stem}_members")
    return {"n_members": len(members), "n_input": len(df), "csv_path": out_path}


def tool_fit_and_compare(
    members_csv_path: str,
    cluster_name: str,
    mh: float = 0.0,
    max_error: float = 0.1,
    logage_half_width: float = 0.3,
    out_png: str | None = None,
) -> dict:
    members = pd.read_csv(members_csv_path)
    literature = hp.get_literature_cluster_params(cluster_name)
    return hp.fit_and_compare(
        members, literature, cluster_name,
        mh=mh, max_error=max_error, logage_half_width=logage_half_width, out_png=out_png,
    )


def tool_run_full_pipeline(
    fits_path: str,
    cluster_name: str,
    gaia_match_radius_arcsec: float = 2.0,
    gaia_mag_limit: float = 20.0,
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
) -> dict:
    return hp.run_hr_diagram_pipeline(
        fits_path, cluster_name,
        gaia_match_radius_arcsec=gaia_match_radius_arcsec,
        gaia_mag_limit=gaia_mag_limit,
        plx_sigma=plx_sigma,
        pm_tol_mas_yr=pm_tol_mas_yr,
    )


TOOL_DISPATCH = {
    "extract_photometry_from_fits": lambda i: tool_extract_photometry(
        i["fits_path"], i.get("threshold", 2.5)
    ),
    "crossmatch_gaia": lambda i: tool_crossmatch_gaia(
        i["csv_path"], i.get("radius_arcsec", 2.0), i.get("mag_limit", 20.0)
    ),
    "get_literature_cluster_params": lambda i: tool_get_literature_params(i["cluster_name"]),
    "select_cluster_members": lambda i: tool_select_members(
        i["csv_path"], i["cluster_name"], i.get("plx_sigma", 3.0), i.get("pm_tol_mas_yr", 1.0)
    ),
    "fit_and_compare_hr_diagram": lambda i: tool_fit_and_compare(
        i["members_csv_path"], i["cluster_name"],
        i.get("mh", 0.0), i.get("max_error", 0.1), i.get("logage_half_width", 0.3),
        i.get("out_png"),
    ),
    "run_full_hr_pipeline": lambda i: tool_run_full_pipeline(
        i["fits_path"], i["cluster_name"],
        i.get("gaia_match_radius_arcsec", 2.0), i.get("gaia_mag_limit", 20.0),
        i.get("plx_sigma", 3.0), i.get("pm_tol_mas_yr", 1.0),
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
        "name": "crossmatch_gaia",
        "description": (
            "Match detected sources (from extract_photometry_from_fits) to Gaia DR3 by sky "
            "position, attaching Gaia's G/BP/RP magnitudes, parallax and proper motion -- "
            "this is what supplies the colour for the HR diagram, since a single FITS frame "
            "is only one filter."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string", "description": "CSV path from extract_photometry_from_fits."},
                "radius_arcsec": {"type": "number", "description": "Match radius in arcsec (default 2.0). Widen if n_matched comes back 0 or low."},
                "mag_limit": {"type": "number", "description": "Only consider Gaia sources brighter than this G magnitude (default 20)."},
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "get_literature_cluster_params",
        "description": (
            "Look up a named open cluster's published age, distance and E(B-V) "
            "(Cantat-Gaudin & Anders 2020, Gaia-DR2-based, via VizieR). Resolves common "
            "aliases (e.g. 'M35' -> NGC 2168) through SIMBAD automatically."
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
            "Fetch a PARSEC isochrone near the cluster's published age, fit distance and "
            "E(B-V) to the cluster members' Gaia photometry, and plot the HR diagram with "
            "the fitted isochrone overlaid. Returns the fitted values, the literature "
            "values, and their percent/absolute differences, plus the saved PNG path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "members_csv_path": {"type": "string", "description": "CSV path from select_cluster_members."},
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
            },
            "required": ["fits_path", "cluster_name"],
        },
    },
]


def _run_one_tool(block):
    """Execute one tool_use block; exceptions come back as an is_error tool_result
    so the agent can see what failed and adjust, instead of crashing the run."""
    try:
        result = TOOL_DISPATCH[block.name](block.input)
        return {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str)}
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
        "Given _pipeline_test/ngc2168_test.fits, of NGC 2168, create an HR diagram "
        "and compare it to literature values."
    )
    print("\n=== FINAL ANSWER ===\n" + answer)
