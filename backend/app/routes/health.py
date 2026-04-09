"""Simple health routes used by setup and the frontend."""

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    """Confirm that the API process is alive."""

    return {"status": "ok"}

