"""Routes for saved Earth Engine authentication settings."""

from fastapi import APIRouter, HTTPException

from ..repositories.settings_repository import get_auth_settings, save_auth_settings
from ..schemas import AuthSettingsInput, AuthSettingsOutput, BrowserAuthOutput
from ..services.earth_engine_service import (
    ensure_earth_engine,
    get_browser_auth_status,
    inspect_auth,
    start_browser_auth,
)


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/auth", response_model=AuthSettingsOutput)
def get_saved_auth() -> AuthSettingsOutput:
    """Return whether the local Earth Engine login and project are ready."""

    saved = get_auth_settings()
    return AuthSettingsOutput(**inspect_auth(saved.get("project_id")))


@router.put("/auth", response_model=AuthSettingsOutput)
def save_auth(payload: AuthSettingsInput) -> AuthSettingsOutput:
    """Save the Earth Engine project and validate it if local login exists."""

    auth_state = inspect_auth(payload.project_id)

    if auth_state["credentials_present"]:
        try:
            auth_state = ensure_earth_engine(payload.project_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    save_auth_settings(payload.project_id)
    return AuthSettingsOutput(**auth_state)


@router.get("/auth/browser", response_model=BrowserAuthOutput)
def get_browser_auth() -> BrowserAuthOutput:
    """Return the state of the backend-driven browser login helper."""

    return BrowserAuthOutput(**get_browser_auth_status())


@router.post("/auth/browser", response_model=BrowserAuthOutput)
def launch_browser_auth() -> BrowserAuthOutput:
    """Launch the official Earth Engine browser login on this same machine."""

    return BrowserAuthOutput(**start_browser_auth())
