"""Focused ports of Astromancer's framework-free HR-diagram helpers.

Input objects deliberately remain mapping-shaped: Astromancer's TypeScript
algorithms operated on JSON service objects, so preserving that loose boundary
is more faithful than inventing a session model in Kepler.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from algorithms.hrdiagram_py import hrfit


# PORTED: algorithms/hrdiagram/fsr/cmd-fsr.util.ts::getCmdData
def get_cmd_data(sources: Sequence[Mapping[str, Any]], filters: Sequence[str]) -> dict[str, Any]:
    pairs: list[tuple[str, str]] = []
    for pair in (("BP", "RP"), ("W1", "W2"), ("gprime", "iprime"), ("J", "H")):
        if pair[0] in filters and pair[1] in filters:
            pairs.append(pair)
    if not pairs:
        pairs.append((filters[0], filters[1]))
    results: list[list[list[float]]] = [[] for _ in pairs]
    for source in sources:
        photometries = source.get("photometries") or []
        available = {p["filter"]: p["mag"] for p in photometries}
        for index, (blue, red) in enumerate(pairs):
            if blue in available and red in available:
                results[index].append([available[blue] - available[red], available[red]])
    winner = max(range(len(results)), key=lambda index: len(results[index]))
    return {"data": results[winner], "blue_filter": pairs[winner][0], "red_filter": pairs[winner][1]}


# PORTED: algorithms/hrdiagram/fsr/fsr-histogram.util.ts::getDefaultBin
def get_default_bin(plot_data: Sequence[float]) -> int:
    if not plot_data:
        return 10
    n = len(plot_data)
    iqr = plot_data[math.floor(n * 0.75)] - plot_data[math.floor(n * 0.25)]
    return math.ceil((plot_data[-1] - plot_data[0]) / (2 * iqr * n ** (-1 / 3)))


# PORTED: algorithms/hrdiagram/fsr/fsr-histogram.util.ts::getHistogramExtremes
def get_histogram_extremes(data: Sequence[float], selected_data: Sequence[float]) -> dict[str, float]:
    if not selected_data:
        return {"min": -999, "max": 999}
    sigma = 0.9876
    return {
        "min": data[math.ceil(len(data) * (0.5 - sigma / 2))],
        "max": data[math.floor(len(data) * (0.5 + sigma / 2))],
    }


# PORTED: algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::computePlotDelta
def compute_plot_delta(filters: Mapping[str, str], params: Mapping[str, float]) -> dict[str, float]:
    blue = hrfit.get_extinction(filters["blue"], params["reddening"])
    red = hrfit.get_extinction(filters["red"], params["reddening"])
    lum = hrfit.get_extinction(filters["lum"], params["reddening"])
    return {"x": red - blue, "y": -lum - 5 * math.log10(params["distance"] * 1000) + 5}


# PORTED: algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::getPlotData
def get_plot_data(raw_data: Sequence[Mapping[str, Any]], plot_type: str, filters: Mapping[str, str], params: Mapping[str, float], max_mag_error: float) -> tuple[list[list[float]], list[str]]:
    kept = [point for point in raw_data if point["max_mag_error"] < max_mag_error]
    if plot_type == "CM":
        return [[point["x"], point["y"]] for point in kept], [point["id"] for point in kept]
    if plot_type == "HR":
        delta = compute_plot_delta(filters, params)
        return [[point["x"] + delta["x"], point["y"] + delta["y"]] for point in kept], [point["id"] for point in kept]
    return [], []


# PORTED: algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::applyIsochroneTransform
def apply_isochrone_transform(response: Mapping[str, Any], plot_type: str, filters: Mapping[str, str], params: Mapping[str, float]) -> list[list[float | None]]:
    data = [list(point) for point in response["data"]]
    if plot_type == "CM":
        delta = compute_plot_delta(filters, params)
        data = [[point[0] - delta["x"], point[1] - delta["y"]] for point in data]
    i_skip = response["iSkip"]
    if i_skip > 0 and len(response["data"]) > i_skip:
        data = [*data[:i_skip - 1], [None, None], *data[i_skip:]]
    return data


# PORTED: algorithms/hrdiagram/result/mwsc-distributions.ts::*Distribution
def get_mwsc_age_distribution(clusters: Sequence[Mapping[str, Any]]) -> list[float]:
    return sorted(10 ** cluster["age"] / 1_000_000 for cluster in clusters if cluster.get("age") is not None and 0 < 10 ** cluster["age"] / 1_000_000 < 13.8)


def get_mwsc_distance_distribution(clusters: Sequence[Mapping[str, Any]]) -> list[float]:
    return sorted(cluster["distance"] / 1000 for cluster in clusters if cluster.get("distance", 0) > 0)


def get_mwsc_metallicity_distribution(clusters: Sequence[Mapping[str, Any]]) -> list[float]:
    return sorted(cluster["metallicity"] for cluster in clusters if cluster.get("metallicity") is not None and -2.3 < cluster["metallicity"] < 0.8)


def get_mwsc_reddening_distribution(clusters: Sequence[Mapping[str, Any]]) -> list[float]:
    return sorted(cluster["e_bv"] for cluster in clusters if cluster.get("e_bv") is not None and 0 <= cluster["e_bv"] <= 1)


def get_mwsc_star_count_distribution(clusters: Sequence[Mapping[str, Any]]) -> list[float]:
    counts = sorted(cluster["num_cluster_stars"] for cluster in clusters if cluster.get("num_cluster_stars", 0) > 0)
    return counts[math.floor(0.0015 * len(counts)):math.ceil(0.99985 * len(counts))]


# PORTED: algorithms/hrdiagram/photometry/cluster-data.service.util.ts::sourceSerialization
def source_serialization(sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: list[dict[str, Any]] = []
    filters: list[str] = []
    for entry in sources:
        photometries = []
        for photometry in entry["photometries"]:
            if photometry["filter"] not in filters:
                filters.append(photometry["filter"])
            photometries.append({"filter": photometry["filter"], "mag": photometry["mag"], "mag_error": photometry["mag_err"]})
        result.append({"id": entry["id"], "astrometry": {"ra": entry["astrometry"]["ra"], "dec": entry["astrometry"]["dec"]}, "fsr": {"pm_ra": entry["fsr"]["pm_ra"], "pm_dec": entry["fsr"]["pm_dec"], "distance": entry["fsr"]["distance"]}, "photometries": photometries})
    return {"sources": result, "filters": filters}


# PORTED: algorithms/hrdiagram/photometry/cluster-data.service.util.ts::updateClusterFieldSources
def update_cluster_field_sources(sources: Sequence[Mapping[str, Any]] | None, fsr: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    if sources is None:
        return {"fsr": [], "not_fsr": []}
    pm_global = fsr.get("pm_ra") is None or fsr.get("pm_dec") is None
    if not pm_global:
        a = (fsr["pm_ra"]["max"] - fsr["pm_ra"]["min"]) / 2
        b = (fsr["pm_dec"]["max"] - fsr["pm_dec"]["min"]) / 2
        center_ra = (fsr["pm_ra"]["max"] + fsr["pm_ra"]["min"]) / 2
        center_dec = (fsr["pm_dec"]["max"] + fsr["pm_dec"]["min"]) / 2
    selected: list[Mapping[str, Any]] = []
    rejected: list[Mapping[str, Any]] = []
    for source in sources:
        values = source.get("fsr")
        distance_ok = fsr.get("distance") is None or (values and values.get("distance") and fsr["distance"]["min"] <= values["distance"] <= fsr["distance"]["max"])
        pm_ok = pm_global
        if not pm_ok and values and values.get("pm_ra") and values.get("pm_dec"):
            inner = 1 - ((values["pm_ra"] - center_ra) / a) ** 2
            dec_diff = b * math.sqrt(inner) if inner >= 0 else math.nan
            pm_ok = center_dec - dec_diff <= values["pm_dec"] <= center_dec + dec_diff
        elif pm_global and (not values or values.get("pm_ra") is None or values.get("pm_dec") is None):
            pm_ok = False
        (selected if distance_ok and pm_ok else rejected).append(source)
    return {"fsr": selected, "not_fsr": rejected}


# PORTED: algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::isValidFilterSelection
def is_valid_filter_selection(filters: Mapping[str, str]) -> bool:
    return filters["blue"] != filters["red"]


# PORTED: algorithms/hrdiagram/result/galaxy-projection.ts::galaxyFaceOnOffset
def galaxy_face_on_offset(galactic_longitude: float, galactic_latitude: float, distance: float) -> dict[str, float]:
    longitude = math.radians(galactic_longitude)
    in_plane = distance * math.cos(math.radians(galactic_latitude)) * 32
    return {"delta_x": in_plane * math.sin(longitude), "delta_y": -in_plane * math.cos(longitude)}


# PORTED: algorithms/hrdiagram/result/galaxy-projection.ts::galaxyEdgeOnOffset
def galaxy_edge_on_offset(galactic_longitude: float, galactic_latitude: float, distance: float) -> dict[str, float]:
    longitude = math.radians(galactic_longitude)
    latitude = math.radians(galactic_latitude)
    in_plane = distance * math.cos(latitude)
    return {"delta_x": -in_plane * math.cos(longitude) * 32, "delta_y": max(-500, min(500, distance * math.sin(latitude) * 16))}


# PORTED: algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::generateRawData
def generate_raw_data(sources: Sequence[Mapping[str, Any]], filters: Mapping[str, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in sources:
        magnitudes: dict[str, float] = {}
        max_error = 0.0
        for photometry in source["photometries"]:
            if photometry["filter"] in (filters["blue"], filters["red"], filters["lum"]):
                magnitudes[photometry["filter"]] = photometry["mag"]
                if photometry["mag_error"] > max_error:
                    max_error = photometry["mag_error"]
        if all(name in magnitudes for name in (filters["blue"], filters["red"], filters["lum"])):
            result.append({"id": source["id"], "x": magnitudes[filters["blue"]] - magnitudes[filters["red"]], "y": magnitudes[filters["lum"]], "max_mag_error": max_error})
    return result


# PORTED: algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::getDataRange
def get_data_range(data: Sequence[Sequence[float]]) -> dict[str, dict[str, float]]:
    if not data:
        return {"x": {"min": 0, "max": 0}, "y": {"min": 0, "max": 0}}
    min_x = max_x = data[0][0]
    min_y = max_y = data[0][1]
    for point in data:
        min_x, max_x = min(min_x, point[0]), max(max_x, point[0])
        min_y, max_y = min(min_y, point[1]), max(max_y, point[1])
    x_delta, y_delta = (max_x - min_x) * 0.1, (max_y - min_y) * 0.1
    if x_delta > 0 and y_delta > 0:
        min_x, max_x, min_y, max_y = min_x - x_delta, max_x + x_delta, min_y - y_delta, max_y + y_delta
    return {"x": {"min": min_x, "max": max_x}, "y": {"min": min_y, "max": max_y}}
