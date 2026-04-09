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
    """Create the database tables from the plain SQL migration files."""

    migrations_dir = ROOT_DIR / "backend" / "migrations"
    migration_files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())

    with get_connection() as connection:
        for migration_file in migration_files:
            sql = migration_file.read_text(encoding="utf-8")
            connection.executescript(sql)
        connection.commit()


def database_exists() -> bool:
    """Tell setup scripts whether the database file already exists."""

    return Path(settings.database_path).exists()

