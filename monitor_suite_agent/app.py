"""FastAPI application for Monitor Suite Agent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request

from . import __version__
from .config import Settings
from .models import HealthResponse, StatusResponse
from .security import require_api_key
from .telemetry import TelemetrySampler


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API with one validated immutable settings object."""
    runtime_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sampler = TelemetrySampler(runtime_settings)
        app.state.sampler = sampler
        await sampler.start()
        try:
            yield
        finally:
            await sampler.stop()

    docs_url = "/docs" if runtime_settings.enable_docs else None
    openapi_url = "/openapi.json" if runtime_settings.enable_docs else None
    application = FastAPI(
        title="Monitor Suite Agent",
        version=__version__,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
    )
    application.state.settings = runtime_settings

    @application.get(
        "/health", response_model=HealthResponse, dependencies=[Depends(require_api_key)]
    )
    async def health(request: Request) -> HealthResponse:
        result = request.app.state.sampler.health()
        return HealthResponse(
            status=result["status"],
            version=__version__,
            sample_available=result["sample_available"],
        )

    @application.get(
        "/status",
        response_model=StatusResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(require_api_key)],
    )
    async def monitor_status(request: Request) -> StatusResponse:
        snapshot = request.app.state.sampler.snapshot()
        if snapshot is None:
            raise HTTPException(status_code=503, detail="Status is not available yet")
        return StatusResponse.model_validate(snapshot)

    return application


app = create_app()
