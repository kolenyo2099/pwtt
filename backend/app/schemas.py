"""Pydantic models shared by routes and services.

These models define the API contract in plain terms so the frontend and backend
agree on the exact shape of requests and responses.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ~160 km × 160 km bounding box. Larger areas routinely exceed Earth Engine
# compute budgets or hang for tens of minutes without returning.
AOI_WARN_KM2 = 10_000
AOI_MAX_KM2 = 100_000


def _collect_coords(obj: Any, out: list[list[float]]) -> None:
    """Recursively pull every [lon, lat] leaf out of a GeoJSON object."""

    if isinstance(obj, list):
        if len(obj) >= 2 and isinstance(obj[0], (int, float)):
            out.append(obj)
        else:
            for item in obj:
                _collect_coords(item, out)
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_coords(value, out)


def aoi_bbox_area_km2(geojson: dict[str, Any]) -> float:
    """Return the bounding-box area in km² for a GeoJSON geometry.

    Uses the equirectangular approximation with a cosine correction for
    longitude extent. This overestimates for non-rectangular shapes, which
    is intentional — the validation should be conservative.
    """

    coords: list[list[float]] = []
    _collect_coords(geojson, coords)
    if len(coords) < 3:
        return 0.0

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    lat_span = max(lats) - min(lats)
    lon_span = max(lons) - min(lons)
    avg_lat = (max(lats) + min(lats)) / 2.0
    height_km = lat_span * 111.32
    width_km = lon_span * 111.32 * math.cos(math.radians(avg_lat))
    return height_km * width_km


RunStatus = Literal["queued", "running", "completed", "failed"]
RunMethod = Literal["stouffer", "max", "ztest", "hotelling", "mahalanobis"]


class AuthSettingsInput(BaseModel):
    """The Earth Engine settings a user can save from the first wizard step."""

    project_id: str = Field(min_length=1)


class AuthSettingsOutput(BaseModel):
    """The saved authentication state shown back to the frontend."""

    configured: bool
    project_id: str | None = None
    auth_mode: Literal["ambient", "missing"]
    credentials_present: bool
    credentials_path: str | None = None


class BrowserAuthOutput(BaseModel):
    """Current status of the browser-based Earth Engine login helper."""

    status: Literal["idle", "running", "completed", "failed"]
    message: str
    credentials_present: bool
    credentials_path: str | None = None


class RunCreateInput(BaseModel):
    """The information needed to enqueue one PWTT analysis."""

    aoi_name: str | None = None
    aoi_geojson: dict[str, Any]
    war_start: str
    inference_start: str
    pre_interval: float = 12
    post_interval: float = 1
    threshold: float = 3.3
    method: RunMethod = "stouffer"

    @field_validator("aoi_geojson", mode="before")
    @classmethod
    def normalize_aoi_geometry(cls, value: Any) -> dict[str, Any]:
        """Accept either a raw GeoJSON geometry or a full GeoJSON feature."""

        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, dict):
            raise ValueError("The AOI shape is missing or invalid.")

        if value.get("type") == "Feature":
            geometry = value.get("geometry")
            if not isinstance(geometry, dict):
                raise ValueError("The AOI feature does not contain a valid geometry.")
            return geometry

        if "type" not in value:
            raise ValueError("The AOI geometry must include a GeoJSON type.")

        return value

    @field_validator("aoi_geojson", mode="after")
    @classmethod
    def check_aoi_area(cls, value: Any) -> Any:
        """Reject AOIs whose bounding box exceeds the Earth Engine compute budget.

        Very large areas cause GEE reduceRegion and reduceToVectors calls to
        run for tens of minutes or hang indefinitely. This guard provides a
        fast-fail with a clear message before any GEE work begins.
        """

        area = aoi_bbox_area_km2(value)
        if area > AOI_MAX_KM2:
            raise ValueError(
                f"The AOI bounding box is approximately {int(area):,} km², "
                f"which exceeds the {AOI_MAX_KM2:,} km² limit. "
                "Earth Engine compute budgets cannot handle areas this large reliably. "
                "Draw a smaller polygon and re-submit."
            )
        return value

    @field_validator("pre_interval", "post_interval", "threshold", mode="before")
    @classmethod
    def normalize_decimal_numbers(cls, value: Any) -> float:
        """Accept decimal strings that use either a dot or a comma."""

        if isinstance(value, str):
            value = value.strip().replace(",", ".")

        return float(value)

    @field_validator("war_start", "inference_start", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        """Trim incoming date strings so the route does not reject harmless whitespace."""

        if isinstance(value, str):
            return value.strip()

        return str(value)


class RunSummary(BaseModel):
    """A short summary row used in the wizard and recent-runs list."""

    id: int
    status: RunStatus
    aoi_name: str | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class LayerUrls(BaseModel):
    """Tile layers used to render the pre, post, and PWTT result maps."""

    pre_event: str
    post_event: str
    pwtt_overlay: str
    buildings_overlay: str | None = None
    pre_event_preview: str | None = None
    post_event_preview: str | None = None
    pwtt_preview: str | None = None


class BuildingResultSummary(BaseModel):
    """A compact summary of building-level screening results."""

    available: bool
    reason: str | None = None
    total_buildings: int
    damaged_buildings: int
    damaged_share_pct: float
    asset_ids: list[str] | None = None
    top_damaged_buildings: list[dict[str, str | float]] | None = None


class RunResultSummary(BaseModel):
    """A non-technical summary of what the model found."""

    damaged_area_ha: float
    damage_share_pct: float
    mean_t_score: float
    max_t_score: float
    damaged_pixel_estimate: int
    buildings: BuildingResultSummary | None = None


class RunDetail(RunSummary):
    """A full run response for the results step of the wizard."""

    parameters: RunCreateInput
    summary: RunResultSummary | None = None
    layers: LayerUrls | None = None
