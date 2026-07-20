"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import run_migrations
from .routes.health import router as health_router
from .routes.runs import router as runs_router
from .routes.settings import router as settings_router
from .scheduler import start_scheduler
from .settings import settings


app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(runs_router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    """Make sure the local database and background queue are ready."""

    run_migrations()
    start_scheduler()
