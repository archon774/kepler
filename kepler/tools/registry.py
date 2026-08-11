"""Kepler: tool schemas for wiring ``kepler.tools`` into an agent loop.

Each entry is an Anthropic tool-use schema (``name``, ``description``,
``input_schema``) plus the callable it maps to -- the same shape
``database_tools.py``'s single ``astro_tool_schema`` used, just one schema
per database instead of one schema with a ``database`` enum switch.
``kepler.runner`` is the only consumer that needs this; importing
``kepler.tools.<module>`` directly and calling a function is simpler for
ordinary Python use.
"""

from __future__ import annotations

from typing import Any, Callable

from kepler.tools.ads import (
    build_literature_review,
    get_citing_papers,
    get_referenced_papers,
    search_ads,
)
from kepler.tools.atnf import search_atnf
from kepler.tools.casda import search_casda
from kepler.tools.mast import search_mast
from kepler.tools.mpc import search_mpc
from kepler.tools.ned import search_ned
from kepler.tools.resolve import resolve_target
from kepler.tools.simbad import (
    get_paper_abstract,
    search_simbad,
    search_simbad_bibliography,
    search_simbad_measurements,
)
from kepler.tools.vizier import list_vizier_catalogs, search_vizier

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
    "search_mpc": search_mpc,
    "search_casda": search_casda,
}
