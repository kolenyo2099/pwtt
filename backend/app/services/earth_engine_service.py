"""Earth Engine setup and small helper functions.

This service keeps all Earth Engine initialization in one place so routes and
pipeline logic can focus on the actual analysis steps.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from typing import Any

import ee

from ..repositories.settings_repository import get_auth_settings
from ..settings import settings


_init_lock = threading.Lock()
_initialized_fingerprint: str | None = None
_browser_auth_lock = threading.Lock()
_browser_auth_state = {
    "status": "idle",
    "message": "Not started.",
}


def get_credentials_path() -> str:
    """Return the standard Earth Engine user credential file path."""

    return ee.oauth.get_credentials_path()


def credentials_present() -> bool:
    """Tell the app whether a local Earth Engine login already exists."""

    return os.path.exists(get_credentials_path())


def get_effective_auth() -> dict[str, str | None]:
    """Return the saved Earth Engine project, falling back to the environment."""

    saved = get_auth_settings()
    return {
        "project_id": saved.get("project_id") or settings.earth_engine_project,
    }


def inspect_auth(project_id: str | None = None) -> dict[str, str | bool | None]:
    """Summarize whether local Earth Engine access is ready to use."""

    effective = get_effective_auth()
    project = project_id or effective["project_id"]
    local_credentials_present = credentials_present()

    return {
        "configured": bool(project and local_credentials_present),
        "project_id": project,
        "auth_mode": "ambient" if local_credentials_present else "missing",
        "credentials_present": local_credentials_present,
        "credentials_path": get_credentials_path(),
    }


def ensure_earth_engine(project_id: str | None = None) -> dict[str, str | bool | None]:
    """Initialize Earth Engine using the normal user login stored on disk."""

    effective = get_effective_auth()
    project = project_id or effective["project_id"]

    if not project:
        raise ValueError("An Earth Engine cloud project is required before running the pipeline.")
    if not credentials_present():
        raise ValueError(
            "Earth Engine login is missing. Use the app's browser login button or run 'earthengine authenticate'."
        )

    fingerprint = hashlib.sha1(project.encode("utf-8")).hexdigest()

    global _initialized_fingerprint
    with _init_lock:
        if fingerprint != _initialized_fingerprint:
            ee.Initialize(project=project)
            ee.data.setDeadline(600_000)  # milliseconds → 10 minutes
            # This small server-side request confirms the stored login really works.
            ee.Number(1).getInfo()
            _initialized_fingerprint = fingerprint

    return inspect_auth(project)


def _run_browser_auth() -> None:
    """Launch the official Earth Engine browser login and record the result."""

    global _browser_auth_state
    command = [
        sys.executable,
        "-m",
        "ee.cli.eecli",
        "authenticate",
        "--auth_mode=localhost",
        "--quiet",
        "--force",
    ]

    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        output = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode == 0 and credentials_present():
            _browser_auth_state = {
                "status": "completed",
                "message": "Earth Engine login completed in your browser.",
            }
        else:
            _browser_auth_state = {
                "status": "failed",
                "message": output or "Earth Engine login failed.",
            }
    except Exception as exc:  # noqa: BLE001
        _browser_auth_state = {
            "status": "failed",
            "message": str(exc),
        }


def start_browser_auth() -> dict[str, str | bool | None]:
    """Start the local browser-based Earth Engine OAuth flow once."""

    global _browser_auth_state
    with _browser_auth_lock:
        if _browser_auth_state["status"] == "running":
            return get_browser_auth_status()

        _browser_auth_state = {
            "status": "running",
            "message": "Browser login started. Finish the Earth Engine sign-in in the opened window.",
        }
        thread = threading.Thread(target=_run_browser_auth, daemon=True)
        thread.start()
    return get_browser_auth_status()


def get_browser_auth_status() -> dict[str, str | bool | None]:
    """Return the current browser login helper status for the frontend."""

    return {
        "status": _browser_auth_state["status"],
        "message": _browser_auth_state["message"],
        "credentials_present": credentials_present(),
        "credentials_path": get_credentials_path(),
    }


def geometry_from_geojson(geojson: dict[str, Any]) -> ee.Geometry:
    """Convert a browser GeoJSON shape into an Earth Engine geometry."""

    return ee.Geometry(geojson)


def make_tile_url(image: ee.Image, vis_params: dict[str, Any]) -> str:
    """Return a tile URL that the frontend can use inside Leaflet."""

    map_id = ee.Image(image).getMapId(vis_params)
    return map_id["tile_fetcher"].url_format


def make_thumbnail_url(image: ee.Image, region: dict[str, Any], width: int) -> str:
    """Return a one-off PNG URL for a static preview image.

    The results view behaves more like a report than a GIS editor, so static
    previews are easier to size reliably than interactive map tiles.
    """

    return ee.Image(image).getThumbURL(
        {
            "region": region,
            "dimensions": width,
            "format": "png",
            "crs": "EPSG:4326",
        }
    )
