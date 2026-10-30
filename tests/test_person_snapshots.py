from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from securitypi.capture import Frame
from securitypi.config import HomeAssistantSettings, SnapshotSettings
from securitypi.notifications import NotificationQueue
from securitypi.snapshots import PersonSnapshots, cleanup, inventory, snapshot_directory
from securitypi.tracking import PersonArrivals, Tracker
from securitypi.vision import Detection, decode


def test_variable_fps_counts_observation_but_not_missing_intervals():
    tracker = Tracker(fps=5)
    person = Detection(0, 0.9, (0.1, 0.1, 0.2, 0.4))
    for now in (0, 0.4, 0.8, 1.2):
        track = tracker.update([person], now)[0]
    assert track.observed_seconds == pytest.approx(1.2)
    tracker.update([], 1.6)
    track = tracker.update([person], 2)[0]
    assert track.observed_seconds == pytest.approx(1.2)
    track = tracker.update([person], 2.4)[0]
    assert track.observed_seconds == pytest.approx(1.6)


def test_qualified_departed_person_survives_polling_and_deduplicates(tmp_path):
    cache = PersonArrivals(10)
    queue = NotificationQueue(tmp_path / "outbox.db", HomeAssistantSettings())
    sent = []
    person = SimpleNamespace(id=1, class_id=0, observed_seconds=9.99)
    records, new = cache.update([person], datetime.fromtimestamp(1000, UTC))
    assert not records and not new
    person.observed_seconds = 10
    records, new = cache.update([person], datetime.fromtimestamp(1001, UTC))
    assert new
    records, _ = cache.update([], datetime.fromtimestamp(1002, UTC))
    state = dict(monitoring=True, run_id="abc", tracks=[], person_arrivals=records)
    queue.tick(state, 1002, lambda payload: sent.append(payload) or "accepted")
    queue.tick(state, 1003, lambda payload: sent.append(payload) or "accepted")
    assert len(sent) == 1
    assert sent[0]["title"] == "SecurityPI"
    assert sent[0]["message"] == "Person detected."
    queue.close()


def test_snapshots_have_three_thresholds_and_unique_runs(tmp_path):
    config = SnapshotSettings(enabled=True)
    stamp = datetime.now(UTC)
    frame = Frame(np.zeros((80, 100, 3), np.uint8), 1, stamp, 1)
    person = SimpleNamespace(id=1, class_id=0, observed_seconds=0)
    for _ in range(2):
        writer = PersonSnapshots(tmp_path, config, uuid4().hex)
        for seconds in (4, 5, 5.1, 10, 10.1, 20, 21):
            person.observed_seconds = seconds
            writer.update(
                replace(
                    frame, captured_at=stamp + timedelta(seconds=seconds), monotonic_seconds=seconds
                ),
                [person],
            )
            writer.queue.join()
        writer.close()
        assert writer.written == 3 and writer.errors == 0
    assert len(inventory(tmp_path)) == 6
    assert all(path.stat().st_mode & 0o077 == 0 for _, path, _ in inventory(tmp_path))


def test_skipped_thresholds_use_one_image_and_queue_never_blocks(tmp_path):
    writer = PersonSnapshots(tmp_path, SnapshotSettings(), uuid4().hex)
    writer.worker = SimpleNamespace()  # Deliberately no consuming thread.
    frame = Frame(np.zeros((10, 10, 3), np.uint8), 1, datetime.now(UTC), 30)
    people = [SimpleNamespace(id=i, class_id=0, observed_seconds=30) for i in range(5)]
    writer.update(frame, people)
    assert writer.queue.qsize() == 2
    assert writer.dropped == 3
    writer.update(frame, people)
    assert writer.queue.qsize() == 2 and writer.dropped == 3


def test_cleanup_age_size_count_and_training_preservation(tmp_path):
    config = SnapshotSettings(max_mib=1, max_images=3)
    directory = snapshot_directory(tmp_path)
    directory.mkdir(parents=True)
    stamp = datetime.now(UTC)
    for days in (8, 6, 5, 4, 3):
        name = (stamp - timedelta(days=days)).strftime("%Y%m%dT%H%M%S%fZ")
        (directory / f"{name}-{uuid4().hex}-1-5.jpg").write_bytes(b"x" * 400000)
    training = tmp_path / "training" / "private.jpg"
    training.parent.mkdir()
    training.write_bytes(b"training")
    unrelated = directory / "keep.jpg"
    unrelated.write_bytes(b"private")
    result = cleanup(tmp_path, config, stamp.timestamp())
    assert result["snapshot_count"] == 2
    assert result["snapshot_mib"] < 1
    assert training.exists() and unrelated.exists()
    # Capture timestamps, not mutable mtimes, drive expiry.
    assert cleanup(tmp_path, config, (stamp + timedelta(days=8)).timestamp())["snapshot_count"] == 0


def test_snapshot_write_failure_is_nonfatal(tmp_path, monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "imencode", lambda *args: (False, None))
    writer = PersonSnapshots(tmp_path, SnapshotSettings(enabled=True), uuid4().hex)
    frame = Frame(np.zeros((10, 10, 3), np.uint8), 1, datetime.now(UTC), 5)
    writer.update(frame, [SimpleNamespace(id=1, class_id=0, observed_seconds=5)])
    writer.queue.join()
    writer.close()
    assert writer.errors == 1 and not inventory(tmp_path)


def test_only_people_and_all_road_vehicles_are_decoded():
    rows = [[10, 10, 50, 50, 0.9, cls] for cls in (0, 2, 3, 5, 7, 9, 15, 79)]
    assert {d.class_id for d in decode(np.array([rows]), (100, 100, 3), 100)} == {0, 2, 3, 5, 7}


def test_unavailable_snapshot_storage_does_not_stop_analysis(tmp_path):
    directory = snapshot_directory(tmp_path)
    directory.parent.mkdir(parents=True)
    directory.write_text("not a directory")
    writer = PersonSnapshots(tmp_path, SnapshotSettings(enabled=True), uuid4().hex)
    assert writer.worker is None and writer.errors == 1
    writer.close()


def test_cleanup_does_not_follow_symlinks_or_invalid_dates(tmp_path):
    directory = snapshot_directory(tmp_path)
    directory.mkdir(parents=True)
    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"private")
    name = "20200101T000000000000Z-" + uuid4().hex + "-1-5.jpg"
    (directory / name).symlink_to(outside)
    invalid = directory / ("20209999T000000000000Z-" + uuid4().hex + "-1-5.jpg")
    invalid.write_bytes(b"invalid")
    assert cleanup(tmp_path, SnapshotSettings())["snapshot_count"] == 0
    assert outside.exists() and invalid.exists()


def test_cleanup_removes_only_stale_owned_temporary_writes(tmp_path):
    import os

    directory = snapshot_directory(tmp_path)
    directory.mkdir(parents=True)
    stamp = datetime.now(UTC)
    name = stamp.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex + "-1-5.jpg.tmp"
    stale = directory / name
    stale.write_bytes(b"incomplete")
    os.utime(stale, (stamp.timestamp() - 7200, stamp.timestamp() - 7200))
    fresh = directory / name.replace("-1-5.", "-2-5.")
    fresh.write_bytes(b"writing")
    unrelated = directory / "private.jpg.tmp"
    unrelated.write_bytes(b"keep")
    cleanup(tmp_path, SnapshotSettings(), stamp.timestamp())
    assert not stale.exists() and fresh.exists() and unrelated.exists()
