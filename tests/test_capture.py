"""Real codec checks plus isolated worker failures; no webcam required in CI."""

import json
import time
from argparse import Namespace

import cv2
import numpy as np
import pytest

from securitypi.capture import CaptureError, NativeSource, SyntheticSource, create_source
from securitypi.capture_cli import run_capture
from securitypi.config import CameraSettings, ConfigError, Settings, load_settings


def _blocked_open_worker(connection, config):
    time.sleep(60)


def _blocked_read_worker(connection, config):
    connection.send(("opened", {"backend": "test"}))
    connection.recv()
    time.sleep(60)


def _disconnect_worker(connection, config):
    from datetime import UTC, datetime

    connection.send(("opened", {"backend": "test"}))
    connection.recv()
    connection.send(
        ("frame", (np.zeros((8, 8, 3), np.uint8), datetime.now(UTC), time.monotonic(), None))
    )
    if connection.recv() == "read":
        connection.send(("error", "Simulated disconnect."))
    connection.close()


def test_synthetic_frames_are_independent_timestamped_and_closeable():
    with create_source(CameraSettings(width=64, height=48)) as source:
        first = source.read()
        before = first.image.copy()
        second = source.read()
        assert first.image.shape == (48, 64, 3)
        assert first.image.dtype == np.uint8
        assert first.captured_at.utcoffset().total_seconds() == 0
        assert second.monotonic_seconds >= first.monotonic_seconds
        assert second.sequence == first.sequence + 1
        assert np.array_equal(first.image, before)
        assert not np.array_equal(first.image, second.image)
    with pytest.raises(CaptureError, match="closed"):
        source.read()
    source.close()  # Idempotent shutdown.


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    assert writer.isOpened(), "Generated-video codec must work on supported CI targets"
    try:
        source = SyntheticSource(CameraSettings(width=64, height=48))
        for _ in range(3):
            writer.write(source.read().image)
    finally:
        writer.release()
    return path


def test_real_video_decode_eof_and_process_cleanup(video_file):
    source = NativeSource(CameraSettings(source="video", video_path=video_file))
    with source:
        frames = [source.read() for _ in range(3)]
        assert all(frame.image.shape == (48, 64, 3) for frame in frames)
        assert [frame.sequence for frame in frames] == [1, 2, 3]
        assert source.read() is None
        assert source.read() is None  # Do not reopen/loop at EOF.
        assert source.process is None
    assert source.connection is None


def test_failed_native_open_has_finite_retry_budget_and_no_worker_leak():
    settings = CameraSettings(
        source="usb", io_timeout_seconds=0.2, reconnect_attempts=1, reconnect_delay_seconds=0
    )
    started = time.monotonic()
    with NativeSource(settings, worker_target=_blocked_open_worker) as source:
        with pytest.raises(CaptureError, match="timed out"):
            source.read()
        assert source.reconnects == 1
        assert source.process is None
        assert source.connection is None
    assert time.monotonic() - started < 8


def test_blocked_read_is_terminated_instead_of_hanging():
    settings = CameraSettings(source="usb", io_timeout_seconds=3, reconnect_attempts=0)
    started = time.monotonic()
    with NativeSource(settings, worker_target=_blocked_read_worker) as source:
        with pytest.raises(CaptureError, match="timed out"):
            source.read()
        assert source.info["backend"] == "test"  # Open completed; read itself stalled.
        assert source.process is None
    assert time.monotonic() - started < 10


def test_disconnect_reopens_with_continuous_sequence_and_new_frames():
    settings = CameraSettings(source="usb", reconnect_delay_seconds=0)
    with NativeSource(settings, worker_target=_disconnect_worker) as source:
        first = source.read()
        second = source.read()
        assert (first.sequence, second.sequence) == (1, 2)
        assert source.reconnects == 1
        assert second.monotonic_seconds >= first.monotonic_seconds
    assert source.process is None


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_corrupt_video_fails_without_usb_retry(tmp_path, exists):
    path = tmp_path / "bad.avi"
    if exists:
        path.write_bytes(b"not a video")
    with NativeSource(CameraSettings(source="video", video_path=path)) as source:
        with pytest.raises(CaptureError):
            source.read()
        assert source.reconnects == 0
        assert source.process is None


def test_video_path_resolves_relative_to_config_and_requires_path(tmp_path):
    path = tmp_path / "camera.toml"
    path.write_text('[camera]\nsource="video"\nvideo_path="sample.avi"', encoding="utf-8")
    assert load_settings(path).camera.video_path == tmp_path / "sample.avi"
    path.write_text('[camera]\nsource="video"', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_capture_cli_snapshot_report_and_eof_are_real(video_file, tmp_path, capsys):
    settings = Settings(camera=CameraSettings(source="video", video_path=video_file))
    settings.storage.directory = tmp_path
    snapshot = tmp_path / "last.jpg"
    report = tmp_path / "result.json"
    args = Namespace(
        command="capture",
        source=None,
        device_index=None,
        backend=None,
        video=None,
        frames=10,
        snapshot=snapshot,
        report=report,
    )
    assert run_capture(settings, args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["frames"] == 3
    assert result["reason"] == "end_of_file"
    assert result["monitoring"] is False
    assert json.loads(report.read_text()) == result
    assert cv2.imdecode(np.frombuffer(snapshot.read_bytes(), np.uint8), cv2.IMREAD_COLOR).shape == (
        48,
        64,
        3,
    )


def test_capture_rejects_artifacts_outside_storage_before_opening(tmp_path):
    settings = Settings()
    settings.storage.directory = tmp_path / "evidence"
    args = Namespace(
        command="capture",
        source=None,
        device_index=None,
        backend=None,
        video=None,
        frames=1,
        snapshot=tmp_path / "outside.jpg",
        report=None,
    )
    with pytest.raises(CaptureError, match="inside"):
        run_capture(settings, args)
    assert not settings.storage.directory.exists()


def test_interrupted_capture_releases_source_and_reports_partial_result(
    tmp_path, monkeypatch, capsys
):
    import securitypi.capture_cli as module

    class InterruptedSource(SyntheticSource):
        def read(self):
            if self.sequence == 1:
                raise KeyboardInterrupt
            return super().read()

    source = InterruptedSource(CameraSettings(width=64, height=48))
    monkeypatch.setattr(module, "create_source", lambda config: source)
    settings = Settings()
    settings.storage.directory = tmp_path
    args = Namespace(
        command="capture",
        source=None,
        device_index=None,
        backend=None,
        video=None,
        frames=0,
        snapshot=None,
        report=None,
    )
    assert run_capture(settings, args) == 130
    assert source.closed
    assert json.loads(capsys.readouterr().out)["reason"] == "interrupted"
