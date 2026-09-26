"""Focused ports of Astromancer's framework-free HR-diagram helpers.

Input objects deliberately remain mapping-shaped: Astromancer's TypeScript
algorithms operated on JSON service objects, so preserving that loose boundary
is more faithful than inventing a session model in Kepler.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

# PORTED: git-history:algorithms/hrdiagram/fsr/cmd-fsr.util.ts::getCmdData
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


# PORTED: git-history:algorithms/hrdiagram/fsr/fsr-histogram.util.ts::getDefaultBin
def get_default_bin(plot_data: Sequence[float]) -> int | float:
    if not plot_data:
        return 10
    n = len(plot_data)
    iqr = plot_data[math.floor(n * 0.75)] - plot_data[math.floor(n * 0.25)]
    numerator = plot_data[-1] - plot_data[0]
    denominator = 2 * iqr * n ** (-1 / 3)
    if denominator == 0:
        if numerator == 0:
            return math.nan
        return math.copysign(math.inf, numerator)
    return math.ceil(numerator / denominator)


# PORTED: git-history:algorithms/hrdiagram/fsr/fsr-histogram.util.ts::getHistogramExtremes
def get_histogram_extremes(data: Sequence[float], selected_data: Sequence[float]) -> dict[str, float]:
    if not selected_data:
        return {"min": -999, "max": 999}
    sigma = 0.9876
    return {
        "min": data[math.ceil(len(data) * (0.5 - sigma / 2))],
        "max": data[math.floor(len(data) * (0.5 + sigma / 2))],
    }


# PORTED: git-history:algorithms/hrdiagram/cluster.util.ts::getExtinction
def _legacy_extinction(filter_name: str, reddening: float, rv: float = 3.1) -> float:
    x = _FILTER_WAVELENGTH[filter_name] ** -1
    y = x - 1.82
    a = b = 0.0
    if 0.3 < x < 1.1:
        a = 0.574 * x ** 1.61
        b = -0.527 * x ** 1.61
    elif 1.1 < x < 3.3:
        a = 1 + 0.17699 * y - 0.50447 * y ** 2 - 0.02427 * y ** 3 + 0.72085 * y ** 4 + 0.01979 * y ** 5 - 0.7753 * y ** 6 + 0.32999 * y ** 7
        b = 1.41338 * y + 2.28305 * y ** 2 + 1.07233 * y ** 3 - 5.38434 * y ** 4 - 0.62251 * y ** 5 + 5.3026 * y ** 6 - 2.09002 * y ** 7
    return 3.1 * reddening * (a + b / rv)


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::computePlotDelta
def compute_plot_delta(filters: Mapping[str, str], params: Mapping[str, float]) -> dict[str, float]:
    blue = _legacy_extinction(filters["blue"], params["reddening"])
    red = _legacy_extinction(filters["red"], params["reddening"])
    lum = _legacy_extinction(filters["lum"], params["reddening"])
    return {"x": red - blue, "y": -lum - 5 * math.log10(params["distance"] * 1000) + 5}


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::getPlotData
def get_plot_data(raw_data: Sequence[Mapping[str, Any]], plot_type: str, filters: Mapping[str, str], params: Mapping[str, float], max_mag_error: float) -> tuple[list[list[float]], list[str]]:
    kept = [point for point in raw_data if point["max_mag_error"] < max_mag_error]
    if plot_type == "CM":
        return [[point["x"], point["y"]] for point in kept], [point["id"] for point in kept]
    if plot_type == "HR":
        delta = compute_plot_delta(filters, params)
        return [[point["x"] + delta["x"], point["y"] + delta["y"]] for point in kept], [point["id"] for point in kept]
    return [], []


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::applyIsochroneTransform
def apply_isochrone_transform(response: Mapping[str, Any], plot_type: str, filters: Mapping[str, str], params: Mapping[str, float]) -> list[list[float | None]]:
    data = [list(point) for point in response["data"]]
    if plot_type == "CM":
        delta = compute_plot_delta(filters, params)
        data = [[point[0] - delta["x"], point[1] - delta["y"]] for point in data]
    i_skip = response["iSkip"]
    if i_skip > 0 and len(response["data"]) > i_skip:
        data = [*data[:i_skip - 1], [None, None], *data[i_skip:]]
    return data


# PORTED: git-history:algorithms/hrdiagram/result/mwsc-distributions.ts::*Distribution
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


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.util.ts::sourceSerialization
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


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.util.ts::updateClusterFieldSources
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


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::isValidFilterSelection
def is_valid_filter_selection(filters: Mapping[str, str]) -> bool:
    return filters["blue"] != filters["red"]


# PORTED: git-history:algorithms/hrdiagram/result/galaxy-projection.ts::galaxyFaceOnOffset
def galaxy_face_on_offset(galactic_longitude: float, galactic_latitude: float, distance: float) -> dict[str, float]:
    longitude = math.radians(galactic_longitude)
    in_plane = distance * math.cos(math.radians(galactic_latitude)) * 32
    return {"delta_x": in_plane * math.sin(longitude), "delta_y": -in_plane * math.cos(longitude)}


# PORTED: git-history:algorithms/hrdiagram/result/galaxy-projection.ts::galaxyEdgeOnOffset
def galaxy_edge_on_offset(galactic_longitude: float, galactic_latitude: float, distance: float) -> dict[str, float]:
    longitude = math.radians(galactic_longitude)
    latitude = math.radians(galactic_latitude)
    in_plane = distance * math.cos(latitude)
    return {"delta_x": -in_plane * math.cos(longitude) * 32, "delta_y": max(-500, min(500, distance * math.sin(latitude) * 16))}


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::generateRawData
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


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::getDataRange
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


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.util.ts::appendFSRResults
def append_fsr_results(sources: list[dict[str, Any]], fsr: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered_fsr = sorted(fsr, key=lambda entry: float(entry["id"]))
    i = j = 0
    while i < len(sources) and j < len(ordered_fsr):
        source_id = sources[i]["id"]
        result_id = ordered_fsr[j]["id"]
        if source_id == result_id:
            sources[i]["fsr"] = {
                "pm_ra": ordered_fsr[j]["pm_ra"],
                "pm_dec": ordered_fsr[j]["pm_dec"],
                "distance": ordered_fsr[j]["distance"],
            }
            i += 1
            j += 1
        elif source_id < result_id:
            i += 1
        else:
            j += 1
    return sources


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.util.ts::getStarCountsByFilter
def get_star_counts_by_filter(
    cluster_sources: Sequence[Mapping[str, Any]],
    field_sources: Sequence[Mapping[str, Any]],
    filters: Sequence[str],
    fsr: Mapping[str, Any],
    star_count: Mapping[str, int],
    total_stars_count: int,
) -> dict[str, int]:
    del fsr  # Present in the legacy signature but unused by its implementation.
    cluster_stars = sum(
        any(photometry["filter"] in filters for photometry in source["photometries"])
        for source in cluster_sources
    )
    field_stars = sum(
        any(photometry["filter"] in filters for photometry in source["photometries"])
        for source in field_sources
    )
    if cluster_stars == 0 and field_stars == 0:
        return {"cluster_stars": 0, "field_stars": 0, "unused_stars": total_stars_count}
    field_stars += star_count["field_stars"]
    return {
        "cluster_stars": cluster_stars,
        "field_stars": field_stars,
        "unused_stars": max(0, total_stars_count - cluster_stars - field_stars),
    }


# PORTED: git-history:algorithms/hrdiagram/shared/angle.util.ts::rad
def rad(degree: float) -> float:
    return degree / 180 * math.pi


# PORTED: git-history:algorithms/hrdiagram/shared/angle.util.ts::deg
def deg(radians: float) -> float:
    return radians / math.pi * 180


# PORTED: git-history:algorithms/hrdiagram/shared/angle.util.ts::d2HMS
def d2_hms(degrees: float) -> list[float]:
    hours = math.floor(degrees / 15)
    minutes = math.floor((degrees - hours * 15) * 4)
    seconds = ((degrees - hours * 15) * 4 - minutes) * 60
    return [hours, minutes, seconds]


# PORTED: git-history:algorithms/hrdiagram/shared/angle.util.ts::d2DMS
def d2_dms(degrees: float) -> list[float]:
    degrees = abs(degrees)
    whole_degrees = math.floor(degrees)
    minutes = math.floor((degrees - whole_degrees) * 60)
    seconds = ((degrees - whole_degrees) * 60 - minutes) * 60
    return [whole_degrees, minutes, seconds]


# PORTED: git-history:algorithms/hrdiagram/cluster.util.ts::haversine
def haversine(dec1: float, dec2: float, ra1: float, ra2: float) -> float:
    dec1_rad, dec2_rad, ra1_rad, ra2_rad = map(rad, (dec1, dec2, ra1, ra2))
    theta = 2 * math.asin(
        (math.sin((dec1_rad - dec2_rad) / 2) ** 2
         + math.cos(dec1_rad) * math.cos(dec2_rad) * math.sin((ra1_rad - ra2_rad) / 2) ** 2) ** 0.5
    )
    return deg(theta)


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::getHalfLightRadius
def get_half_light_radius(sources: Sequence[Mapping[str, Any]], center_ra: float, center_dec: float) -> float:
    distances = sorted(
        haversine(center_dec, source["astrometry"]["dec"], center_ra, source["astrometry"]["ra"])
        for source in sources
    )
    return distances[math.floor(len(distances) / 2)]


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::getPhysicalRadius
def get_physical_radius(distance: float, angular_radius: float) -> float:
    return 2 * distance * math.tan(rad(angular_radius) / 2) * 3261.56


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::getPmra
def get_pmra(pmras: Sequence[float]) -> float:
    return pmras[math.floor(len(pmras) / 2)]


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::getPmdec
def get_pmdec(pmdecs: Sequence[float]) -> float:
    return pmdecs[math.floor(len(pmdecs) / 2)]


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::getVelocityDispersion
def get_velocity_dispersion(sources: Sequence[Mapping[str, Any]], pmra: float, pmdec: float) -> float:
    dispersion = sorted(
        math.sqrt((source["fsr"]["pm_ra"] - pmra) ** 2 + (source["fsr"]["pm_dec"] - pmdec) ** 2)
        for source in sources
        if source["fsr"] is not None and source["fsr"]["pm_ra"] is not None and source["fsr"]["pm_dec"] is not None
    )
    percentile = 0.683
    selected = dispersion[
        math.floor(len(dispersion) * (1 - percentile) / 2):
        math.ceil(len(dispersion) * (1 - percentile / 2))
    ]
    return sum(selected) / len(selected)


# PORTED: git-history:algorithms/hrdiagram/result/cluster-summary.ts::logAgeToMyr
def log_age_to_myr(log_age: float) -> float:
    return 10 ** log_age / 1_000_000


_FILTER_FRAMING = {
    "U": {"red": 11.72, "faint": 11.72, "blue": -4.49, "bright": -10.57},
    "B": {"red": 10.72, "faint": 10.72, "blue": -3.34, "bright": -10.6},
    "V": {"red": 9.38, "faint": 9.38, "blue": -3.04, "bright": -10.67},
    "R": {"red": 8.45, "faint": 8.45, "blue": -2.92, "bright": -10.88},
    "I": {"red": 7.69, "faint": 7.69, "blue": -2.75, "bright": -11.25},
    "uprime": {"red": 12.55, "faint": 12.55, "blue": -3.78, "bright": -9.66},
    "gprime": {"red": 10.13, "faint": 10.13, "blue": -3.36, "bright": -10.74},
    "rprime": {"red": 8.8, "faint": 8.8, "blue": -2.84, "bright": -10.68},
    "iprime": {"red": 8.26, "faint": 8.26, "blue": -2.47, "bright": -10.79},
    "zprime": {"red": 7.93, "faint": 7.93, "blue": -2.13, "bright": -10.87},
    "J": {"red": 6.67, "faint": 6.67, "blue": -2.42, "bright": -11.82},
    "H": {"red": 6.1, "faint": 6.1, "blue": -2.28, "bright": -12.18},
    "K": {"red": 5.92, "faint": 5.92, "blue": -2.19, "bright": -12.24},
    "W1": {"red": 5.7, "faint": 5.7, "blue": -2.11, "bright": -12.3},
    "W2": {"red": 5.58, "faint": 5.58, "blue": -2.07, "bright": -12.33},
    "W3": {"red": 5.52, "faint": 5.52, "blue": -3.31, "bright": -12.31},
    "W4": {"red": 5.19, "faint": 5.19, "blue": -3.13, "bright": -12.62},
    "BP": {"red": 9.57, "faint": 9.57, "blue": -3.3, "bright": -10.67},
    "G": {"red": 8.73, "faint": 8.73, "blue": -3.13, "bright": -10.76},
    "RP": {"red": 7.83, "faint": 7.83, "blue": -2.82, "bright": -11.18},
}


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/isochrone-plot.util.ts::getStandardViewRange
def get_standard_view_range(filters: Mapping[str, str]) -> dict[str, dict[str, float]]:
    blue, red, lum = (_FILTER_FRAMING[filters[name]] for name in ("blue", "red", "lum"))
    color_red = blue["red"] - red["red"]
    color_blue = blue["blue"] - red["blue"]
    min_x = color_blue - (color_red - color_blue) / 8
    max_x = color_red + (color_red - color_blue) / 8
    return {
        "x": {"min": min(min_x, max_x), "max": max(min_x, max_x)},
        "y": {
            "min": lum["bright"] + (lum["bright"] - red["faint"]) / 8,
            "max": lum["faint"] - (lum["bright"] - lum["faint"]) / 8,
        },
    }


# PORTED: git-history:algorithms/hrdiagram/isochrone-matching/cluster-isochrone.service.ts::resetDistance
def reset_distance(fsr_params: Mapping[str, Any]) -> float:
    distance = fsr_params["distance"]
    if distance:
        return float(f"{(distance['max'] + distance['min']) / 2:.2f}")
    return 0.1


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::equatorial2Galactic
def equatorial_to_galactic(ra: float, dec: float) -> dict[str, float]:
    ra_ngp = rad(192.8595)
    dec_ngp = rad(27.1284)
    l_ngp = rad(122.93314)
    ra_rad = rad(ra)
    dec_rad = rad(dec)
    b = math.asin(
        math.sin(dec_ngp) * math.sin(dec_rad)
        + math.cos(dec_ngp) * math.cos(dec_rad) * math.cos(ra_rad - ra_ngp)
    )
    temp = math.cos(dec_rad) * math.sin(ra_rad - ra_ngp) / (
        math.sin(dec_rad) * math.cos(dec_ngp)
        - math.cos(dec_rad) * math.sin(dec_ngp) * math.cos(ra_rad - ra_ngp)
    )
    temp = math.atan(temp)
    temp = temp + math.pi if temp < 0 else temp
    longitude = l_ngp - temp
    longitude = longitude + 2 * math.pi if longitude < 0 else longitude
    return {"l": deg(longitude), "b": deg(b)}


# PORTED: git-history:algorithms/hrdiagram/result/result.utils.ts::getMass
def get_mass(velocity_dispersion: float, distance: float, physical_radius: float) -> float:
    sigma = 3.086 * 10 ** 13 * distance * rad(velocity_dispersion) / (
        3600 * 365.25 * 24 * 3600
    )
    radius_pc = physical_radius * 0.3066
    return 10 * sigma * sigma * radius_pc / 0.004302


# PORTED: git-history:algorithms/hrdiagram/result/cluster-summary.ts::computeClusterSummary
def compute_cluster_summary(
    sources: Sequence[Mapping[str, Any]],
    cluster_ra: float,
    cluster_dec: float,
    pmras: Sequence[float],
    pmdecs: Sequence[float],
    plot_params: Mapping[str, float],
    isochrone_params: Mapping[str, float],
) -> dict[str, float | int]:
    angular_radius = get_half_light_radius(sources, cluster_ra, cluster_dec)
    galactic = equatorial_to_galactic(cluster_ra, cluster_dec)
    distance = plot_params["distance"]
    physical_radius = get_physical_radius(distance, angular_radius)
    pmra = get_pmra(pmras)
    # The TypeScript summary calls getPmra for both arrays. Both functions are
    # identical; retain that call shape rather than silently correcting it.
    pmdec = get_pmra(pmdecs)
    velocity_dispersion = get_velocity_dispersion(sources, pmra, pmdec)
    return {
        "numberOfStars": len(sources),
        "angularRadius": angular_radius,
        "ra": cluster_ra,
        "dec": cluster_dec,
        "l": galactic["l"],
        "b": galactic["b"],
        "physicalRadius": physical_radius,
        "pmra": pmra,
        "pmdec": pmdec,
        "velocityDispersion": velocity_dispersion,
        "mass": get_mass(velocity_dispersion, distance, physical_radius),
        "distance": distance,
        "age": isochrone_params["age"],
        "metallicity": isochrone_params["metallicity"],
        "reddening": plot_params["reddening"],
    }


_FILTER_WAVELENGTH = {
    "U": 0.364, "B": 0.442, "V": 0.54, "R": 0.647, "I": 0.7865,
    "gprime": 0.475, "rprime": 0.622, "iprime": 0.763, "zprime": 0.905,
    "J": 1.25, "H": 1.65, "K": 2.15,
    "W1": 3.4, "W2": 4.6, "W3": 12.0, "W4": 22.0,
    "BP": 0.532, "G": 0.673, "RP": 0.797,
}


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.ts::setSources/generateFilterList
def normalize_sources(sources: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    for source in sources:
        fsr = source.get("fsr")
        if fsr is None or any(fsr.get(key) is None for key in ("distance", "pm_ra", "pm_dec")):
            continue
        photometries = [
            dict(photometry)
            for photometry in source["photometries"]
            if photometry["filter"] in _FILTER_WAVELENGTH
            and math.isfinite(photometry["mag"])
            and math.isfinite(photometry["mag_error"])
        ]
        photometries.sort(key=lambda photometry: _FILTER_WAVELENGTH[photometry["filter"]])
        normalized.append({**source, "photometries": photometries})
    filters = sorted(
        {photometry["filter"] for source in normalized for photometry in source["photometries"]},
        key=_FILTER_WAVELENGTH.__getitem__,
    )
    return normalized, filters


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.ts::getDistance/getPmra/getPmdec
def get_fsr_values(sources: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    return sorted(
        float(f"{source['fsr'][field]:.2f}")
        for source in sources
        if source.get("fsr") is not None and source["fsr"].get(field) is not None
    )


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.ts::getRa/getDec
def get_astrometry_values(sources: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    return sorted(
        float(f"{source['astrometry'][field]:.2f}")
        for source in sources
        if source.get("astrometry") is not None and source["astrometry"].get(field) is not None
    )


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.ts::getClusterRa/getClusterDec
def get_cluster_coordinate(sources: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = get_astrometry_values(sources, field)
    return None if not values else values[math.floor(len(values) / 2)]


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.ts::get2DpmChartData
def get_2d_pm_chart_data(
    cluster_sources: Sequence[Mapping[str, Any]] | None,
    field_sources: Sequence[Mapping[str, Any]] | None,
) -> dict[str, list[list[float]]]:
    if cluster_sources is None or field_sources is None:
        return {"cluster": [], "field": []}

    def values(sources: Sequence[Mapping[str, Any]]) -> list[list[float]]:
        return [
            [source["fsr"]["pm_ra"], source["fsr"]["pm_dec"]]
            for source in sources
            if source.get("fsr") is not None
            and source["fsr"].get("pm_ra") is not None
            and source["fsr"].get("pm_dec") is not None
        ]

    return {"cluster": values(cluster_sources), "field": values(field_sources)}


# PORTED: git-history:algorithms/hrdiagram/photometry/cluster-data.service.ts::getInterfaceStarCounts
def get_interface_star_counts(
    cluster_sources: Sequence[Mapping[str, Any]],
    field_sources: Sequence[Mapping[str, Any]],
    star_counts: Mapping[str, Mapping[str, int]],
    cluster: Mapping[str, int],
    user_partition: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    if user_partition is not None:
        result["user"] = {
            "field_stars": len(user_partition["not_fsr"]),
            "cluster_stars": len(user_partition["fsr"]),
            "unused_stars": 0,
        }
    catalogs = {
        "GAIA": (["G", "BP", "RP"], "num_total_stars"),
        "APASS": (["gprime", "rprime", "iprime", "zprime"], "num_APASS_stars"),
        "TWO_MASS": (["J", "H", "K"], "num_TWO_MASS_stars"),
        "WISE": (["W1", "W2", "W3", "W4"], "num_WISE_stars"),
    }
    for catalog, (filters, total_key) in catalogs.items():
        result[catalog] = get_star_counts_by_filter(
            cluster_sources, field_sources, filters, {}, star_counts[catalog], cluster[total_key]
        )
    return result
