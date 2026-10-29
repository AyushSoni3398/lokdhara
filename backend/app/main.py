"""FastAPI application factory. Run with: uv run uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app import log_privacy
from app.config import get_settings
from app.errors import install_error_handlers
from app.health import router as health_router
from app.modules.catalogue.router import router as catalogue_router
from app.modules.consents.router import router as consents_router
from app.modules.identity.router import router as identity_router
from app.modules.ops.router import router as ops_router
from app.modules.processing.router import router as processing_router
from app.modules.prompts.router import router as prompts_router
from app.modules.releases.router import router as releases_router
from app.modules.reports.router import router as reports_router
from app.modules.speakers.router import router as speakers_router
from app.modules.submissions.router import router as submissions_router
from app.modules.topics.router import router as topics_router
from app.modules.withdrawals.router import router as withdrawals_router
from app.object_store.router import router as local_storage_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    is_production = settings.env == "production"
    log_privacy.configure(settings.log_level)
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
    app.include_router(processing_router, prefix=API_PREFIX)
    app.include_router(speakers_router, prefix=API_PREFIX)
    app.include_router(consents_router, prefix=API_PREFIX)
    app.include_router(prompts_router, prefix=API_PREFIX)
    app.include_router(topics_router, prefix=API_PREFIX)
    app.include_router(submissions_router, prefix=API_PREFIX)
    app.include_router(reports_router, prefix=API_PREFIX)
    app.include_router(catalogue_router, prefix=API_PREFIX)
    app.include_router(releases_router, prefix=API_PREFIX)
    app.include_router(withdrawals_router, prefix=API_PREFIX)
    app.include_router(ops_router, prefix=API_PREFIX)
    if settings.storage_backend == "local" and settings.is_local:
        app.include_router(local_storage_router, prefix=API_PREFIX)
    return app


app = create_app()
