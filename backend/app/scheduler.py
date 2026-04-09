"""Background queue poller.

The scheduler keeps the API responsive by moving PWTT runs into background
threads. APScheduler is used as the simple queue driver, which matches the
project requirement for a poller-based backend.
"""

from __future__ import annotations

import threading

from apscheduler.schedulers.background import BackgroundScheduler

from .repositories.runs_repository import (
    get_next_queued_run,
    get_stalled_runs,
    mark_run_completed,
    mark_run_failed,
    mark_run_running,
)
from .services.pipeline_service import execute_run


_scheduler: BackgroundScheduler | None = None
_active_run_ids: set[int] = set()
_active_lock = threading.Lock()

# A run that produces no heartbeat for this long is assumed to be stuck on a
# blocking GEE call and will be marked as failed so the UI reflects reality.
# Raised to 90 minutes because tiled building retrieval on large AOIs can
# legitimately take 60+ minutes across many sequential tile round-trips.
_STALL_TIMEOUT_SECONDS = 90 * 60  # 90 minutes


def _worker(run_id: int, parameters: dict) -> None:
    """Run one analysis and write either a summary or an error back to SQLite."""

    try:
        summary = execute_run(run_id, parameters)
        mark_run_completed(run_id, summary)
    except Exception as exc:  # noqa: BLE001
        mark_run_failed(run_id, str(exc))
    finally:
        with _active_lock:
            _active_run_ids.discard(run_id)


def poll_run_queue() -> None:
    """Start one queued run at a time so local machines do not get overloaded."""

    with _active_lock:
        if _active_run_ids:
            return

    next_run = get_next_queued_run()
    if not next_run:
        return

    run_id = int(next_run["id"])
    mark_run_running(run_id)

    with _active_lock:
        _active_run_ids.add(run_id)

    thread = threading.Thread(target=_worker, args=(run_id, next_run["parameters"]), daemon=True)
    thread.start()


def reap_stalled_runs() -> None:
    """Fail any run that has made no heartbeat progress within the timeout window.

    execute_run calls touch_run_heartbeat after each major Earth Engine step.
    A run that has not updated its timestamp in _STALL_TIMEOUT_SECONDS is
    almost certainly stuck on a blocking GEE call — most likely caused by an
    AOI that is too large for the configured compute budget.
    """

    stalled = get_stalled_runs(_STALL_TIMEOUT_SECONDS)
    for row in stalled:
        run_id = row["id"]
        mark_run_failed(
            run_id,
            f"Run stopped making progress and was cancelled after "
            f"{_STALL_TIMEOUT_SECONDS // 60} minutes. A GEE request is likely "
            "hanging — this can happen with very large or densely-built AOIs. "
            "Try a smaller area, a shorter date range, or raise the threshold "
            "to reduce the number of candidate buildings.",
        )
        with _active_lock:
            _active_run_ids.discard(run_id)


def start_scheduler() -> None:
    """Boot the shared background scheduler once."""

    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(poll_run_queue, "interval", seconds=3, max_instances=1, coalesce=True)
    _scheduler.add_job(reap_stalled_runs, "interval", minutes=1, max_instances=1, coalesce=True)
    _scheduler.start()
