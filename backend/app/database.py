"""Small helpers for SQLite access and database bootstrapping.

The application is intentionally simple, so we use plain SQL instead of an ORM.
That keeps the data model easy to audit and easy to move into Tauri later.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .settings import ROOT_DIR, settings


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with dictionary-style rows."""

    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def run_migrations() -> None:
    """Apply the plain SQL migration files that have not been applied yet.

    Applied filenames are tracked in schema_migrations so migrations that are
    not idempotent (such as ALTER TABLE ADD COLUMN) run exactly once. Databases
    created before this table existed simply re-run the initial migration,
    which only contains CREATE TABLE IF NOT EXISTS statements.
    """

    migrations_dir = ROOT_DIR / "backend" / "migrations"
    migration_files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            row["filename"] for row in connection.execute("SELECT filename FROM schema_migrations").fetchall()
        }
        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            connection.executescript(migration_file.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (migration_file.name,))
        connection.commit()


def database_exists() -> bool:
    """Tell setup scripts whether the database file already exists."""

    return Path(settings.database_path).exists()

