"""Central application settings.

This file keeps environment variables in one place so the rest of the code does
not need to guess where ports, database paths, or credentials should come from.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class AppSettings(BaseSettings):
    """Read environment variables once and expose safe defaults."""

    app_name: str = "PWTT Wizard"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_port: int = 5173
    database_path: Path = ROOT_DIR / "backend" / "data" / "flightwatch.db"
    run_cache_dir: Path = ROOT_DIR / "backend" / "data" / "run_cache"
    earth_engine_project: str | None = None
    ms_buildings_parent: str = "projects/sat-io/open-datasets/MSBuildings"
    ms_buildings_cache_hours: int = 24 * 7

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def backend_url(self) -> str:
        """Base URL the frontend uses to reach the backend API."""

        return f"http://127.0.0.1:{self.backend_port}"

    @property
    def cors_origins(self) -> list[str]:
        """Return the local frontend URLs that are allowed to call the API."""

        return [
            f"http://localhost:{self.frontend_port}",
            f"http://127.0.0.1:{self.frontend_port}",
        ]

    @property
    def cors_origin_regex(self) -> str:
        """Allow local dev frontends even when Vite falls back to another port."""

        return r"^http://(localhost|127\.0\.0\.1):\d+$"


settings = AppSettings()
