"""Small helpers for per-run cached files.

The app stores expensive derived outputs on disk so opening a finished run does
not recompute building footprints or image exports every time.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..settings import settings


def get_run_cache_dir(run_id: int) -> Path:
    """Return the folder used to store cached outputs for one run."""

    path = settings.run_cache_dir / str(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_run_cache_file(run_id: int, filename: str) -> Path:
    """Build one cache file path inside the run cache directory."""

    return get_run_cache_dir(run_id) / filename


def read_cached_json(run_id: int, filename: str) -> dict[str, Any] | None:
    """Load one cached JSON document when it already exists."""

    path = get_run_cache_file(run_id, filename)
    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def write_cached_json(run_id: int, filename: str, payload: dict[str, Any]) -> Path:
    """Write one JSON cache file for later reuse."""

    path = get_run_cache_file(run_id, filename)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_cached_bytes(run_id: int, filename: str, payload: bytes) -> Path:
    """Write one binary cache file such as a PNG export."""

    path = get_run_cache_file(run_id, filename)
    path.write_bytes(payload)
    return path


def delete_run_cache(run_id: int) -> None:
    """Remove cached files for a deleted run."""

    path = settings.run_cache_dir / str(run_id)
    if path.exists():
        shutil.rmtree(path)
