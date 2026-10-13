import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from securitypi.api import create_app
from securitypi.config import ConfigError, Settings, load_settings
from securitypi.logging import JsonFormatter


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_relative_storage_is_independent_of_cwd(tmp_path, monkeypatch):
    config = write_config(tmp_path, '[storage]\ndirectory = "evidence"\n')
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    settings = load_settings(config)
    assert settings.storage.directory == tmp_path / "evidence"
    assert not settings.storage.directory.exists()


@pytest.mark.parametrize(
    "content,field",
    [
        ('[server]\nhost = "0.0.0.0"', "server.host"),
        ("[server]\nport = 70000", "server.port"),
        ("[camera]\nfps = true", "camera.fps"),
        ('[camera]\nsource = "typo"', "camera.source"),
        ("[storage]\nmax_gb = nan", "storage.max_gb"),
        ('[storage]\ndirectory = ""', "storage.directory"),
        ('[home_assistant]\ntoken = "SENSITIVE_VALUE"', "home_assistant.token"),
        ('[home_assistant]\nurl = "http://user:SENSITIVE_VALUE@localhost"', "home_assistant.url"),
    ],
)
def test_rejects_invalid_settings_without_echoing_values(tmp_path, content, field):
    with pytest.raises(ConfigError) as caught:
        load_settings(write_config(tmp_path, content))
    assert field in str(caught.value)
    assert "SENSITIVE_VALUE" not in str(caught.value)


@pytest.mark.parametrize("content", ["[broken", 'name = "one"\nname = "two"'])
def test_malformed_toml_is_actionable(tmp_path, content):
    with pytest.raises(ConfigError, match="TOML syntax"):
        load_settings(write_config(tmp_path, content))


def test_missing_file_is_actionable(tmp_path):
    with pytest.raises(ConfigError, match="Cannot read configuration"):
        load_settings(tmp_path / "missing.toml")


def test_health_does_not_claim_camera_readiness_or_leak_settings():
    async def check():
        transport = httpx.ASGITransport(app=create_app(Settings()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health")
            assert health.json()["status"] == "ok"
            response = await client.get("/api/status")
            state = response.json()
            assert state["monitoring"] is False
            assert state["parking"] == "unknown"
            assert state["home_assistant"] == "not_connected"
            assert "token_env" not in response.text
            assert (await client.get("/api/unknown")).status_code == 404

    asyncio.run(check())


def test_cli_valid_and_invalid_config_exit_codes(tmp_path):
    valid = write_config(tmp_path, 'name = "SecurityPI"')
    result = subprocess.run(
        [sys.executable, "-m", "securitypi", "check-config", "--config", str(valid)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    entry = json.loads(result.stderr)
    assert entry["level"] == "INFO"
    invalid = write_config(tmp_path, '[home_assistant]\ntoken = "SENSITIVE_VALUE"')
    result = subprocess.run(
        [sys.executable, "-m", "securitypi", "check-config", "--config", str(invalid)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "home_assistant.token" in result.stderr
    assert "SENSITIVE_VALUE" not in result.stderr
    assert "Traceback" not in result.stderr


def test_logs_are_json_with_escaped_multiline_messages():
    record = logging.LogRecord("securitypi", logging.INFO, "", 0, "first\nsecond", (), None)
    output = JsonFormatter().format(record)
    assert len(output.splitlines()) == 1
    assert json.loads(output)["message"] == "first\nsecond"
