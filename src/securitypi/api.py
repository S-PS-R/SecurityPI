"""Loopback bridge to Home Assistant; never opens the camera or imports inference."""

import shutil
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from securitypi import __version__
from securitypi.config import Settings
from securitypi.history import read_tracks
from securitypi.snapshots import inventory
from securitypi.state import read_json, read_vision


class HealthResponse(BaseModel):
    service: Literal["securitypi"] = "securitypi"
    version: str = __version__
    status: Literal["ok"] = "ok"


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="SecurityPI", version=__version__)
    app.state.settings = settings

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/status")
    def status():
        current = read_vision(settings.storage.directory)
        return {
            "stage": "vision_candidate",
            "monitoring": current["monitoring"],
            "camera": current["state"],
            "detection": "running" if current["monitoring"] else "offline",
            "home_assistant": (
                "configured_unverified"
                if settings.home_assistant.notifications_enabled
                else "not_connected"
            ),
            "parking": "unknown",
        }

    @app.get("/api/vision")
    def vision():
        return read_vision(settings.storage.directory)

    @app.get("/api/history/tracks")
    def track_history():
        return read_tracks(settings.storage.directory, time.time())

    @app.get("/api/storage")
    def storage():
        directory = settings.storage.directory
        database = directory / "home-assistant" / "home-assistant_v2.db"
        # Include SQLite's live journal; never open HA's database for writing.
        sizes = []
        for suffix in ("", "-wal", "-shm"):
            try:
                sizes.append(database.with_name(database.name + suffix).stat().st_size)
            except FileNotFoundError:
                pass
        tracks = directory / "tracks.sqlite3"
        images = inventory(directory)
        return {
            "snapshot_count": len(images),
            "snapshot_mib": round(sum(row[2] for row in images) / 1048576, 2),
            "history_mib": round(sum(sizes) / 1048576, 2) if sizes else None,
            "disk_free_gib": round(shutil.disk_usage(directory).free / 1073741824, 1),
            "tracks_mib": round(tracks.stat().st_size / 1048576, 2) if tracks.exists() else None,
        }

    @app.get("/api/notifications")
    def notifications():
        enabled = settings.home_assistant.notifications_enabled
        result = {
            "enabled": enabled,
            "worker_running": False,
            "phone_receipt": "unverified",
            "events": {},
            "recent_events": [],
            "rules": {
                "person_seconds": settings.home_assistant.person_seconds,
                "road_linger_seconds": settings.activity.road_linger_seconds,
                "person_alert_mode": "per_track",
            },
        }
        if enabled:
            try:
                state = read_json(settings.storage.directory / "notifications.json", limit=8192)
                age = time.time() - state["updated_at"]
                result["worker_running"] = bool(state["running"] and 0 <= age <= 30)
                if isinstance(state["events"], dict):
                    result["events"] = {
                        key: count
                        for key, count in state["events"].items()
                        if key
                        in ("pending", "accepted", "rejected", "expired", "failed", "cancelled")
                        and type(count) is int
                        and 0 <= count <= 100
                    }
                recent = state.get("recent_events", [])
                if isinstance(recent, list):
                    result["recent_events"] = [
                        {
                            key: event[key]
                            for key in ("created", "state", "title", "message", "track_id")
                            if key in event
                        }
                        for event in recent[:5]
                        if isinstance(event, dict)
                    ]
            except (OSError, ValueError, TypeError, KeyError):
                pass
        return result

    @app.get("/api/preview.jpg")
    def preview():
        if not read_vision(settings.storage.directory)["monitoring"]:
            raise HTTPException(503, "Camera frame unavailable or stale")
        try:
            path = settings.storage.directory / "vision-preview.jpg"
            with path.open("rb") as stream:
                if not 0 <= time.time() - path.stat().st_mtime <= 15:
                    raise ValueError("Stale preview")
                content = stream.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024 or not content.startswith(b"\xff\xd8"):
                raise ValueError("Invalid preview")
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Preview unavailable") from exc
        return Response(content, media_type="image/jpeg")

    return app
