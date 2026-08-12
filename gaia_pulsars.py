import os
from anthropic import Anthropic
import json

client = Anthropic(
    # This is the default and can be omitted
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
)

# def ask_claude(prompt, max_tokens=1024):     
#     message = client.messages.create(
#         model="claude-haiku-4-5-20251001",             
#         max_tokens=1024,                
#         messages=[
#             {"role": "user", "content": "Using the ATNF Pulsar Catalogue, what is the pulsar with right ascension RA: 19h 21m 44.815s and declination DEC:  +21° 53′ 02.25″?"},   
#         ],
#     )
#     return "".join(                          
#         block.text for block in message.content if block.type == "text"
#     )

# tools = [
#     {
#         "name": "find_pulsar",
#         "description": "Find a pulsar in the ATNF Pulsar Catalogue based on its coordinates.",
#         "input_schema": {
#             "type": "object",
#             "properties": {
#                 "ra": {
#                     "type": "string",
#                     "description": "Right ascension in hours, minutes, seconds (e.g., 19h 21m 44.815s)"
#                 },
#                 "dec": {
#                     "type": "string",
#                     "description": "Declination in degrees, arcminutes, arcseconds (e.g., +21° 53′ 02.25″)"
#                 }
#             },
#             "required": ["ra", "dec"]
#         }
#     },
#     {
#         "name": "catologue_pulsars_by_rotation_period",
#         "description": "Create dictionary of pulsars in a given RA and DEC by rotational period, from fastest to slowest.",
#         "input_schema": {
#             "type": "object",
#             "properties": {
#                 "ra": {"type": "string","description": "Right ascension in hours, minutes, seconds (e.g., 19h 21m 44.815s)"},
#                 "dec": {"type": "string","description": "Declination in degrees, arcminutes, arcseconds (e.g., +21° 53′ 02.25″)"},
#                 "name": {"type": "string", "description": "Name of the pulsar using PSR prefix (e.g., PSR B1919+21)"},
#             },
#             "required": ["ra", "dec", "name"],
#         },
#     },
# ]

# messages = [{"role": "user", "content": "What's the name of the pulsar with right ascension RA: 19h 21m 44.815s and declination DEC: +21° 53′ 02.25″?"}]


# # Claude replies with a tool_use block naming the tool and its arguments.
# response = client.messages.create(
#     model="claude-haiku-4-5-20251001",
#     max_tokens=1024,
#     tools=tools,
#     # Ask for at most one tool call per turn.
#     tool_choice={"type": "auto", "disable_parallel_tool_use": False},
#     messages=messages,
# )
# tool_use = next(block for block in response.content if block.type == "tool_use")
# print(f"Claude called {tool_use.name} with {json.dumps(tool_use.input)}")

# # Run the tool, then send the result back in a tool_result block.
# pulsar = "PSR B1919+21"  
# messages += [
#     {"role": "assistant", "content": response.content},
#     {
#         "role": "user",
#         "content": [
#             {"type": "tool_result", "tool_use_id": tool_use.id, "content": pulsar}
#         ],
#     },
# ]
# followup = client.messages.create(
#     model="claude-haiku-4-5-20251001",
#     max_tokens=1024,
#     tools=tools,
#     tool_choice={"type": "auto", "disable_parallel_tool_use": False},
#     messages=messages,
# )


# # Claude uses the result to answer the original question.
# final_text = next(block for block in followup.content if block.type == "text")
# print(final_text.text)


########################


from concurrent.futures import ThreadPoolExecutor

from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.gaia import Gaia
from astroquery.simbad import Simbad

from tools.astrometry import describe_image_wcs, locate_target_in_image
from tools.atnf import search_atnf
from tools.sonify import sonify_pulsar

MODEL = "claude-haiku-4-5-20251001"


SYSTEM_PROMPT = (
    "You are an astronomy research assistant. You have tools to resolve object names to "
    "sky coordinates and to query the Gaia DR3 and SIMBAD databases. When a question "
    "involves several objects, call the relevant tools for ALL of them in the same turn "
    "so they run in parallel. Base every factual claim on tool results rather than prior "
    "knowledge, and state the numbers you used.\n\n"
    "Pulsar-specific tools: search_atnf returns a pulsar's full ATNF Pulsar Catalogue "
    "record (position, period P0, DM, and whatever else ATNF has for it) -- use the "
    "formal designation (e.g. 'J0534+2200' or 'B0531+21'), not a common nickname. "
    "describe_image_wcs and locate_target_in_image read a FITS frame's WCS (field "
    "center, pixel scale, or where a specific target/RA-Dec falls in the frame and "
    "whether it's actually in bounds) -- use locate_target_in_image before assuming an "
    "optical follow-up frame covers a pulsar's position, especially since SIMBAD "
    "sometimes doesn't resolve a pulsar under the same name ATNF uses (pass ra_deg/"
    "dec_deg from search_atnf directly in that case rather than target_name). "
    "sonify_pulsar renders a pulsar's rotation as an audio .wav file from its ATNF "
    "period -- mode='click' (default) plays an audible click once per rotation at any "
    "period; mode='tone' plays a continuous pitch at the rotation frequency, which "
    "needs speed_factor raised well above 1.0 for most pulsars to be audible at all "
    "(most real rotation periods are far below audible pitch) -- check the result's "
    "frequency_hz and warnings before claiming a tone rendering is audible."
)

def resolve_object(name):
    """Resolve an object name (e.g. 'Pleiades', 'M31') to RA/Dec in degrees via SESAME."""
    c = SkyCoord.from_name(name)
    return {"name": name, "ra_deg": round(c.ra.deg, 6), "dec_deg": round(c.dec.deg, 6)} # .dec is from SkyCoord

def find_object_by_coordinates(ra_deg, dec_deg):
    """Find an object name given its RA and Dec in degrees using Simbad."""
    c = SkyCoord(ra=ra_deg, dec=dec_deg)
    result = Simbad.query_region(c, radius=1 * u.arcsec)
    if result is not None and len(result) > 0:
        return {"ra_deg": ra_deg, "dec_deg": dec_deg, "name": result[0]['NAME']}
    return {"ra_deg": ra_deg, "dec_deg": dec_deg, "name": None}

def query_gaia_cone(ra_deg, dec_deg, radius_deg=0.1, mag_limit=21.0):
    """Query Gaia DR3 for sources inside a cone, optionally brighter than mag_limit (G band).

    Returns the source count and the five brightest sources. The ADQL below uses the
    Gaia-archive convention CIRCLE('ICRS', ra, dec, radius); if your Gaia version rejects
    the frame string, drop 'ICRS' from both POINT and CIRCLE.
    """
    adql = f"""
        SELECT source_id, ra, dec, phot_g_mean_mag
        FROM gaiadr3.gaia_source
        WHERE 1 = CONTAINS(POINT('ICRS', ra, dec),
                           CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius_deg}))
          AND phot_g_mean_mag < {mag_limit}
        ORDER BY phot_g_mean_mag ASC
    """
    df = Gaia.launch_job(adql).get_results().to_pandas()
    return {
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "radius_deg": radius_deg,
        "mag_limit": mag_limit,
        "source_count": int(len(df)),
        "brightest": df.head(5).to_dict(orient="records"),
    }


def query_simbad(name):
    """Look up an object's basic SIMBAD record (identifier, coordinates, type)."""
    table = Simbad.query_object(name)
    if table is None or len(table) == 0:
        return {"name": name, "found": False}
    return {"name": name, "found": True,
            "record": table.to_pandas().to_dict(orient="records")[0]}


# Maps the tool NAME Claude uses -> the Python call. Adding a new tool later means:
# write the function, add one schema entry below, add one line here. That's it.

TOOL_DISPATCH = {
    "resolve_object": lambda i: resolve_object(i["name"]),
    "query_gaia_cone": lambda i: query_gaia_cone(
        i["ra_deg"], i["dec_deg"],
        i.get("radius_deg", 0.1), i.get("mag_limit", 21.0),
    ),
    "query_simbad": lambda i: query_simbad(i["name"]),
    "search_atnf": lambda i: search_atnf(i["name"]),
    "describe_image_wcs": lambda i: describe_image_wcs(i["fits_path"]),
    "locate_target_in_image": lambda i: locate_target_in_image(
        i["fits_path"], i.get("target_name"), i.get("ra_deg"), i.get("dec_deg"),
    ),
    "sonify_pulsar": lambda i: sonify_pulsar(
        i["name"], i.get("mode", "click"), i.get("duration_s", 5.0),
        i.get("sample_rate", 44100), i.get("speed_factor", 1.0),
    ),
}


TOOLS = [
    {
        "name": "resolve_object",
        "description": "Resolve an astronomical object name (e.g. 'Pleiades', 'M31', "
                       "'NGC 752') to right ascension and declination in degrees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name or catalog ID."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "query_gaia_cone",
        "description": "Query the Gaia DR3 catalog for stellar sources within a circular "
                       "region of the sky. Returns how many sources fall in the cone and "
                       "the five brightest. Use resolve_object first to get coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ra_deg":     {"type": "number", "description": "Right ascension, degrees."},
                "dec_deg":    {"type": "number", "description": "Declination, degrees."},
                "radius_deg": {"type": "number", "description": "Cone radius in degrees (default 0.1)."},
                "mag_limit":  {"type": "number", "description": "Keep only sources with G magnitude brighter than this (default 21)."},
            },
            "required": ["ra_deg", "dec_deg"],
        },
    },
    {
        "name": "query_simbad",
        "description": "Look up an object's basic record in SIMBAD: main identifier, "
                       "coordinates, and object type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Object name or catalog ID."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_atnf",
        "description": "Return every ATNF Pulsar Catalogue parameter available for a named "
                       "pulsar (position, rotation period P0, DM, and whatever else ATNF has "
                       "on file). Requires the formal designation -- J2000 form preferred "
                       "(e.g. 'J0534+2200'), B1950 also accepted (e.g. 'B0531+21') -- ATNF "
                       "does zero name resolution, so translate a common nickname yourself "
                       "first. A name that isn't a pulsar returns not_found, not an error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Formal pulsar designation, e.g. 'J0534+2200'."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "describe_image_wcs",
        "description": "Read a FITS frame's WCS: whether it has a celestial solution, image "
                       "shape, field center RA/Dec, pixel scale, and rotation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fits_path": {"type": "string", "description": "Path to the FITS file."}
            },
            "required": ["fits_path"],
        },
    },
    {
        "name": "locate_target_in_image",
        "description": "Find where a named target or a fixed RA/Dec falls in one FITS "
                       "frame's pixel grid, and whether that pixel is actually inside the "
                       "image. Pass target_name to resolve via SIMBAD, or ra_deg+dec_deg "
                       "directly -- prefer coordinates from search_atnf for a pulsar, since "
                       "SIMBAD sometimes doesn't resolve it under the same designation. Use "
                       "this before assuming an optical follow-up frame actually covers a "
                       "pulsar's position, rather than searching the whole frame blind.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fits_path": {"type": "string", "description": "Path to the FITS file."},
                "target_name": {"type": "string", "description": "Object name to resolve via SIMBAD."},
                "ra_deg": {"type": "number", "description": "Right ascension in degrees (use with dec_deg instead of target_name)."},
                "dec_deg": {"type": "number", "description": "Declination in degrees (use with ra_deg instead of target_name)."},
            },
            "required": ["fits_path"],
        },
    },
    {
        "name": "sonify_pulsar",
        "description": "Render a pulsar's rotation as an audio .wav file, from its ATNF "
                       "period (P0, looked up automatically). mode='click' (default) plays "
                       "an audible click once per rotation, recognizable as a pulse train at "
                       "any period. mode='tone' plays a continuous pitch at the rotation "
                       "frequency instead -- most real pulsar periods are far too slow for "
                       "this to be audible without raising speed_factor well above 1.0; check "
                       "the result's frequency_hz and warnings before claiming it's audible.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Formal pulsar designation, e.g. 'J0534+2200'."},
                "mode": {"type": "string", "enum": ["click", "tone"], "description": "Defaults to 'click'."},
                "duration_s": {"type": "number", "description": "Length of the rendered audio in seconds (default 5.0)."},
                "sample_rate": {"type": "integer", "description": "Audio sample rate in Hz (default 44100)."},
                "speed_factor": {"type": "number", "description": "Time-compression factor; effective frequency = speed_factor / P0 (default 1.0, the pulsar's real rate)."},
            },
            "required": ["name"],
        },
    },
]

# Loop 

def _run_one_tool(block):
    """Execute a single tool_use block and return its tool_result dict.

    Errors are caught and handed BACK to Claude as an is_error result instead of crashing
    the run -- so a failed query becomes something the agent can see and route around.
    """
    try:
        result = TOOL_DISPATCH[block.name](block.input)
        # search_atnf/describe_image_wcs/locate_target_in_image/sonify_pulsar
        # return tools.models Pydantic instances (KeplerToolModel), not plain
        # dicts like this file's original functions -- model_dump(mode="json")
        # first or json.dumps would fall back to str() on them via default=str,
        # producing an unstructured repr instead of real JSON.
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": json.dumps(payload, default=str)}
    except Exception as exc:
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": f"ERROR running {block.name}: {exc}", "is_error": True}


def run_agent(question, max_turns=8, verbose=True):
    """Send a question and let Claude use tools autonomously until it answers."""
    messages = [{"role": "user", "content": question}]

    for turn in range(1, max_turns + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        # Record Claude's turn (tool requests and/or text) in the running history.
        messages.append({"role": "assistant", "content": response.content})

        # No tool requested => Claude is done. Return its final text.
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        # One turn can carry SEVERAL tool_use blocks -- that's parallel tool use.
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if verbose:
            called = ", ".join(f"{b.name}({json.dumps(b.input)})" for b in tool_uses)
            print(f"[turn {turn}] {len(tool_uses)} tool call(s) in parallel: {called}")

        # Run them concurrently. pool.map preserves order, so each result lines up with
        # its tool_use -- guaranteeing every tool_use id gets exactly one tool_result.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_run_one_tool, tool_uses))

        # ALL tool_results go back in ONE user message (results first in the content list).
        messages.append({"role": "user", "content": results})

    return "Stopped: reached max_turns without a final answer."


if __name__ == "__main__":
    answer = run_agent(
        "Compare how many Gaia sources brighter than G=15 lie within 0.1 degrees of the "
        "centres of the Pleiades and the Hyades. Which field is denser and by how much?"
    )
    print("\n=== FINAL ANSWER ===\n" + answer)

