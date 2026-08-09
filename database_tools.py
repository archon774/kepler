"""
AstroQuery Tool for Claude (Anthropic API)

An agentic tool for Claude to query astronomical databases (SIMBAD, NED, VizieR, 
ATNF Pulsar Catalogue, and NASA ADS) for context retrieval, data comparison, 
and target identification.
"""

import os
import json
import pandas as pd
import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.simbad import Simbad
from astroquery.ipac.ned import Ned
from astroquery.vizier import Vizier
import psrqpy
import ads
import anthropic

# ==========================================
# 1. TOOL SCHEMA DEFINITION FOR CLAUDE
# ==========================================
astro_tool_schema = {
    "name": "query_astronomical_databases",
    "description": (
        "Queries astronomical databases (SIMBAD, NED, VizieR, ATNF, NASA ADS) "
        "to retrieve celestial object data, catalogs, and literature records for data comparison."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "database": {
                "type": "string",
                "description": (
                    "The database to query: 'SIMBAD' (galactic/stellar objects), "
                    "'NED' (extragalactic targets), 'VIZIER' (photometric/astrometric catalogs), "
                    "'ATNF' (radio pulsars), or 'ADS' (academic literature)."
                ),
                "enum": ["SIMBAD", "NED", "VIZIER", "ATNF", "ADS"]
            },
            "query_type": {
                "type": "string",
                "description": (
                    "Type of query: 'object_name' or 'region_search' (by coordinates). "
                    "For ADS, this parameter is ignored in favor of keyword matching."
                ),
                "enum": ["object_name", "region_search"]
            },
            "target": {
                "type": "string",
                "description": (
                    "For SIMBAD/NED/VIZIER/ATNF: Object identifier (e.g. 'Betelgeuse', 'M31') "
                    "or coordinates ('00 42 44.3 +41 16 09'). "
                    "For ADS: Solr search syntax (e.g., 'title:\"Andromeda\" AND abs:\"distance\"')."
                )
            },
            "radius_arcmin": {
                "type": "number",
                "description": "Search radius in arcminutes for region searches. Defaults to 2.0."
            },
            "vizier_catalog": {
                "type": "string",
                "description": "Specific VizieR catalog ID (e.g., 'II/246'). Optional, only used if database is VIZIER."
            }
        },
        "required": ["database", "query_type", "target"]
    }
}


# ==========================================
# 2. TOOL EXECUTION CLASS
# ==========================================
class AstroQueryTool:
    def __init__(self, ads_token: str = None):
        """
        Initializes query clients with configured fields, timeouts, and API tokens.
        """
        # Configure SIMBAD defaults and timeouts
        self.simbad = Simbad()
        self.simbad.add_votable_fields('V', 'rvz_radvel', 'sp')
        self.simbad.TIMEOUT = 15

        # Configure NED timeouts
        Ned.TIMEOUT = 15

        # Configure NASA ADS Token (reads environment variable if not passed)
        token = ads_token or os.environ.get("ADS_DEV_KEY")
        if token:
            ads.config.token = token

    def execute(self, arguments: dict) -> dict:
        """
        Routes Claude's tool argument payload to the corresponding query method.
        """
        db = arguments.get("database")
        q_type = arguments.get("query_type")
        target = arguments.get("target")
        radius = arguments.get("radius_arcmin", 2.0)
        catalog = arguments.get("vizier_catalog")

        try:
            if db == "SIMBAD":
                return self._query_simbad(q_type, target, radius)
            elif db == "NED":
                return self._query_ned(q_type, target, radius)
            elif db == "VIZIER":
                return self._query_vizier(q_type, target, radius, catalog)
            elif db == "ATNF":
                return self._query_atnf(target)
            elif db == "ADS":
                return self._query_ads(target)
            else:
                return {"error": f"Unknown database: {db}"}
        except Exception as e:
            return {"error": str(e)}

    def _query_simbad(self, q_type: str, target: str, radius: float) -> dict:
        if q_type == "object_name":
            result = self.simbad.query_object(target)
        else:
            coord = SkyCoord(target, unit=(u.hourangle, u.deg))
            result = self.simbad.query_region(coord, radius=radius * u.arcmin)
        return self._table_to_dict(result)

    def _query_ned(self, q_type: str, target: str, radius: float) -> dict:
        if q_type == "object_name":
            result = Ned.query_object(target)
        else:
            coord = SkyCoord(target, unit=(u.hourangle, u.deg))
            result = Ned.query_region(coord, radius=radius * u.arcmin)
        return self._table_to_dict(result)

    def _query_vizier(self, q_type: str, target: str, radius: float, catalog: str = None) -> dict:
        vizier = Vizier(columns=['*'])
        if catalog:
            vizier.catalog = catalog

        if q_type == "object_name":
            result_list = vizier.query_object(target)
        else:
            coord = SkyCoord(target, unit=(u.hourangle, u.deg))
            result_list = vizier.query_region(coord, radius=radius * u.arcmin)

        if not result_list:
            return {"status": "No data found"}

        return self._table_to_dict(result_list[0])

    def _query_atnf(self, target: str) -> dict:
        query = psrqpy.QueryATNF(params=['PSRJ', 'P0', 'DM', 'AGE'], psrs=[target])
        df = query.pandas
        if df.empty:
            return {"status": "No pulsar found"}
        return {"data": df.to_dict(orient='records')}

    def _query_ads(self, target: str) -> dict:
        if not ads.config.token:
            return {"error": "NASA ADS API token missing. Set ADS_DEV_KEY in environment or pass to AstroQueryTool."}

        papers = ads.SearchQuery(
            q=target,
            sort="citation_count desc",
            fl=["title", "author", "bibcode", "citation_count"]
        )

        results = []
        for i, paper in enumerate(papers):
            if i >= 5:
                break
            results.append({
                "title": paper.title[0] if paper.title else "N/A",
                "authors": paper.author[:3] if paper.author else [],
                "bibcode": paper.bibcode,
                "citations": paper.citation_count if paper.citation_count else 0
            })

        if not results:
            return {"status": f"No papers found for query: {target}"}

        return {"data": results}

    def _table_to_dict(self, astropy_table) -> dict:
        """
        Converts Astropy tables to JSON-serializable dictionaries while handling 
        byte-decoding and Pandas 4 compatibility.
        """
        if astropy_table is None or len(astropy_table) == 0:
            return {"status": "No data found"}

        df = astropy_table.to_pandas()

        # Handle byte strings and explicitly include 'str' alongside 'object' for Pandas 4+
        for col in df.select_dtypes(include=['object', 'str']).columns:
            df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

        df = df.fillna("N/A")
        return {"data": df.head(5).to_dict(orient="records")}


# ==========================================
# 3. EXAMPLE INTEGRATION BOILERPLATE
# ==========================================
def main():
    """
    Example runner demonstrating tool call handling with Claude.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Set your ANTHROPIC_API_KEY environment variable to execute queries.")
        return

    client = anthropic.Anthropic(api_key=anthropic_key)
    tool_handler = AstroQueryTool()

    # INSERT YOUR QUERY HERE
    user_message = "" 
    
    if not user_message:
        print("Please provide a query string in the `user_message` variable.")
        return

    print(f"User: {user_message}\nSending request to Claude...")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=5120,
        tools=[astro_tool_schema],
        messages=[{"role": "user", "content": user_message}]
    )

    if response.stop_reason == "tool_use":
        for content_block in response.content:
            if content_block.type == "tool_use":
                tool_name = content_block.name
                tool_args = content_block.input

                if tool_name == "query_astronomical_databases":
                    print(f"[*] Executing tool call for database: {tool_args.get('database')}")
                    result = tool_handler.execute(tool_args)
                    print("\nTool Output:")
                    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()