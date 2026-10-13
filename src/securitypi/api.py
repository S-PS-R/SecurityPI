"""Foundation API. Process health is intentionally distinct from monitoring health."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from securitypi import __version__
from securitypi.config import Settings


class HealthResponse(BaseModel):
    service: Literal["securitypi"] = "securitypi"
    version: str = __version__
    status: Literal["ok"] = "ok"


class StatusResponse(BaseModel):
    stage: Literal["foundation"] = "foundation"
    monitoring: Literal[False] = False
    camera: Literal["not_started"] = "not_started"
    detection: Literal["not_implemented"] = "not_implemented"
    home_assistant: Literal["not_connected"] = "not_connected"
    parking: Literal["unknown"] = "unknown"


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="SecurityPI", version=__version__)
    app.state.settings = settings

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        return StatusResponse()

    return app
