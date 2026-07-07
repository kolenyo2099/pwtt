"""Building-footprint lookup and scoring helpers.

This service adapts the Lebanon demo logic into a generic flow. It discovers
the Microsoft Buildings country assets available in Earth Engine, resolves the
AOI to matching countries, and computes per-building damage scores once per run.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from difflib import get_close_matches
from typing import Any

import ee

from ..repositories.settings_repository import get_setting, save_setting
from ..settings import settings


COUNTRIES_DATASET = "USDOS/LSIB_SIMPLE/2017"
ASSET_CACHE_KEY = "ms_buildings_asset_index"
REGIONAL_ASSETS = {"Africa", "Asia", "Europe", "North_America", "Oceania", "South_America"}
MAX_BUILDINGS_PER_RUN = 20_000
MIN_BUILDING_AREA_M2 = 200
TOP_DAMAGED_LIMIT = 8
HOTSPOT_BUFFER_METERS = 30
HOTSPOT_THRESHOLD_FLOOR = 2.8
OUTLINE_FOOTPRINT_LIMIT = 12000

NAME_ALIASES = {
    "bahamas": "The_Bahamas",
    "bosnia and herzegovina": "Bosnia_and_Herzegovina",
    "brunei": "Brunei",
    "cape verde": "Cabo_Verde",
    "cote divoire": "Cote_dIvoire",
    "congo kinshasa": "Democratic_Republic_of_the_Congo",
    "congo brazzaville": "Republic_of_the_Congo",
    "czechia": "Czech_Republic",
    "eswatini": "Swaziland",
    "gambia": "The_Gambia",
    "ivory coast": "Cote_dIvoire",
    "north macedonia": "Macedonia",
    "russia": "Russia",
    "south korea": "South_Korea",
    "syria": "Syria",
    "taiwan": "Taiwan",
    "tanzania": "Tanzania",
    "turkiye": "Turkey",
    "united states": "United_States",
    "united states of america": "United_States",
    "venezuela": "Venezuela",
    "viet nam": "Vietnam",
}


def _normalize_name(value: str) -> str:
    """Normalize names so country labels and asset ids can be matched safely."""

    lowered = value.strip().lower().replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _load_asset_index() -> dict[str, dict[str, str]]:
    """Return a cached map from normalized names to Earth Engine asset ids."""

    cached = get_setting(ASSET_CACHE_KEY)
    if cached and cached.get("value") and cached.get("updated_at"):
        updated_at = datetime.fromisoformat(str(cached["updated_at"]).replace(" ", "T"))
        if datetime.utcnow() - updated_at < timedelta(hours=settings.ms_buildings_cache_hours):
            return json.loads(str(cached["value"]))

    assets = ee.data.listAssets(settings.ms_buildings_parent).get("assets", [])
    countries: dict[str, str] = {}
    regions: dict[str, str] = {}

    for asset in assets:
        asset_id = asset["id"]
        name = asset_id.rsplit("/", 1)[-1]
        target = regions if name in REGIONAL_ASSETS else countries
        target[_normalize_name(name.replace("_", " "))] = asset_id

    payload = {"countries": countries, "regions": regions}
    save_setting(ASSET_CACHE_KEY, json.dumps(payload))
    return payload


def _resolve_asset_ids(aoi: ee.Geometry) -> list[str]:
    """Resolve the AOI to one or more matching Microsoft Buildings asset ids."""

    index = _load_asset_index()
    features = (
        ee.FeatureCollection(COUNTRIES_DATASET)
        .filterBounds(aoi)
        .aggregate_array("country_na")
        .getInfo()
        or []
    )
    regions = (
        ee.FeatureCollection(COUNTRIES_DATASET)
        .filterBounds(aoi)
        .aggregate_array("wld_rgn")
        .getInfo()
        or []
    )

    asset_ids: list[str] = []
    available_country_keys = list(index["countries"].keys())

    for name in features:
        normalized = _normalize_name(str(name))
        alias_name = NAME_ALIASES.get(normalized)
        if alias_name:
            normalized = _normalize_name(alias_name.replace("_", " "))

        asset_id = index["countries"].get(normalized)
        if not asset_id:
            close = get_close_matches(normalized, available_country_keys, n=1, cutoff=0.9)
            asset_id = index["countries"].get(close[0]) if close else None
        if asset_id and asset_id not in asset_ids:
            asset_ids.append(asset_id)

    if asset_ids:
        return asset_ids

    for region_name in regions:
        region_id = index["regions"].get(_normalize_name(str(region_name)))
        if region_id and region_id not in asset_ids:
            asset_ids.append(region_id)

    return asset_ids


def _merge_assets(asset_ids: list[str]) -> ee.FeatureCollection:
    """Merge multiple country assets into one feature collection for the AOI."""

    collection = ee.FeatureCollection([])
    for asset_id in asset_ids:
        tagged = ee.FeatureCollection(asset_id).map(
            lambda feature: feature.set(
                "source_asset_id",
                asset_id,
            ).set(
                "source_provider",
                "Microsoft Buildings",
            )
        )
        collection = collection.merge(tagged)
    return collection


def _mean_score_to_float(value: Any) -> float:
    """Convert Earth Engine output values into stable floats for display and sorting."""

    if value is None:
        return 0.0
    return round(float(value), 2)


def _damage_category(score: float, threshold: float) -> str:
    """Translate a building score into a plain-language severity label."""

    if score >= threshold + 1.5:
        return "Severe"
    if score >= threshold + 0.75:
        return "High"
    if score >= threshold:
        return "Elevated"
    return "Below threshold"


def _geometry_center(geometry: dict[str, Any]) -> tuple[float, float]:
    """Approximate the feature center so exports can deep-link to the location."""

    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon" and coordinates:
        ring = coordinates[0]
    elif geometry.get("type") == "MultiPolygon" and coordinates:
        ring = coordinates[0][0]
    else:
        return (0.0, 0.0)

    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return (round((min(lons) + max(lons)) / 2, 6), round((min(lats) + max(lats)) / 2, 6))


def _google_maps_url(longitude: float, latitude: float) -> str:
    """Build a web URL that opens the feature in Google Maps."""

    return f"https://www.google.com/maps?q={latitude},{longitude}"


def _fetch_features_paginated(
    feature_collection: ee.FeatureCollection,
) -> dict[str, Any]:
    """Retrieve a FeatureCollection using server-side pagination.

    ee.data.computeFeatures() uses an internal pageToken loop and is not
    subject to the interactive 5 000-element cap that getInfo() enforces.
    It is the right tool whenever the caller has already reduced the collection
    to a manageable set via server-side filters (see score_buildings).

    Falls back to tiled retrieval only if computeFeatures raises — which can
    happen for very large or complex feature sets that exceed interactive
    compute-time limits even with pagination.
    """

    try:
        result = ee.data.computeFeatures({
            "expression": feature_collection,
            "fileFormat": "GEOJSON",
        })
        return {"type": "FeatureCollection", "features": (result or {}).get("features", [])}
    except Exception:
        pass  # fall through to tiled retrieval

    # Tile fallback: split the bounding box into 0.25° chunks and merge results.
    # Only reached for very dense urban areas where even the filtered set is large.
    _TILE_DEG = 0.25
    bounds_info = feature_collection.geometry().bounds(1).getInfo()
    ring = bounds_info["coordinates"][0]
    min_lon = min(c[0] for c in ring)
    max_lon = max(c[0] for c in ring)
    min_lat = min(c[1] for c in ring)
    max_lat = max(c[1] for c in ring)

    all_features: list[dict[str, Any]] = []
    seen: set[str] = set()

    lon = min_lon
    while lon < max_lon:
        lat = min_lat
        while lat < max_lat:
            tile_geom = ee.Geometry.Rectangle([
                lon, lat,
                min(lon + _TILE_DEG, max_lon),
                min(lat + _TILE_DEG, max_lat),
            ])
            tile_fc = feature_collection.filterBounds(tile_geom)
            tile_features: list[dict[str, Any]] = []
            try:
                result = ee.data.computeFeatures({"expression": tile_fc, "fileFormat": "GEOJSON"})
                tile_features = (result or {}).get("features", [])
            except Exception:
                try:
                    result = tile_fc.limit(4999).getInfo()
                    tile_features = (result or {}).get("features", [])
                except Exception:
                    pass
            for feature in tile_features:
                fid = str(feature.get("id") or feature.get("properties", {}).get("system:index") or "")
                if fid and fid in seen:
                    continue
                if fid:
                    seen.add(fid)
                all_features.append(feature)
            lat += _TILE_DEG
        lon += _TILE_DEG

    return {"type": "FeatureCollection", "features": all_features}


def _candidate_footprints(footprints: ee.FeatureCollection, image: ee.Image, aoi: ee.Geometry, threshold: float) -> ee.FeatureCollection:
    """Limit expensive building scoring to hotspot areas instead of the whole AOI.

    This keeps the query practical on large AOIs and avoids hammering the
    provider while still returning the buildings most likely to matter.
    """

    # Screen slightly below the user's threshold (buildings average several
    # pixels, so a qualifying mean can come from a mix above and below it).
    # The floor keeps huge low-threshold queries affordable, but must never
    # rise above the user's own threshold — otherwise lowering the threshold
    # below 2.8 would silently exclude the very buildings the user asked for.
    screening_level = min(threshold, max(threshold - 0.4, HOTSPOT_THRESHOLD_FLOOR))
    hotspot_mask = (
        image.select("T_statistic")
        .gte(screening_level)
        .focalMax(HOTSPOT_BUFFER_METERS, "square", "meters")
        .selfMask()
    )
    hotspot_vectors = hotspot_mask.reduceToVectors(
        geometry=aoi,
        scale=20,
        geometryType="polygon",
        reducer=ee.Reducer.countEvery(),
        bestEffort=True,
        maxPixels=1e10,
    )
    hotspot_geometry = ee.FeatureCollection(hotspot_vectors).geometry()
    return footprints.filterBounds(hotspot_geometry)


def score_buildings(aoi: ee.Geometry, image: ee.Image, threshold: float) -> dict[str, Any]:
    """Compute per-building damage scores using Microsoft Buildings footprints.

    The result is returned as a GeoJSON-like feature collection plus a compact
    summary that the UI can show without re-running the Earth Engine job.
    """

    asset_ids = _resolve_asset_ids(aoi)
    if not asset_ids:
        return {
            "feature_collection": {"type": "FeatureCollection", "features": []},
            "summary": {
                "available": False,
                "reason": "No Microsoft Buildings coverage was found for this AOI.",
                "total_buildings": 0,
                "damaged_buildings": 0,
                "damaged_share_pct": 0.0,
                "min_building_area_m2": MIN_BUILDING_AREA_M2,
            },
        }

    footprints = (
        _merge_assets(asset_ids)
        .filterBounds(aoi)
        .map(
            lambda feature: feature.set("area_m2", feature.geometry().area(10)).set(
                "geometry_type", feature.geometry().type()
            )
        )
        .filter(ee.Filter.gt("area_m2", MIN_BUILDING_AREA_M2))
        .filter(ee.Filter.eq("geometry_type", "Polygon"))
    )

    total_buildings = int(ee.Number(footprints.size()).getInfo())
    candidate_footprints = _candidate_footprints(footprints, image, aoi, threshold)
    candidate_count = int(ee.Number(candidate_footprints.size()).getInfo())

    if candidate_count == 0:
        return {
            "feature_collection": {"type": "FeatureCollection", "features": []},
            "summary": {
                "available": True,
                "reason": "No building hotspots were found above the screening threshold.",
                "asset_ids": asset_ids,
                "total_buildings": total_buildings,
                "damaged_buildings": 0,
                "damaged_share_pct": 0.0,
                "top_damaged_buildings": [],
                "min_building_area_m2": MIN_BUILDING_AREA_M2,
            },
        }

    scored = image.select("T_statistic").reduceRegions(
        collection=candidate_footprints,
        reducer=ee.Reducer.mean(),
        scale=10,
        tileScale=8,
    )
    # Tag each building with its damage probability and damaged flag.  Both
    # operations are lazy — nothing is computed on GEE servers yet.
    enriched = scored.map(
        lambda feature: feature.set(
            "damage_probability", ee.Number(feature.get("mean")),
            "damaged", ee.Number(ee.Algorithms.If(ee.Number(feature.get("mean")).gte(threshold), 1, 0)),
        )
    )

    # Server-side filter: keep only buildings at or above the threshold.
    # This is still lazy — GEE adds it to the computation graph and evaluates
    # it during materialisation, so only the features we actually need cross
    # the wire.  For a typical threshold this reduces the result set by 80–95 %
    # compared to fetching all candidates, which is the primary reason the
    # 5 000-element cap was being hit.
    damaged_fc = enriched.filter(ee.Filter.gte("mean", threshold))

    feature_collection = _fetch_features_paginated(damaged_fc)
    top_damaged: list[dict[str, Any]] = []

    # Every feature in the result is already confirmed damaged (mean >= threshold),
    # so the loop only needs to enrich properties — no damaged-flag check required.
    for index, feature in enumerate(feature_collection.get("features", []), start=1):
        properties = feature.setdefault("properties", {})
        score = _mean_score_to_float(properties.get("damage_probability", properties.get("mean")))
        longitude, latitude = _geometry_center(feature.get("geometry", {}))
        category = _damage_category(score, threshold)

        # The score is the mean T statistic inside the footprint — a detection
        # confidence, not a calibrated probability or a severity measure.
        # "mean_t" is the honest name; "damage_probability" is kept so older
        # caches, exports, and downstream consumers keep working.
        properties["mean_t"] = score
        properties["damage_probability"] = score
        properties["damaged"] = 1
        properties["category"] = category
        properties["longitude"] = longitude
        properties["latitude"] = latitude
        properties["google_maps_url"] = _google_maps_url(longitude, latitude)
        properties["label"] = f"Building {index}"

        top_damaged.append(
            {
                "label": properties["label"],
                "category": category,
                "damage_probability": score,
                "google_maps_url": properties["google_maps_url"],
            }
        )

    top_damaged.sort(key=lambda item: item["damage_probability"], reverse=True)
    damaged_buildings = len(feature_collection.get("features", []))
    damaged_share = round((damaged_buildings / total_buildings) * 100, 2) if total_buildings else 0.0

    return {
        "feature_collection": feature_collection,
        "summary": {
            "available": True,
            "reason": None,
            "asset_ids": asset_ids,
            "total_buildings": total_buildings,
            "damaged_buildings": damaged_buildings,
            "damaged_share_pct": damaged_share,
            "top_damaged_buildings": top_damaged[:TOP_DAMAGED_LIMIT],
            "min_building_area_m2": MIN_BUILDING_AREA_M2,
        },
    }


def enrich_cached_buildings(
    feature_collection: dict[str, Any],
    threshold: float,
    asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Upgrade older cached building outputs with newer derived properties.

    This keeps old runs exportable even when they were created before newer KML
    and UI fields such as categories and Google Maps links existed.
    """

    enriched = {
        "type": feature_collection.get("type", "FeatureCollection"),
        "features": [],
    }
    default_asset_id = asset_ids[0] if asset_ids and len(asset_ids) == 1 else None
    top_damaged: list[dict[str, Any]] = []

    for index, feature in enumerate(feature_collection.get("features", []), start=1):
        copied_feature = {
            "type": feature.get("type", "Feature"),
            "geometry": feature.get("geometry"),
            "properties": dict(feature.get("properties", {})),
        }
        properties = copied_feature["properties"]
        score = _mean_score_to_float(properties.get("damage_probability", properties.get("mean")))
        longitude, latitude = _geometry_center(copied_feature.get("geometry", {}) or {})
        category = _damage_category(score, threshold)

        properties["mean_t"] = score
        properties["damage_probability"] = score
        properties["category"] = category
        properties["longitude"] = longitude
        properties["latitude"] = latitude
        properties["google_maps_url"] = properties.get("google_maps_url") or _google_maps_url(longitude, latitude)
        properties["label"] = properties.get("label") or f"Building {index}"
        properties["source_provider"] = properties.get("source_provider") or "Microsoft Buildings"
        if default_asset_id and not properties.get("source_asset_id"):
            properties["source_asset_id"] = default_asset_id

        if properties.get("damaged"):
            top_damaged.append(
                {
                    "label": properties["label"],
                    "category": category,
                    "damage_probability": score,
                    "google_maps_url": properties["google_maps_url"],
                }
            )

        enriched["features"].append(copied_feature)

    top_damaged.sort(key=lambda item: item["damage_probability"], reverse=True)
    return {
        "feature_collection": enriched,
        "summary_patch": {
            "damaged_buildings": sum(
                1 for feature in enriched["features"] if feature.get("properties", {}).get("damaged")
            ),
            "top_damaged_buildings": top_damaged[:TOP_DAMAGED_LIMIT],
        },
    }


def building_outline_images(feature_collection: dict[str, Any]) -> tuple[ee.Image, ee.Image]:
    """Create outline layers for all buildings and the damaged subset."""

    collection = ee.FeatureCollection(feature_collection)
    damaged = collection.filter(ee.Filter.eq("damaged", 1))
    outlines = ee.Image().byte().paint(collection, 1, 3)
    damaged_outlines = ee.Image().byte().paint(damaged, 1, 4)
    return outlines, damaged_outlines
