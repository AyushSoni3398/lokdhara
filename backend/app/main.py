"""FastAPI application factory. Run with: uv run uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app.config import get_settings
from app.errors import install_error_handlers
from app.health import router as health_router
from app.modules.identity.router import router as identity_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    is_production = settings.env == "production"
    app = FastAPI(
        title="Lokdhara API",
        version="0.1.0",
        # Interactive docs only outside production.
        docs_url=None if is_production else "/api/docs",
        openapi_url=None if is_production else "/api/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(identity_router, prefix=API_PREFIX)
    return app


app = create_app()
