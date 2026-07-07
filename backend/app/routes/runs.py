"""Routes for creating runs, checking progress, and exporting KML."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..repositories.runs_repository import create_run, delete_run, get_run, list_runs, requeue_run
from ..schemas import PreflightOutput, RunCreateInput
from ..services.cache_service import delete_run_cache, get_run_cache_file
from ..services.earth_engine_service import ensure_earth_engine, geometry_from_geojson
from ..services.kml_service import feature_collection_to_kml
from ..services.pipeline_service import (
    build_run_detail,
    check_sentinel1_coverage,
    export_damage_kml,
    export_triptych_png,
)


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def get_runs() -> list[dict]:
    """List recent analyses so the user can revisit past work."""

    return list_runs()


@router.post("")
def enqueue_run(payload: RunCreateInput) -> dict[str, int | str]:
    """Create a queued analysis run that the scheduler will pick up shortly."""

    run_id = create_run(payload.model_dump())
    return {"id": run_id, "status": "queued"}


@router.post("/preflight")
def preflight_run(payload: RunCreateInput) -> PreflightOutput:
    """Check Sentinel-1 coverage for the chosen AOI and dates before queueing.

    This runs the same coverage validation the pipeline performs, but at
    submit time — so a bad date combination fails in seconds with a clear
    message instead of after minutes in the queue. It also reports scene
    counts so the user can judge the statistical power of their windows.
    """

    try:
        ensure_earth_engine()
        aoi = geometry_from_geojson(payload.aoi_geojson)
        coverage = check_sentinel1_coverage(aoi, payload.model_dump())
    except ValueError as exc:
        return PreflightOutput(ok=False, message=str(exc), coverage=None)

    return PreflightOutput(ok=True, message=None, coverage=coverage)


@router.get("/{run_id}")
def get_run_detail(run_id: int) -> dict:
    """Return one run, including fresh map tile URLs when it has finished."""

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    if run["status"] == "completed":
        return build_run_detail(run)
    return run


_VALID_PREVIEW_PANELS = {"pre", "post", "pwtt"}


@router.get("/{run_id}/preview/{panel}")
def get_run_preview_image(run_id: int, panel: str) -> Response:
    """Serve one of the three cached preview panel images for a finished run."""

    if panel not in _VALID_PREVIEW_PANELS:
        raise HTTPException(status_code=404, detail="Invalid panel name.")
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    path = get_run_cache_file(run_id, f"preview_{panel}.png")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Preview image not cached yet.")
    return Response(content=path.read_bytes(), media_type="image/png")


@router.get("/{run_id}/export.kml")
def export_run_kml(run_id: int) -> Response:
    """Recompute damage polygons and stream them back as KML."""

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "completed":
        raise HTTPException(status_code=409, detail="The run must finish before export is available.")

    feature_collection = export_damage_kml(run)
    kml_text = feature_collection_to_kml(feature_collection, f"PWTT Run {run_id}")
    headers = {"Content-Disposition": f'attachment; filename="pwtt-run-{run_id}.kml"'}
    return Response(content=kml_text, media_type="application/vnd.google-earth.kml+xml", headers=headers)


@router.get("/{run_id}/export.png")
def export_run_png(run_id: int) -> Response:
    """Stream the cached triptych PNG for one finished run."""

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "completed":
        raise HTTPException(status_code=409, detail="The run must finish before export is available.")

    png_bytes = export_triptych_png(run)
    headers = {"Content-Disposition": f'attachment; filename="pwtt-run-{run_id}.png"'}
    return Response(content=png_bytes, media_type="image/png", headers=headers)


@router.post("/{run_id}/retry")
def retry_run(run_id: int) -> dict[str, int | str]:
    """Re-queue a failed run so the scheduler will attempt it again."""

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed runs can be retried.")

    requeue_run(run_id)
    return {"id": run_id, "status": "queued"}


@router.delete("/{run_id}", status_code=204)
def remove_run(run_id: int) -> Response:
    """Delete one finished or failed run from history and remove its cache."""

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Wait for the run to finish before removing it.")

    delete_run(run_id)
    delete_run_cache(run_id)
    return Response(status_code=204)
