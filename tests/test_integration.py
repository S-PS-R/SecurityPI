import asyncio
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from securitypi.api import create_app
from securitypi.config import HomeAssistantSettings, Settings
from securitypi.notifications import NotificationQueue, send_notification
from securitypi.soak import limit_reason
from securitypi.state import read_vision, write_json


def live_state(now=None, person=1):
    return {
        "monitoring": True,
        "state": "analyzing",
        "run_id": "test-run",
        "captured_at": (now or datetime.now(UTC)).isoformat(),
        "frames_analyzed": 50,
        "people_visible": 1,
        "tracks": [{"id": person, "class_id": 0, "elapsed_seconds": 20, "observed_seconds": 12}],
        "parking": {"availability": "free", "available_spaces": 3},
    }


@pytest.mark.parametrize("age", [16, -1])
def test_stale_and_future_status_never_reports_zero_or_available(tmp_path, age):
    now = datetime.now(UTC)
    write_json(tmp_path / "vision-status.json", live_state(now - timedelta(seconds=age)))
    state = read_vision(tmp_path, now=now)
    assert not state["monitoring"]
    assert state["people_visible"] is None
    assert not state["tracks"]
    assert state["parking"]["available_spaces"] is None


@pytest.mark.parametrize("content", ["{broken", "x" * 131073, '{"monitoring":true}'])
def test_broken_status_is_unavailable(tmp_path, content):
    (tmp_path / "vision-status.json").write_text(content)
    assert read_vision(tmp_path)["state"] == "unavailable"


def test_api_reads_live_state_and_refuses_stale_preview(tmp_path):
    async def check():
        settings = Settings(storage={"directory": tmp_path})
        transport = httpx.ASGITransport(app=create_app(settings))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            write_json(tmp_path / "vision-status.json", live_state())
            (tmp_path / "vision-preview.jpg").write_bytes(b"\xff\xd8test")
            value = (await client.get("/api/vision")).json()
            assert value["people_visible"] == 1
            assert value["longest_observed_seconds"] == 12
            assert value["parking"]["availability"] == "unknown"
            response = await client.get("/api/preview.jpg")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            os.utime(tmp_path / "vision-preview.jpg", (1, 1))
            assert (await client.get("/api/preview.jpg")).status_code == 503
            stopped = live_state()
            stopped.update(monitoring=False, state="stopped")
            write_json(tmp_path / "vision-status.json", stopped)
            assert (await client.get("/api/preview.jpg")).status_code == 503
            assert (await client.get("/api/status")).json()["monitoring"] is False

    asyncio.run(check())


def test_notification_status_defaults_disabled_and_hides_secrets(tmp_path):
    async def check():
        app = create_app(Settings(storage={"directory": tmp_path}))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/notifications")
            assert response.json() == {
                "enabled": False,
                "worker_running": False,
                "phone_receipt": "unverified",
                "events": {},
                "recent_events": [],
                "rules": {
                    "person_seconds": 10,
                    "road_linger_seconds": 30,
                    "person_alert_mode": "per_track",
                },
            }
            assert "token" not in response.text

    asyncio.run(check())


def test_queue_per_track_deduplication_and_restart(tmp_path):
    path = tmp_path / "outbox.db"
    config = HomeAssistantSettings()
    calls = []

    def sender(payload):
        calls.append(payload)
        return "accepted"

    queue = NotificationQueue(path, config)
    assert queue.tick(live_state(), 1000, sender) == {"accepted": 1}
    queue.close()
    queue = NotificationQueue(path, config)
    assert queue.tick(live_state(), 1400, sender) == {"accepted": 1}
    queue.tick(live_state(person=2), 1401, sender)
    queue.tick(live_state(person=3), 1402, sender)
    assert len(calls) == 3
    assert "test-run:1" in calls[0]["data"]["tag"]
    assert calls[0]["data"]["url"] == "/securitypi-dashboard/overview"
    queue.close()


def test_retry_expiry_and_stale_cancellation(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings())
    calls = []

    def sender(payload):
        calls.append(payload)
        return "retry"

    assert queue.tick(live_state(), 1000, sender) == {"pending": 1}
    queue.tick(live_state(), 1005, sender)
    assert len(calls) == 1
    queue.tick(live_state(), 1010, sender)
    assert len(calls) == 2
    assert queue.tick(live_state(), 1120, sender) == {"expired": 1}
    queue.tick(live_state(person=2), 1400, sender)
    assert queue.tick({"monitoring": False}, 1401, sender)["cancelled"] == 1
    assert len(calls) == 3
    queue.close()


def test_dry_run_does_not_send_and_queue_stays_bounded(tmp_path):
    queue = NotificationQueue(tmp_path / "dry.db", HomeAssistantSettings())

    def forbidden(_payload):
        pytest.fail("Dry run contacted the network")

    for i in range(150):
        stats = queue.tick(live_state(person=i), 1000 + i * 301, forbidden, dry_run=True)
    assert stats == {"simulated": 100}
    assert (tmp_path / "dry.db").stat().st_size < 1048576
    queue.close()


def test_camera_run_change_cancels_queued_event(tmp_path):
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings())
    queue.tick(live_state(), 1000, lambda _: "retry")
    changed = live_state()
    changed["run_id"] = "new-run"
    sent = []
    assert queue.tick(changed, 1010, lambda payload: sent.append(payload) or "accepted") == {
        "cancelled": 1,
        "accepted": 1,
    }
    assert len(sent) == 1 and "new-run" in sent[0]["data"]["tag"]
    queue.close()


@pytest.mark.parametrize(
    "code,outcome",
    [(200, "accepted"), (401, "rejected"), (429, "retry"), (503, "retry"), (302, "rejected")],
)
def test_home_assistant_http_contract_without_real_notifications(monkeypatch, code, outcome):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    self.headers["Authorization"],
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(code)
            if code == 302:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = HomeAssistantSettings(
            url=f"http://127.0.0.1:{server.server_port}", notify_service="mobile_app_test"
        )
        monkeypatch.setenv(config.token_env, "fake-test-token")
        payload = {"message": "Local mock only", "data": {"tag": "test"}}
        assert send_notification(config, payload) == outcome
        assert received == [
            ("/api/services/notify/mobile_app_test", "Bearer fake-test-token", payload)
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("rss_mib", 651, "process_memory_limit"),
        ("available_memory_mib", 100, "host_memory_limit"),
        ("free_disk_mib", 100, "disk_limit"),
        ("temperature_c", 80, "temperature_limit"),
    ],
)
def test_soak_stops_at_resource_limits(field, value, reason):
    sample = {
        "rss_mib": 300,
        "available_memory_mib": 1000,
        "free_disk_mib": 1000,
        "temperature_c": 55,
    }
    assert limit_reason(sample) is None
    sample[field] = value
    assert limit_reason(sample) == reason


def test_numeric_history_fields_are_unknown_offline_and_count_vehicle_classes(tmp_path):
    now = datetime.now(UTC)
    raw = live_state(now)
    raw.update(analysis_fps=3.5, capture_fps=30.0, inference_ms=250)
    raw["tracks"] += [
        {
            "id": cls,
            "class_id": cls,
            "elapsed_seconds": 10,
            "observed_seconds": 10,
            "motion": "stationary" if cls in (2, 3) else "moving",
        }
        for cls in (2, 3, 5, 7)
    ]
    write_json(tmp_path / "vision-status.json", raw)
    state = read_vision(tmp_path, now=now)
    assert state["vehicles_visible"] == 4
    assert state["vehicles_stationary"] == 2
    assert state["analysis_fps"] == 3.5
    state = read_vision(tmp_path, now=now + timedelta(seconds=16))
    assert all(
        state[key] is None
        for key in (
            "vehicles_visible",
            "vehicles_stationary",
            "analysis_fps",
            "capture_fps",
            "inference_ms",
        )
    )


def test_storage_reports_database_and_journal_without_scanning_samples(tmp_path):
    async def check():
        directory = tmp_path / "home-assistant"
        directory.mkdir()
        (directory / "home-assistant_v2.db").write_bytes(b"x" * 1048576)
        (directory / "home-assistant_v2.db-wal").write_bytes(b"x" * 524288)
        (tmp_path / "tracks.sqlite3").write_bytes(b"x" * 1048576)
        app = create_app(Settings(storage={"directory": tmp_path}))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            value = (await client.get("/api/storage")).json()
            assert value["history_mib"] == 1.5
            assert value["tracks_mib"] == 1.0
            assert value["disk_free_gib"] > 0

    asyncio.run(check())


def test_raw_detection_counts_do_not_wait_for_tracks_and_clear_when_detections_leave(tmp_path):
    now = datetime.now(UTC)
    raw = live_state(now)
    raw["tracks"] = []
    raw["detections"] = [
        {"class_id": cls, "label": label, "confidence": 0.2, "box": [0.1, 0.1, 0.2, 0.2]}
        for cls, label in ((0, "person"), (2, "car"), (3, "motorcycle"), (9, "traffic light"))
    ]
    write_json(tmp_path / "vision-status.json", raw)
    state = read_vision(tmp_path, now=now)
    assert state["people_visible"] == 1
    assert state["vehicles_visible"] == 2
    assert state["objects_visible"] == 4
    assert len(state["detections"]) == 4
    assert state["tracks"] == []
    raw["detections"] = []
    raw["tracks"] = live_state(now)["tracks"]
    write_json(tmp_path / "vision-status.json", raw)
    state = read_vision(tmp_path, now=now)
    assert state["people_visible"] == state["vehicles_visible"] == state["objects_visible"] == 0
