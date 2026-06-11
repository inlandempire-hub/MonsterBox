"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (import so tables register on Base.metadata)
from .config import settings
from .db import Base, engine
from .routers import account, admin, health, statblocks


def create_app() -> FastAPI:
    # Skeleton convenience: auto-create tables. In production this is replaced by
    # Alembic migrations (the schema is otherwise unchanged).
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title="MonsterBox API", version="0.1.0")
    # Auth is by bearer token (not cookies), so we don't need credentialed CORS.
    # In dev, allow any origin so the local PWA (any port) can call the API; in
    # production, lock to the configured PWA origin(s).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.dev_auth else settings.cors_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(account.router)
    app.include_router(statblocks.router)
    app.include_router(admin.router)
    return app


app = create_app()
