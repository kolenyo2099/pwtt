"""Command-line helper used by setup.sh to create the SQLite database."""

from .database import run_migrations


if __name__ == "__main__":
    run_migrations()

