"""Validate non-secret TOML settings without creating files or touching hardware."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator


class ConfigError(ValueError):
    """Configuration error safe to display without including supplied values."""


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ServerSettings(SettingsModel):
    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535, strict=True)


class CameraSettings(SettingsModel):
    source: Literal["synthetic", "usb"] = "synthetic"
    device_index: int = Field(default=0, ge=0, strict=True)
    width: int = Field(default=640, ge=1, le=4096, strict=True)
    height: int = Field(default=480, ge=1, le=4096, strict=True)
    fps: int = Field(default=10, ge=1, le=60, strict=True)


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

    @field_validator("url")
    @classmethod
    def no_inline_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("URL must not contain credentials, query, or fragment")
        if value.path not in (None, "/"):
            raise ValueError("URL must refer to the Home Assistant origin")
        return value


class Settings(SettingsModel):
    name: str = Field(default="SecurityPI", min_length=1, max_length=80)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    server: ServerSettings = Field(default_factory=ServerSettings)
    camera: CameraSettings = Field(default_factory=CameraSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    home_assistant: HomeAssistantSettings = Field(default_factory=HomeAssistantSettings)


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
    return settings
