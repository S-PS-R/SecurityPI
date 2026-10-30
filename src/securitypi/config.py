"""Validate non-secret TOML settings without creating files or touching hardware."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class ConfigError(ValueError):
    """Configuration error safe to display without including supplied values."""


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ServerSettings(SettingsModel):
    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535, strict=True)


class CameraSettings(SettingsModel):
    source: Literal["synthetic", "usb", "video"] = "synthetic"
    video_path: Path | None = None
    backend: Literal["auto", "dshow", "msmf", "v4l2", "ffmpeg"] = "auto"
    fourcc: str | None = Field(default=None, pattern=r"^[A-Za-z0-9 ]{4}$")
    io_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60, strict=True, allow_inf_nan=False)
    reconnect_attempts: int = Field(default=2, ge=0, le=10, strict=True)
    reconnect_delay_seconds: float = Field(
        default=1.0, ge=0, le=10, strict=True, allow_inf_nan=False
    )
    rotate_180: bool = Field(default=False, strict=True)
    device_index: int = Field(default=0, ge=0, strict=True)
    width: int = Field(default=640, ge=1, le=4096, strict=True)
    height: int = Field(default=480, ge=1, le=4096, strict=True)
    fps: int = Field(default=10, ge=1, le=60, strict=True)

    @field_validator("video_path", mode="before")
    @classmethod
    def nonempty_video_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("video_path must not be empty")
        return value

    @model_validator(mode="after")
    def validate_file_source(self):
        if self.source == "video" and self.video_path is None:
            raise ValueError("video source requires video_path")
        if self.source != "video" and self.video_path is not None:
            raise ValueError("video_path is only used by video sources")
        return self


class StorageSettings(SettingsModel):
    directory: Path = Path("../data")
    retention_days: int = Field(default=7, ge=1, le=365, strict=True)
    max_gb: float = Field(default=5.0, gt=0, le=10000, strict=True, allow_inf_nan=False)

    @field_validator("directory", mode="before")
    @classmethod
    def nonempty_directory(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("directory must not be empty")
        return value


class HomeAssistantSettings(SettingsModel):
    url: AnyHttpUrl = AnyHttpUrl("http://homeassistant.local:8123")
    token_env: str = Field(default="SECURITYPI_HA_TOKEN", pattern=r"^[A-Z][A-Z0-9_]*$")
    notifications_enabled: bool = Field(default=False, strict=True)
    notify_service: str | None = Field(default=None, pattern=r"^mobile_app_[a-z0-9_]{1,80}$")
    person_seconds: float = Field(default=10, ge=0, le=3600, allow_inf_nan=False)
    expiry_seconds: float = Field(default=120, ge=30, le=600, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_phone(self):
        if self.notifications_enabled and self.notify_service is None:
            raise ValueError("Enabled notifications require a mobile_app notify service")
        return self

    @field_validator("url")
    @classmethod
    def no_inline_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("URL must not contain credentials, query, or fragment")
        if value.path not in (None, "/"):
            raise ValueError("URL must refer to the Home Assistant origin")
        return value


class VisionSettings(SettingsModel):
    backend: Literal["opencv", "onnxruntime"] = "opencv"
    model: Path | None = None
    threads: int = Field(default=1, ge=1, le=4, strict=True)
    analysis_fps: float = Field(default=2.0, ge=0.2, le=10, strict=True, allow_inf_nan=False)
    preview_fps: float = Field(default=1.0, ge=0.2, le=10, strict=True, allow_inf_nan=False)
    confidence: float = Field(default=0.15, ge=0.1, le=0.9, strict=True, allow_inf_nan=False)
    lost_seconds: float = Field(default=3.0, ge=0.5, le=10, strict=True, allow_inf_nan=False)
    calibration_seconds: float = Field(
        default=300.0, ge=30, le=3600, strict=True, allow_inf_nan=False
    )


class SnapshotSettings(SettingsModel):
    enabled: bool = Field(default=False, strict=True)
    max_mib: int = Field(default=500, ge=1, le=4096, strict=True)
    max_images: int = Field(default=10000, ge=3, le=100000, strict=True)


class DatasetSettings(SettingsModel):
    enabled: bool = Field(default=False, strict=True)
    interval_hours: float = Field(default=2.0, ge=0.5, le=24, allow_inf_nan=False)
    duration_hours: float = Field(default=24.0, ge=1, le=744, allow_inf_nan=False)
    max_images: int = Field(default=12, ge=1, le=1000, strict=True)
    max_mib: int = Field(default=100, ge=1, le=1024, strict=True)


class ActivitySettings(SettingsModel):
    stationary_seconds: float = Field(default=5.0, ge=2, le=60, allow_inf_nan=False)
    parked_seconds: float = Field(default=60.0, ge=10, le=3600, allow_inf_nan=False)
    road_linger_seconds: float = Field(default=30.0, ge=5, le=3600, allow_inf_nan=False)
    road_polygon: list[tuple[float, float]] = Field(default_factory=list, max_length=12)

    @field_validator("road_polygon")
    @classmethod
    def valid_polygon(cls, points):
        if points and (len(points) < 3 or len(set(points)) != len(points)):
            raise ValueError("Use at least three distinct road outline points")
        if any(not 0 <= value <= 1 for point in points for value in point):
            raise ValueError("Road outline coordinates must be between zero and one")
        if points:
            area = sum(
                x * points[(i + 1) % len(points)][1] - y * points[(i + 1) % len(points)][0]
                for i, (x, y) in enumerate(points)
            )
            if abs(area) < 0.001:
                raise ValueError("Road outline must enclose an area")
        return points


class Settings(SettingsModel):
    name: str = Field(default="SecurityPI", min_length=1, max_length=80)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    server: ServerSettings = Field(default_factory=ServerSettings)
    camera: CameraSettings = Field(default_factory=CameraSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    home_assistant: HomeAssistantSettings = Field(default_factory=HomeAssistantSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    snapshots: SnapshotSettings = Field(default_factory=SnapshotSettings)
    dataset: DatasetSettings = Field(default_factory=DatasetSettings)
    activity: ActivitySettings = Field(default_factory=ActivitySettings)


def load_settings(path: Path) -> Settings:
    """Resolve storage relative to config, not the process's working directory."""
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError("Cannot read configuration: check the file and TOML syntax.") from exc
    try:
        settings = Settings.model_validate(raw)
    except ValidationError as exc:
        # Do not print ValidationError's raw input values (they may include secrets).
        locations = ", ".join(
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors(include_input=False, include_context=False)
        )
        raise ConfigError(f"Invalid configuration field(s): {locations}.") from exc
    directory = settings.storage.directory.expanduser()
    if not directory.is_absolute():
        directory = path.resolve().parent / directory
    settings.storage.directory = directory.resolve()
    if settings.vision.model is not None:
        model = settings.vision.model.expanduser()
        if not model.is_absolute():
            model = path.resolve().parent / model
        settings.vision.model = model.resolve()
    if settings.camera.video_path is not None:
        video = settings.camera.video_path.expanduser()
        if not video.is_absolute():
            video = path.resolve().parent / video
        settings.camera.video_path = video.resolve()
    return settings
