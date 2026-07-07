"""PWTT-specific business logic.

This module wraps the upstream `pwtt` package in app-friendly functions that
return summaries, tile layers, and exportable vectors for the wizard UI.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import ee
import pwtt

from .buildings_service import building_outline_images, enrich_cached_buildings, score_buildings
from .cache_service import get_run_cache_file, read_cached_json, write_cached_bytes, write_cached_json
from .earth_engine_service import ensure_earth_engine, geometry_from_geojson, make_thumbnail_url, make_tile_url
from .png_service import PWTT_VIS, RGB_VIS, render_triptych_and_panels, render_triptych_png
from ..repositories.runs_repository import touch_run_heartbeat, update_run_summary
from ..settings import settings


# UC Berkeley severity ramp — California Gold, Wellman Tile, Rose Dark.
OVERLAY_PALETTE = ["#fdb515", "#d9661f", "#770747"]
PREVIEW_WIDTH = 1200
STALE_BUILDING_REASON_MARKERS = (
    "Draw a smaller AOI",
    "building-level scoring",
)


def _mask_sentinel2_clouds(image: ee.Image) -> ee.Image:
    """Remove obvious cloud pixels from Sentinel-2 so the preview panels stay readable."""

    qa_band = image.select("QA60")
    cloud_mask = qa_band.bitwiseAnd(1 << 10).eq(0)
    cirrus_mask = qa_band.bitwiseAnd(1 << 11).eq(0)
    return image.updateMask(cloud_mask.And(cirrus_mask)).divide(10000)


def _safe_sentinel2_composite(aoi: ee.Geometry, start_date: str, end_date: str) -> ee.Image:
    """Build an RGB preview image, or a masked fallback when imagery is unavailable."""

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        .map(_mask_sentinel2_clouds)
    )
    fallback = ee.Image.constant([0, 0, 0]).rename(["B4", "B3", "B2"]).updateMask(0)
    composite = ee.Image(ee.Algorithms.If(collection.size().gt(0), collection.median(), fallback))
    return composite.clip(aoi)


def _compute_summary(image: ee.Image, aoi: ee.Geometry) -> dict[str, Any]:
    """Turn raw Earth Engine outputs into a few numbers a non-technical user can read quickly."""

    damaged_area = (
        image.select("damage")
        .selfMask()
        .multiply(ee.Image.pixelArea())
        .rename("damaged_area")
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=20,
            maxPixels=1e10,
            tileScale=4,
        )
        .get("damaged_area")
    )
    total_area = aoi.area(1)
    mean_t = image.select("T_statistic").reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi,
        scale=20,
        maxPixels=1e10,
        tileScale=4,
    ).get("T_statistic")
    max_t = image.select("T_statistic").reduceRegion(
        reducer=ee.Reducer.max(),
        geometry=aoi,
        scale=20,
        maxPixels=1e10,
        tileScale=4,
    ).get("T_statistic")
    damaged_pixels = image.select("damage").reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi,
        scale=20,
        maxPixels=1e10,
        tileScale=4,
    ).get("damage")

    # The T statistic is masked to built-up pixels (Dynamic World built > 0.1)
    # inside the PWTT package, so its mask doubles as a built-up-area layer.
    # Damage share is reported against this built-up area rather than the whole
    # AOI: dividing by total AOI area would dilute the share to near zero for
    # any AOI that includes farmland or water around the town of interest.
    built_area = (
        image.select("T_statistic")
        .mask()
        .multiply(ee.Image.pixelArea())
        .rename("built_area")
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=20,
            maxPixels=1e10,
            tileScale=4,
        )
        .get("built_area")
    )

    summary = ee.Dictionary(
        {
            "damaged_area_ha": ee.Number(damaged_area).divide(10000),
            "built_area_ha": ee.Number(built_area).divide(10000),
            "damage_share_pct": ee.Number(damaged_area).divide(ee.Number(built_area).max(1)).multiply(100),
            "aoi_share_pct": ee.Number(damaged_area).divide(total_area).multiply(100),
            "mean_t_score": ee.Number(mean_t),
            "max_t_score": ee.Number(max_t),
            "damaged_pixel_estimate": ee.Number(damaged_pixels).round(),
        }
    )
    result = summary.getInfo()

    # Rounded values are easier to scan in the wizard and still precise enough for triage.
    return {
        "damaged_area_ha": round(float(result["damaged_area_ha"]), 2),
        "built_area_ha": round(float(result["built_area_ha"]), 2),
        "damage_share_pct": round(float(result["damage_share_pct"]), 2),
        "aoi_share_pct": round(float(result["aoi_share_pct"]), 2),
        "mean_t_score": round(float(result["mean_t_score"]), 2),
        "max_t_score": round(float(result["max_t_score"]), 2),
        "damaged_pixel_estimate": int(result["damaged_pixel_estimate"]),
    }


def _apply_threshold(image: ee.Image, threshold: float) -> ee.Image:
    """Rebuild the damage mask from the T statistic using the user's chosen threshold.

    The installed PWTT package hardcodes its own damage threshold internally.
    Recomputing the mask here keeps the UI threshold control meaningful without
    requiring changes inside the third-party package.
    """

    damage_mask = image.select("T_statistic").gt(threshold).rename("damage").toFloat()
    return image.addBands(damage_mask, overwrite=True)


def _preview_window_dates(parameters: dict[str, Any]) -> tuple[str, str]:
    """Return slightly wider windows for the preview mosaics."""

    war_start = datetime.fromisoformat(parameters["war_start"])
    inference_start = datetime.fromisoformat(parameters["inference_start"])
    pre_start = (war_start - timedelta(days=45)).date().isoformat()
    post_end = (inference_start + timedelta(days=45)).date().isoformat()
    return pre_start, post_end


def check_sentinel1_coverage(aoi: ee.Geometry, parameters: dict[str, Any]) -> dict[str, Any]:
    """Check the Sentinel-1 inputs PWTT needs and report how many scenes exist.

    The upstream library fails with a low-level Earth Engine band-selection
    error when the post window has no usable Sentinel-1 scenes. This guard
    turns that into a clear message the UI can show directly. The returned
    scene counts feed the preflight endpoint and the run summary so users can
    judge the statistical power of their chosen windows: the t-test runs per
    orbit, so the per-orbit minimums are the numbers that matter.
    """

    war_start = datetime.fromisoformat(parameters["war_start"]).date().isoformat()
    inference_start = datetime.fromisoformat(parameters["inference_start"]).date().isoformat()
    pre_start = (
        datetime.fromisoformat(parameters["war_start"]) - timedelta(days=round(float(parameters["pre_interval"]) * 30))
    ).date().isoformat()
    post_end = (
        datetime.fromisoformat(parameters["inference_start"]) + timedelta(days=round(float(parameters["post_interval"]) * 30))
    ).date().isoformat()

    base_collection = (
        ee.ImageCollection("COPERNICUS/S1_GRD_FLOAT")
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filterBounds(aoi)
    )
    pre_collection = base_collection.filterDate(
        ee.Date(parameters["war_start"]).advance(ee.Number(parameters["pre_interval"]).multiply(-1), "month"),
        parameters["war_start"],
    )
    post_collection = base_collection.filterDate(
        parameters["inference_start"],
        ee.Date(parameters["inference_start"]).advance(parameters["post_interval"], "month"),
    )
    pre_histogram = pre_collection.aggregate_histogram("relativeOrbitNumber_start").getInfo() or {}
    post_histogram = post_collection.aggregate_histogram("relativeOrbitNumber_start").getInfo() or {}
    pre_orbits = set(pre_histogram)
    post_orbits = set(post_histogram)

    if not post_orbits:
        raise ValueError(
            f"No Sentinel-1 scenes were found in the post-event window from {inference_start} to {post_end}. "
            "Choose a later inference start date or increase post-war months."
        )

    if not pre_orbits:
        raise ValueError(
            f"No Sentinel-1 scenes were found in the baseline window before {war_start}. "
            "Choose a later conflict start date or reduce pre-war months."
        )

    shared_orbits = pre_orbits & post_orbits
    if not shared_orbits:
        raise ValueError(
            f"No overlapping Sentinel-1 orbit coverage was found between the baseline window ending {war_start} "
            f"and the post-event window from {inference_start} to {post_end}. "
            "Choose a later inference start date or increase post-war months."
        )

    return {
        "pre_scenes": int(sum(pre_histogram[orbit] for orbit in shared_orbits)),
        "post_scenes": int(sum(post_histogram[orbit] for orbit in shared_orbits)),
        "orbit_count": len(shared_orbits),
        "min_pre_scenes_per_orbit": int(min(pre_histogram[orbit] for orbit in shared_orbits)),
        "min_post_scenes_per_orbit": int(min(post_histogram[orbit] for orbit in shared_orbits)),
        "pre_window": [pre_start, war_start],
        "post_window": [inference_start, post_end],
    }


def _build_preview_images(aoi: ee.Geometry, parameters: dict[str, Any]) -> tuple[ee.Image, ee.Image]:
    """Return the pre-event and post-event preview images used in the UI and PNG export."""

    pre_start, post_end = _preview_window_dates(parameters)
    pre_image = _safe_sentinel2_composite(aoi, pre_start, parameters["war_start"])
    post_image = _safe_sentinel2_composite(aoi, parameters["inference_start"], post_end)
    return pre_image, post_image


def _build_layers(
    aoi: ee.Geometry,
    parameters: dict[str, Any],
    buildings_geojson: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    """Create fresh tile URLs for the result panels."""

    image = run_pwtt_image(aoi, parameters)
    pre_image, post_image = _build_preview_images(aoi, parameters)
    buildings_overlay_url = None
    region = ee.Feature(aoi.bounds(1)).geometry().getInfo()
    pwtt_preview_image = post_image.visualize(**RGB_VIS).blend(image.select("T_statistic").visualize(**PWTT_VIS))

    if buildings_geojson and buildings_geojson.get("features"):
        outlines, damaged_outlines = building_outline_images(buildings_geojson)
        pwtt_preview_image = (
            pwtt_preview_image
            .blend(outlines.visualize(palette=["ffffff"], opacity=0.95))
            .blend(damaged_outlines.visualize(palette=["d9661f"], opacity=1.0))
        )
        buildings_overlay_url = make_tile_url(
            outlines.visualize(palette=["ffffff"], opacity=0.95).blend(
                damaged_outlines.visualize(palette=["d9661f"], opacity=1.0)
            ),
            {},
        )

    return {
        "pre_event": make_tile_url(pre_image, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35, "gamma": 1.2}),
        "post_event": make_tile_url(post_image, {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35, "gamma": 1.2}),
        "pwtt_overlay": make_tile_url(
            image.select("T_statistic"),
            {
                "min": max(parameters["threshold"] - 0.8, 1.5),
                "max": max(parameters["threshold"] + 1.7, 5.0),
                "palette": OVERLAY_PALETTE,
                "opacity": 0.62,
            },
        ),
        "buildings_overlay": buildings_overlay_url,
        "pre_event_preview": make_thumbnail_url(pre_image.visualize(**RGB_VIS), region, PREVIEW_WIDTH),
        "post_event_preview": make_thumbnail_url(post_image.visualize(**RGB_VIS), region, PREVIEW_WIDTH),
        "pwtt_preview": make_thumbnail_url(pwtt_preview_image, region, PREVIEW_WIDTH),
    }


def _cached_buildings_need_recompute(summary: dict[str, Any], buildings_geojson: dict[str, Any] | None) -> bool:
    """Detect older building caches that were produced before the newer export logic.

    Older runs can keep an empty or incomplete cache forever unless we refresh
    them here. This check stays intentionally simple and favors correctness over
    saving a small amount of recomputation.
    """

    building_summary = (summary or {}).get("buildings") or {}
    reason = str(building_summary.get("reason") or "")
    features = (buildings_geojson or {}).get("features", [])

    if any(marker in reason for marker in STALE_BUILDING_REASON_MARKERS):
        return True
    if not building_summary:
        return True
    if features:
        return False

    if building_summary.get("damaged_buildings"):
        return True
    if building_summary.get("available") and not reason and building_summary.get("total_buildings", 0) > 0:
        return True

    return False


def _cached_buildings_need_enrichment(summary: dict[str, Any], buildings_geojson: dict[str, Any] | None) -> bool:
    """Detect older cached features that only need local property enrichment."""

    building_summary = (summary or {}).get("buildings") or {}
    features = (buildings_geojson or {}).get("features", [])
    if not features:
        return False

    properties = features[0].get("properties", {})
    if any(key not in properties for key in ("category", "google_maps_url", "label", "source_provider")):
        return True
    if not building_summary.get("top_damaged_buildings") and building_summary.get("damaged_buildings", 0) > 0:
        return True

    return False


def _load_or_refresh_buildings(run_id: int, aoi: ee.Geometry, image: ee.Image, parameters: dict[str, Any], summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return building outputs for a run, refreshing stale caches when needed."""

    buildings_geojson = read_cached_json(run_id, "buildings.geojson")
    building_outputs: dict[str, Any] | None = None

    if _cached_buildings_need_recompute(summary, buildings_geojson):
        building_outputs = score_buildings(aoi, image, float(parameters["threshold"]))
        buildings_geojson = building_outputs["feature_collection"]
        write_cached_json(run_id, "buildings.geojson", buildings_geojson)
    elif _cached_buildings_need_enrichment(summary, buildings_geojson):
        enriched = enrich_cached_buildings(
            buildings_geojson or {"type": "FeatureCollection", "features": []},
            float(parameters["threshold"]),
            ((summary or {}).get("buildings") or {}).get("asset_ids"),
        )
        buildings_geojson = enriched["feature_collection"]
        current_building_summary = (summary or {}).get("buildings") or {}
        total_buildings = int(current_building_summary.get("total_buildings", len(buildings_geojson.get("features", []))))
        damaged_buildings = int(enriched["summary_patch"]["damaged_buildings"])
        building_outputs = {
            "feature_collection": buildings_geojson,
            "summary": {
                **current_building_summary,
                "damaged_buildings": damaged_buildings,
                "damaged_share_pct": round((damaged_buildings / total_buildings) * 100, 2) if total_buildings else 0.0,
                "top_damaged_buildings": enriched["summary_patch"]["top_damaged_buildings"],
            },
        }
        write_cached_json(run_id, "buildings.geojson", buildings_geojson)

    if building_outputs is None:
        building_outputs = {
            "feature_collection": buildings_geojson or {"type": "FeatureCollection", "features": []},
            "summary": (summary or {}).get("buildings")
            or {
                "available": False,
                "reason": "Building screening has not been generated for this run yet.",
                "total_buildings": 0,
                "damaged_buildings": 0,
                "damaged_share_pct": 0.0,
                "top_damaged_buildings": [],
            },
        }

    return building_outputs, buildings_geojson or {"type": "FeatureCollection", "features": []}


def run_pwtt_image(aoi: ee.Geometry, parameters: dict[str, Any], validate: bool = True) -> ee.Image:
    """Create the core PWTT image from saved run parameters."""

    if validate:
        check_sentinel1_coverage(aoi, parameters)
    base_image = pwtt.detect_damage(
        aoi=aoi,
        war_start=parameters["war_start"],
        inference_start=parameters["inference_start"],
        pre_interval=parameters["pre_interval"],
        post_interval=parameters["post_interval"],
        viz=False,
    )
    return _apply_threshold(base_image, float(parameters["threshold"]))


def _is_gee_timeout(exc: BaseException) -> bool:
    """Return True when an exception is a GEE read timeout that's worth retrying."""
    msg = str(exc).lower()
    return "read timed out" in msg or "readtimeouterror" in msg or "timed out" in msg


def execute_run(run_id: int, parameters: dict[str, Any]) -> dict[str, Any]:
    """Run the heavy PWTT summary calculation for one queued job.

    touch_run_heartbeat is called after each major Earth Engine step so the
    stall detector in the scheduler can distinguish a slow-but-progressing run
    from one that is genuinely blocked on a hanging GEE request.
    """

    max_attempts = 2
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            ensure_earth_engine()
            aoi = geometry_from_geojson(parameters["aoi_geojson"])

            # Step 1: validate Sentinel-1 coverage and build the PWTT damage image.
            touch_run_heartbeat(run_id, "Checking radar coverage (step 1 of 4)")
            coverage = check_sentinel1_coverage(aoi, parameters)
            image = run_pwtt_image(aoi, parameters, validate=False)

            # Step 2: compute aggregate damage statistics across the AOI.
            touch_run_heartbeat(run_id, "Computing damage statistics (step 2 of 4)")
            summary = _compute_summary(image, aoi)
            summary["coverage"] = coverage

            # Step 3: score individual buildings within hotspot areas.
            touch_run_heartbeat(run_id, "Scoring buildings (step 3 of 4)")
            building_outputs = score_buildings(aoi, image, float(parameters["threshold"]))
            buildings_geojson = building_outputs["feature_collection"]
            if buildings_geojson.get("features"):
                write_cached_json(run_id, "buildings.geojson", buildings_geojson)
            summary["buildings"] = building_outputs["summary"]

            # Step 4: render and cache the three preview panel images.
            touch_run_heartbeat(run_id, "Rendering preview images (step 4 of 4)")
            pre_image, post_image = _build_preview_images(aoi, parameters)
            triptych_png, preview_panels = render_triptych_and_panels(
                aoi=aoi,
                pre_image=pre_image,
                post_image=post_image,
                pwtt_image=image,
                buildings_geojson=buildings_geojson,
            )
            write_cached_bytes(run_id, "triptych.png", triptych_png)
            for panel_name, panel_bytes in preview_panels.items():
                write_cached_bytes(run_id, f"preview_{panel_name}.png", panel_bytes)
            touch_run_heartbeat(run_id)

            return summary

        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _is_gee_timeout(exc) and attempt < max_attempts:
                touch_run_heartbeat(run_id, "Earth Engine timed out — retrying")
                time.sleep(15)
                continue
            raise

    raise last_exc  # type: ignore[misc]


_PREVIEW_CACHE_FILES = [
    ("pre_event_preview", "preview_pre.png", "pre"),
    ("post_event_preview", "preview_post.png", "post"),
    ("pwtt_preview", "preview_pwtt.png", "pwtt"),
]


def _cached_preview_layers(run_id: int) -> dict[str, str | None] | None:
    """Return layer URLs backed entirely by cached PNGs, or None if incomplete."""

    if not all(get_run_cache_file(run_id, cache_file).exists() for _, cache_file, _ in _PREVIEW_CACHE_FILES):
        return None
    return {
        layer_key: f"{settings.backend_url}/api/runs/{run_id}/preview/{panel}"
        for layer_key, _, panel in _PREVIEW_CACHE_FILES
    }


def _cached_buildings_are_current(summary: dict[str, Any], buildings_geojson: dict[str, Any] | None) -> bool:
    """True when the cached building outputs need no Earth Engine refresh."""

    return not _cached_buildings_need_recompute(summary, buildings_geojson) and not _cached_buildings_need_enrichment(
        summary, buildings_geojson
    )


def build_run_detail(run: dict[str, Any]) -> dict[str, Any]:
    """Attach preview image URLs to a stored run so the results page can render.

    Completed runs normally have everything cached locally (summary, building
    GeoJSON, preview PNGs), in which case this returns immediately without
    touching Earth Engine. The slow path below only exists for runs created by
    older app versions whose caches are missing or incomplete.
    """

    run_id = int(run["id"])
    summary = run.get("summary") or {}
    cached_layers = _cached_preview_layers(run_id)
    if summary and cached_layers and _cached_buildings_are_current(summary, read_cached_json(run_id, "buildings.geojson")):
        return {**run, "layers": cached_layers}

    ensure_earth_engine()
    aoi = geometry_from_geojson(run["aoi_geojson"])
    image = run_pwtt_image(aoi, run["parameters"])
    building_outputs, buildings_geojson = _load_or_refresh_buildings(
        run_id,
        aoi,
        image,
        run["parameters"],
        summary,
    )
    refreshed_summary = {
        **summary,
        "buildings": building_outputs["summary"],
    }
    if refreshed_summary != summary:
        update_run_summary(run_id, refreshed_summary)
        summary = refreshed_summary

    layers = _build_layers(aoi, run["parameters"], buildings_geojson)

    # Replace GEE thumbnail URLs with stable cached images when available.
    # GEE thumbnail URLs expire after a few hours; local files never do.
    for layer_key, cache_file, panel in _PREVIEW_CACHE_FILES:
        if get_run_cache_file(run_id, cache_file).exists():
            layers[layer_key] = f"{settings.backend_url}/api/runs/{run_id}/preview/{panel}"

    return {
        **run,
        "summary": summary,
        "layers": layers,
    }


def export_damage_kml(run: dict[str, Any]) -> dict[str, Any]:
    """Return KML-ready building polygons, straight from cache when possible."""

    run_id = int(run["id"])
    summary = run.get("summary") or {}
    cached_geojson = read_cached_json(run_id, "buildings.geojson")
    if summary and _cached_buildings_are_current(summary, cached_geojson):
        return cached_geojson or {"type": "FeatureCollection", "features": []}

    ensure_earth_engine()
    aoi = geometry_from_geojson(run["aoi_geojson"])
    image = run_pwtt_image(aoi, run["parameters"])
    building_outputs, buildings_geojson = _load_or_refresh_buildings(
        int(run["id"]),
        aoi,
        image,
        run["parameters"],
        run.get("summary") or {},
    )
    refreshed_summary = {
        **(run.get("summary") or {}),
        "buildings": building_outputs["summary"],
    }
    update_run_summary(int(run["id"]), refreshed_summary)
    return buildings_geojson


def export_triptych_png(run: dict[str, Any]) -> bytes:
    """Return the cached triptych PNG, generating it only when missing."""

    cached_path = get_run_cache_file(int(run["id"]), "triptych.png")
    if cached_path.exists():
        return cached_path.read_bytes()

    ensure_earth_engine()
    aoi = geometry_from_geojson(run["aoi_geojson"])
    image = run_pwtt_image(aoi, run["parameters"])
    pre_image, post_image = _build_preview_images(aoi, run["parameters"])
    _, buildings_geojson = _load_or_refresh_buildings(
        int(run["id"]),
        aoi,
        image,
        run["parameters"],
        run.get("summary") or {},
    )
    png_bytes = render_triptych_png(
        aoi=aoi,
        pre_image=pre_image,
        post_image=post_image,
        pwtt_image=image,
        buildings_geojson=buildings_geojson,
    )
    write_cached_bytes(int(run["id"]), "triptych.png", png_bytes)
    return png_bytes
