"""Database access for PWTT analysis runs."""

from __future__ import annotations

import json
from typing import Any

from ..database import get_connection


def create_run(payload: dict[str, Any]) -> int:
    """Insert a new queued run and return its database id."""

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO runs (
                status,
                aoi_name,
                aoi_geojson,
                parameters_json,
                created_at,
                updated_at
            )
            VALUES (
                'queued',
                ?,
                ?,
                ?,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """,
            (
                payload.get("aoi_name"),
                json.dumps(payload["aoi_geojson"]),
                json.dumps(payload),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_runs(limit: int = 10) -> list[dict[str, Any]]:
    """Return recent runs so the interface can show analysis history."""

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, status, aoi_name, created_at, updated_at, error_message
            FROM runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run(run_id: int) -> dict[str, Any] | None:
    """Load one run, including its saved parameters and result summary."""

    with get_connection() as connection:
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    if row is None:
        return None

    run = dict(row)
    run["aoi_geojson"] = json.loads(run["aoi_geojson"])
    run["parameters"] = json.loads(run["parameters_json"])
    run["summary"] = json.loads(run["summary_json"]) if run["summary_json"] else None
    return run


def get_next_queued_run() -> dict[str, Any] | None:
    """Return the oldest queued run so the scheduler can process it."""

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM runs
            WHERE status = 'queued'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
    return get_run(int(row["id"])) if row else None


def mark_run_running(run_id: int) -> None:
    """Mark a queued run as actively processing."""

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'running',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (run_id,),
        )
        connection.commit()


def mark_run_completed(run_id: int, summary: dict[str, Any]) -> None:
    """Save the completed summary payload for a finished run."""

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                summary_json = ?,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(summary), run_id),
        )
        connection.commit()


def update_run_summary(run_id: int, summary: dict[str, Any]) -> None:
    """Refresh a stored summary when cached derived outputs were rebuilt later."""

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET summary_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(summary), run_id),
        )
        connection.commit()


def mark_run_failed(run_id: int, error_message: str) -> None:
    """Save a failure message so the UI can explain what went wrong."""

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'failed',
                error_message = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error_message[:2000], run_id),
        )
        connection.commit()


def touch_run_heartbeat(run_id: int) -> None:
    """Stamp updated_at so the stall detector knows this run is still making progress."""

    with get_connection() as connection:
        connection.execute(
            "UPDATE runs SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'running'",
            (run_id,),
        )
        connection.commit()


def get_stalled_runs(timeout_seconds: int) -> list[dict[str, Any]]:
    """Return runs that have been stuck in the 'running' state past the timeout window.

    A run is considered stalled when updated_at has not moved for longer than
    timeout_seconds. execute_run calls touch_run_heartbeat after each major GEE
    step, so a genuine stall (hanging getInfo call) will stop producing updates.
    """

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM runs
            WHERE status = 'running'
              AND (julianday('now') - julianday(updated_at)) * 86400.0 > ?
            """,
            (timeout_seconds,),
        ).fetchall()
    return [{"id": int(row["id"])} for row in rows]


def delete_run(run_id: int) -> None:
    """Remove one run row after the UI asks to clear it from history."""

    with get_connection() as connection:
        connection.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        connection.commit()
