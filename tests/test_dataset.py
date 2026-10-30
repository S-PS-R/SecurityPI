"""Sparse collection must not restart its clock, draw training boxes or erase reviews."""

import json
from datetime import UTC, datetime, timedelta

import cv2
import numpy as np

from securitypi.capture import Frame
from securitypi.config import DatasetSettings
from securitypi.dataset import DatasetCollector


def frame(now):
    return Frame(np.zeros((60, 80, 3), np.uint8), 1, now, 0)


def test_two_hour_collection_survives_restart_and_keeps_raw_image(tmp_path):
    now = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    config = DatasetSettings(enabled=True)
    collector = DatasetCollector(tmp_path, config)
    proposal = {"class_id": 2, "label": "car", "confidence": 0.8, "box": [0.1, 0.2, 0.5, 0.6]}
    collector.update(frame(now), [proposal], "model.onnx")
    collector.update(frame(now + timedelta(hours=1)), [], "model.onnx")
    collector = DatasetCollector(tmp_path, config)
    collector.update(frame(now + timedelta(hours=1, minutes=59)), [], "model.onnx")
    directory = tmp_path / "training"
    assert len(list(directory.glob("*.jpg"))) == 1
    manifest = json.loads((directory / "20261028T000000Z.json").read_text())
    assert manifest["model_suggestions"] == [proposal]
    assert manifest["review"]["status"] == "pending"
    assert manifest["review"]["annotations"] == []
    image = cv2.imread(str(directory / "20261028T000000Z.jpg"))
    assert image.shape == (60, 80, 3) and not image.any()
    collector.update(frame(now + timedelta(hours=2)), [], "model.onnx")
    assert len(list(directory.glob("*.jpg"))) == 2
    assert "20261028T020000Z" in (directory / "review.md").read_text()


def test_collection_stops_at_count_cap_without_erasing_review(tmp_path):
    now = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    collector = DatasetCollector(tmp_path, DatasetSettings(enabled=True, max_images=1))
    collector.update(frame(now), [], "model.onnx")
    path = tmp_path / "training" / "20261028T000000Z.json"
    manifest = json.loads(path.read_text())
    manifest["review"]["notes"] = "Preserve manual work"
    path.write_text(json.dumps(manifest))
    collector.update(frame(now + timedelta(hours=2)), [], "model.onnx")
    assert len(list(path.parent.glob("*.jpg"))) == 1
    assert json.loads(path.read_text())["review"]["notes"] == "Preserve manual work"
    assert json.loads((path.parent / "collection.json").read_text())["state"] == "complete"


def test_collection_stops_at_byte_budget(tmp_path):
    directory = tmp_path / "training"
    directory.mkdir()
    (directory / "other-data.bin").write_bytes(b"x" * 1048576)
    collector = DatasetCollector(tmp_path, DatasetSettings(enabled=True, max_mib=1))
    collector.update(frame(datetime.now(UTC)), [], "model.onnx")
    assert not list(directory.glob("*.jpg"))
    assert collector.blocked


def test_disabled_collection_creates_nothing(tmp_path):
    collector = DatasetCollector(tmp_path, DatasetSettings())
    collector.update(frame(datetime.now(UTC)), [], "model.onnx")
    assert not list(tmp_path.iterdir())


def test_disk_error_is_bounded_and_does_not_stop_analysis(tmp_path, monkeypatch):
    collector = DatasetCollector(tmp_path, DatasetSettings(enabled=True))
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise OSError("disk unavailable")

    monkeypatch.setattr(collector, "_collect", fail)
    now = datetime.now(UTC)
    collector.update(frame(now), [], "model.onnx")
    collector.update(frame(now + timedelta(minutes=1)), [], "model.onnx")
    assert calls == [1]


def test_first_run_stops_at_twelve_and_never_restarts_itself(tmp_path):
    now = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    config = DatasetSettings(enabled=True)
    for i in range(14):
        # Exercise a fresh worker on every sample, including after completion.
        DatasetCollector(tmp_path, config).update(
            frame(now + timedelta(hours=i * 2)), [], "model.onnx"
        )
    directory = tmp_path / "training"
    assert len(list(directory.glob("*.jpg"))) == 12
    status = json.loads((directory / "collection.json").read_text())
    assert status["state"] == "complete" and status["reason"] == "image_limit"
    assert status["next_capture_at"] is None


def test_wall_clock_cutoff_stops_incomplete_run_after_camera_downtime(tmp_path):
    now = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    config = DatasetSettings(enabled=True)
    DatasetCollector(tmp_path, config).update(frame(now), [], "model.onnx")
    DatasetCollector(tmp_path, config).update(frame(now + timedelta(hours=25)), [], "model.onnx")
    directory = tmp_path / "training"
    assert len(list(directory.glob("*.jpg"))) == 1
    status = json.loads((directory / "collection.json").read_text())
    assert status["state"] == "complete" and status["reason"] == "duration_limit"
    DatasetCollector(tmp_path, config).update(frame(now + timedelta(days=3)), [], "model.onnx")
    assert len(list(directory.glob("*.jpg"))) == 1
