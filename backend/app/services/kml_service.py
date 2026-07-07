"""Convert GeoJSON-like damage polygons into a downloadable KML file."""

from __future__ import annotations

import json
from typing import Any

import simplekml

# KML colors are AABBGGRR. These match the UI overlay palette exactly:
# #fdb515 → b415b5fd, #d9661f → b41f66d9, #770747 → b4470777
_COLOR_ELEVATED = "b415b5fd"
_COLOR_HIGH = "b41f66d9"
_COLOR_SEVERE = "b4470777"


def _polygon_color(category: str | None) -> str:
    """Pick a fill color that matches the UI damage categories."""

    if category == "Severe":
        return _COLOR_SEVERE
    if category == "High":
        return _COLOR_HIGH
    return _COLOR_ELEVATED


def _add_polygon(
    kml: simplekml.Kml,
    name: str,
    coordinates: list[list[list[float]]],
    description: str,
    category: str | None,
    properties: dict[str, Any],
) -> None:
    """Add one polygon feature to the KML document with a readable default style."""

    polygon = kml.newpolygon(
        name=name,
        outerboundaryis=coordinates[0],
        innerboundaryis=coordinates[1] if len(coordinates) > 1 else (),
    )
    polygon.description = description
    polygon.style.polystyle.color = _polygon_color(category)
    polygon.style.polystyle.outline = 1
    polygon.style.linestyle.width = 2
    for key, value in properties.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=True)
        polygon.extendeddata.newdata(key, str(value))


def _build_description(properties: dict[str, Any]) -> str:
    """Render the key building attributes in a readable KML description."""

    ordered_keys = [
        "label",
        "category",
        "damage_probability",
        "damaged",
        "source_provider",
        "source_asset_id",
        "google_maps_url",
    ]
    rows: list[str] = []

    for key in ordered_keys:
        value = properties.get(key)
        if value is None:
            continue
        if key == "google_maps_url":
            rows.append(f'Google Maps: <a href="{value}">{value}</a>')
        else:
            rows.append(f"{key.replace('_', ' ').title()}: {value}")

    extra_keys = sorted(key for key in properties.keys() if key not in ordered_keys)
    for key in extra_keys:
        value = properties.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=True)
        rows.append(f"{key}: {value}")

    return "\n".join(rows)


def _geometry_center(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """Approximate a polygon center so exports can still deep-link old caches."""

    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon" and coordinates:
        ring = coordinates[0]
    elif geometry.get("type") == "MultiPolygon" and coordinates:
        ring = coordinates[0][0]
    else:
        return None

    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return ((min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2)


def feature_collection_to_kml(feature_collection: dict[str, Any], document_name: str) -> str:
    """Build a KML string from a GeoJSON FeatureCollection."""

    kml = simplekml.Kml(name=document_name)

    for index, feature in enumerate(feature_collection.get("features", []), start=1):
        geometry = feature.get("geometry", {})
        properties = feature.get("properties", {})
        damaged = properties.get("damaged")
        if damaged is not None and not damaged:
            continue
        if "label" not in properties:
            properties["label"] = f"Building {index}"
        if "damage_probability" not in properties and properties.get("mean") is not None:
            properties["damage_probability"] = properties["mean"]
        if "google_maps_url" not in properties:
            center = _geometry_center(geometry)
            if center:
                properties["google_maps_url"] = f"https://www.google.com/maps?q={center[1]},{center[0]}"
        category = properties.get("category")
        description = _build_description(properties)

        label = properties.get("label")
        if damaged is not None:
            prefix = f"{category} " if category else ""
            feature_name = f"{prefix}{label or f'Building {index}'}"
        else:
            feature_name = f"Damage zone {index}"

        if geometry.get("type") == "Polygon":
            _add_polygon(kml, feature_name, geometry["coordinates"], description, category, properties)
        elif geometry.get("type") == "MultiPolygon":
            for polygon_index, polygon_coordinates in enumerate(geometry["coordinates"], start=1):
                _add_polygon(kml, f"{feature_name}.{polygon_index}", polygon_coordinates, description, category, properties)

    return kml.kml()
