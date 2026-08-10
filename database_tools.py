"""
AstroQuery Tool for Claude (Anthropic API)
Streaming & Multi-Turn Agentic Runner - Universal Astronomy, Historical Archives, MAST Universal File Dumper, & MPC Queries
"""

import os
import re
import json
import pandas as pd
import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.simbad import Simbad
from astroquery.ipac.ned import Ned
from astroquery.vizier import Vizier
from astroquery.mast import Observations
from astroquery.mpc import MPC
import psrqpy
import ads
import anthropic

# ==========================================
# 1. TOOL SCHEMA DEFINITION FOR CLAUDE
# ==========================================
astro_tool_schema = {
    "name": "query_astronomical_databases",
    "description": (
        "Queries astronomical databases (SIMBAD, NED, VizieR, ATNF, NASA ADS, MAST, MPC) "
        "to retrieve celestial object data, catalogs, literature records, solar system ephemerides, and download raw files of any extension to disk."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "database": {
                "type": "string",
                "description": (
                    "Select the database matching the query type:\n"
                    "- 'SIMBAD': General object properties and coordinates.\n"
                    "- 'NED': Extragalactic targets and redshift/photometry data.\n"
                    "- 'VIZIER': General catalog and historical table searches.\n"
                    "- 'ATNF': Radio pulsars strictly.\n"
                    "- 'ADS': Academic literature and historical papers.\n"
                    "- 'MAST': Search and download ALL available data products (FITS, text, logs, previews) for an object directly to local disk.\n"
                    "- 'MPC': Minor Planet Center queries for solar system bodies (asteroids/comets ephemerides & observations)."
                ),
                "enum": ["SIMBAD", "NED", "VIZIER", "ATNF", "ADS", "MAST", "MPC"]
            },
            "query_type": {
                "type": "string",
                "description": "Type of query: 'object_name' or 'region_search' (by coordinates).",
                "enum": ["object_name", "region_search"]
            },
            "target": {
                "type": "string",
                "description": (
                    "The object identifier or search terms (e.g., 'Cas A', 'Ceres', 'Halley', 'M31')."
                )
            },
            "radius_arcmin": {
                "type": "number",
                "description": "Search radius in arcminutes for region searches. Defaults to 2.0."
            },
            "vizier_catalog": {
                "type": "string",
                "description": "Specific VizieR catalog ID. Optional."
            },
            "download_files": {
                "type": "boolean",
                "description": "Set to true when database is 'MAST' to automatically download ALL data product files (any extension) to local disk."
            }
        },
        "required": ["database", "query_type", "target"]
    }
}


# ==========================================
# 2. UNIVERSAL TOOL EXECUTION CLASS WITH UNIVERSAL FILE DUMPER
# ==========================================
class AstroQueryTool:
    def __init__(self, ads_token: str = None):
        self.simbad = Simbad()
        self.simbad.add_votable_fields('V', 'rvz_radvel', 'sp')
        self.simbad.TIMEOUT = 20
        Ned.TIMEOUT = 20

        token = ads_token or os.environ.get("ADS_DEV_KEY")
        if token:
            ads.config.token = token

    def execute(self, arguments: dict) -> dict:
        db = arguments.get("database")
        q_type = arguments.get("query_type")
        target = arguments.get("target")
        radius = arguments.get("radius_arcmin", 2.0)
        catalog = arguments.get("vizier_catalog")
        download_files = arguments.get("download_files", False)

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
            elif db == "MAST":
                return self._query_mast_and_download_all(target, download_files)
            elif db == "MPC":
                return self._query_mpc(target)
            else:
                return {"error": f"Unknown database: {db}"}
        except Exception as e:
            return {"error": str(e)}

    def _query_simbad(self, q_type: str, target: str, radius: float) -> dict:
        result = self.simbad.query_object(target) if q_type == "object_name" else self.simbad.query_region(SkyCoord.from_name(target), radius=radius * u.arcmin)
        return self._table_to_dict(result, max_rows=10)

    def _query_ned(self, q_type: str, target: str, radius: float) -> dict:
        result = Ned.query_object(target) if q_type == "object_name" else Ned.query_region(SkyCoord.from_name(target), radius=radius * u.arcmin)
        return self._table_to_dict(result, max_rows=10)

    def _query_vizier(self, q_type: str, target: str, radius: float, catalog: str = None) -> dict:
        vizier = Vizier(columns=['*'])
        vizier.row_limit = 15
        if catalog:
            vizier.catalog = catalog
            result_list = vizier.query_object(target) if q_type == "object_name" else vizier.query_region(SkyCoord.from_name(target), radius=radius * u.arcmin)
        else:
            result_list = vizier.query_object(target)

        if not result_list:
            return {"status": f"No historical records found for target '{target}'"}

        all_tables_data = {}
        for key in list(result_list.keys())[:5]:
            if "META" not in key and "ReadMe" not in key:
                table_df = self._table_to_dict(result_list[key], max_rows=10)
                if "data" in table_df:
                    all_tables_data[key] = table_df["data"]

        return {"target": target, "catalogs_matched": list(all_tables_data.keys()), "data": all_tables_data}

    def _query_atnf(self, target: str) -> dict:
        if target.lower() in ["cassiopeia a", "cas a", "crab nebula", "m1"]:
            return {"error": f"ATNF is restricted to pulsars. '{target}' is not a pulsar."}
        query = psrqpy.QueryATNF(params=['PSRJ', 'P0', 'DM', 'AGE'], psrs=[target])
        df = query.pandas
        if df.empty:
            return {"status": f"No pulsar found for {target}"}
        return {"data": df.to_dict(orient='records')}

    def _query_ads(self, target: str) -> dict:
        if not ads.config.token:
            return {"error": "NASA ADS API token missing. Set ADS_DEV_KEY in environment."}
        papers = list(ads.SearchQuery(q=target, sort="citation_count desc", fl=["title", "author", "bibcode", "citation_count", "year"]))
        results = [{"title": p.title[0] if p.title else "N/A", "year": getattr(p, 'year', "N/A"), "bibcode": p.bibcode, "citations": p.citation_count or 0} for p in papers[:8]]
        return {"data": results} if results else {"status": f"No papers found for {target}"}

    def _query_mast_and_download_all(self, target: str, download_files: bool) -> dict:
        """
        Searches MAST archive for observations matching the target coordinates 
        and downloads ALL associated data product files (regardless of extension) onto the local filesystem.
        """
        try:
            coord = SkyCoord.from_name(target)
        except Exception:
            return {"error": f"Could not resolve target '{target}' coordinates for MAST."}

        obs_table = Observations.query_criteria(coordinates=coord, radius=0.05 * u.deg)
        if len(obs_table) == 0:
            return {"status": f"No MAST observations found for {target}."}

        # Get all data products without extension filtering
        data_products = Observations.get_product_list(obs_table[:5])
        
        downloaded_files = []
        if download_files and len(data_products) > 0:
            os.makedirs("./fits_downloads", exist_ok=True)
            # Downloads every file product type returned in the product list table
            manifest = Observations.download_products(data_products[:15], download_dir="./fits_downloads")
            downloaded_files = list(manifest['Local Path']) if 'Local Path' in manifest.colnames else []

        return {
            "target": target,
            "observations_found": len(obs_table),
            "total_products_available": len(data_products),
            "downloaded_to_local_disk": downloaded_files,
            "note": "All retrieved files successfully saved locally in './fits_downloads/'" if downloaded_files else "Metadata retrieved. Set download_files=True to download all matched files to disk."
        }

    def _query_mpc(self, target: str) -> dict:
        try:
            ephem_table = MPC.get_ephemeris(target, number=5)
            return self._table_to_dict(ephem_table, max_rows=10)
        except Exception as e:
            try:
                obs_table = MPC.get_observations(target)
                return self._table_to_dict(obs_table, max_rows=10)
            except Exception as inner_e:
                return {"error": f"MPC query failed for target '{target}': {str(e)} | Obs fallback error: {str(inner_e)}"}

    def _table_to_dict(self, astropy_table, max_rows: int = 10) -> dict:
        if astropy_table is None or len(astropy_table) == 0:
            return {"status": "No data found"}
        
        df = astropy_table.to_pandas()
        
        for col in df.columns:
            if pd.api.types.is_integer_dtype(df[col]) or pd.api.types.is_float_dtype(df[col]):
                df[col] = df[col].astype(object)
            elif pd.api.types.is_datetime64_any_dtype(df[col]) or 'time' in col.lower():
                df[col] = df[col].astype(str)

        for col in df.select_dtypes(include=['object', 'str']).columns:
            df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else str(x))

        df = df.fillna("N/A")
        return {"data": df.head(max_rows).to_dict(orient="records")}


# ==========================================
# 3. AGENTIC STREAMING LOOP
# ==========================================
def main():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Set your ANTHROPIC_API_KEY environment variable to execute queries.")
        return

    client = anthropic.Anthropic(api_key=anthropic_key)
    tool_handler = AstroQueryTool()

    user_message = ""
    print(f"User: {user_message}\n" + "="*50)

    messages = [{"role": "user", "content": user_message}]

    for turn in range(6):
        with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=128000,
            tools=[astro_tool_schema],
            messages=messages
        ) as stream:
            
            for text in stream.text_stream:
                print(text, end="", flush=True)

            response = stream.get_final_message()

            if response.stop_reason == "end_turn":
                print("\n\n[Task Complete]")
                break

            elif response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for content_block in response.content:
                    if content_block.type == "tool_use":
                        tool_name = content_block.name
                        tool_args = content_block.input
                        tool_use_id = content_block.id

                        print(f"\n\n[*] [Turn {turn+1}] Executing database -> {tool_args.get('database')} | Target: {tool_args.get('target')} | Download Files: {tool_args.get('download_files', False)}")
                        
                        result = tool_handler.execute(tool_args)
                        print("Tool Output JSON Preview:")
                        print(json.dumps(result, indent=2, default=str)[:400] + "...\n")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(result, default=str)
                        })

                messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    main()
