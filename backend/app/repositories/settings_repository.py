"""Database access for saved application settings.

These helpers keep small app-wide values in one table so cached metadata and
saved configuration can be reused across sessions without adding another store.
"""

from __future__ import annotations

from datetime import datetime

from ..database import get_connection


def get_auth_settings() -> dict[str, str | None]:
    """Return the saved Earth Engine project for local user credentials."""

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT key, value FROM app_settings WHERE key IN ('earth_engine_project')"
        ).fetchall()

    values = {row["key"]: row["value"] for row in rows}
    return {
        "project_id": values.get("earth_engine_project"),
    }


def get_setting(key: str) -> dict[str, str | datetime | None] | None:
    """Return one setting row with its timestamp when the caller needs cache freshness."""

    with get_connection() as connection:
        row = connection.execute(
            "SELECT key, value, updated_at FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()

    return dict(row) if row else None


def save_setting(key: str, value: str) -> None:
    """Insert or replace one setting value in the shared table."""

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        connection.commit()


def save_auth_settings(project_id: str) -> None:
    """Store the user's Earth Engine project for later runs."""

    save_setting("earth_engine_project", project_id)
