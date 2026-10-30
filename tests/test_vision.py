"""Deterministic vision/geometry tests; downloaded models and cameras are optional."""

import json
from argparse import Namespace
from pathlib import Path

import cv2
import numpy as np
import pytest

from securitypi.config import Settings, load_settings
from securitypi.models import fetch
from securitypi.scene import Calibration, SceneGuard, curb_candidates
from securitypi.tracking import Track, Tracker
from securitypi.vision import Detection, VisionError, decode, evaluate, input_blob
from securitypi.vision_cli import run_analysis, write_json


def detection(cls=0, box=(0.1, 0.1, 0.2, 0.4), score=0.9):
    return Detection(cls, score, box)


def test_yolov8_decoder_unpads_clips_and_suppresses_per_class():
    output = np.zeros((1, 84, 4), np.float32)
    output[0, :4, :] = np.array(
        [[100, 100, 100, 100], [100, 100, 100, 600], [80, 80, 80, 50], [100, 100, 100, 30]]
    )
    output[0, 4, 0:2] = [0.9, 0.8]
    output[0, 6, 2] = 0.7
    output[0, 4, 3] = 0.9  # Entirely inside padded image area: reject.
    result = decode(output, (360, 640, 3), 640)
    assert [r.class_id for r in result] == [0, 2]
    assert result[0].box == pytest.approx((60 / 640, 50 / 360, 140 / 640, 150 / 360))


def test_end_to_end_decoder_filters_classes_invalid_boxes_and_low_scores():
    result = decode(
        np.array(
            [
                [
                    [20, 40, 100, 200, 0.9, 0],
                    [10, 20, 5, 30, 0.8, 2],
                    [0, 0, 50, 50, 0.9, 99],
                    [0, 0, 20, 20, 0.01, 2],
                ]
            ]
        ),
        (720, 1280, 3),
        640,
    )
    assert len(result) == 1
    assert result[0].box == pytest.approx((40 / 1280, 80 / 720, 200 / 1280, 400 / 720))
    with pytest.raises(VisionError):
        decode(np.zeros((1, 7, 3)), (720, 1280, 3), 640)


def test_tracks_survive_short_occlusion_count_elapsed_and_expire():
    tracker = Tracker(fps=2, lost_seconds=2)
    first = tracker.update([detection()], 0)[0]
    second = tracker.update([detection()], 0.5)[0]
    assert first.id == second.id
    assert second.elapsed_seconds == 0.5
    assert second.observed_seconds == 0.5
    assert tracker.update([], 1) == []
    returned = tracker.update([detection()], 1.5)[0]
    assert returned.id == first.id
    assert returned.elapsed_seconds == 1.5
    tracker.update([], 5)
    replacement = tracker.update([detection()], 5.5)
    replacement += tracker.update([detection()], 6)
    assert replacement[-1].id != first.id


def test_tracking_keeps_classes_separate_and_history_bounded():
    tracker = Tracker(fps=2, lost_seconds=1)
    tracks = tracker.update([detection(), detection(2)], 0)
    assert {t.class_id for t in tracks} == {0, 2}
    for i in range(1, 100):
        tracker.update([detection(box=((i % 2) * 0.6, 0.1, (i % 2) * 0.6 + 0.1, 0.4))], i / 2)
    assert len(tracker.metadata) < 10
    assert all(len(t.removed_stracks) < 10 for t in tracker.trackers.values())


def parked(id, x, y=0.3, width=0.1):
    return Track(id, 2, (x, y, x + width, y + 0.08), 0.9, 60, 60, 60)


def test_rows_learn_separate_scales_and_gap_capacity_not_availability():
    cars = [
        parked(1, 0.1),
        parked(2, 0.3),
        parked(3, 0.7),
        parked(4, 0.1, 0.7, 0.15),
        parked(5, 0.4, 0.7, 0.15),
        parked(6, 0.7, 0.7, 0.15),
    ]
    rows = curb_candidates(cars)
    assert len(rows) == 2
    assert sorted(r["typical_car_span"] for r in rows) == pytest.approx([0.1, 0.15])
    assert all(r["availability"] == "unknown" for r in rows)
    gaps = [g for row in rows for g in row["gaps"]]
    assert any(g["estimated_car_capacity"] == 2 for g in gaps)
    assert all(g["availability"] == "unknown" and not g["visibility_verified"] for g in gaps)


def test_no_inferred_empty_parking_from_missing_partial_or_moving_cars():
    assert curb_candidates([]) == []
    pair = curb_candidates([parked(1, 0.1), parked(2, 0.5)])
    assert pair[0]["availability"] == "unknown"
    partial = Track(1, 2, (0, 0.3, 0.15, 0.4), 0.9, 60, 60, 60)
    assert not any(
        1 in row["vehicle_ids"]
        for row in curb_candidates([partial, parked(2, 0.4), parked(3, 0.7)])
    )
    moving = Track(1, 2, (0.1, 0.3, 0.2, 0.4), 0.9, 60, 60, 0)
    assert not any(
        1 in row["vehicle_ids"] for row in curb_candidates([moving, parked(2, 0.4), parked(3, 0.7)])
    )


def test_calibration_waits_then_invalidates_on_movement_and_low_visibility():
    calibration = Calibration(seconds=30)
    cars = [parked(1, 0.1), parked(2, 0.4), parked(3, 0.7)]
    calibration.update(cars, 0, "new")
    for now in range(1, 29):
        calibration.update(cars, now, "stable")
    assert calibration.update(cars, 29, "stable")["state"] == "learning"
    assert calibration.update(cars, 30, "stable")["state"] == "candidate_geometry"
    moved = calibration.update(cars, 31, "moved")
    assert moved["state"] == "learning" and moved["sections"] == []
    assert calibration.update(cars, 40, "unverifiable")["sections"] == []


def test_camera_motion_reset_uses_background_features():
    rng = np.random.default_rng(6)
    image = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
    guard = SceneGuard()
    assert guard.check(image) == "new"
    assert guard.check(image) == "stable"
    moved = cv2.warpAffine(image, np.float32([[1, 0, 18], [0, 1, 0]]), (320, 180))
    assert guard.check(moved) == "moved"
    assert guard.check(np.zeros_like(image)) == "unverifiable"


def test_model_paths_resolve_relative_to_configuration(tmp_path):
    path = tmp_path / "local.toml"
    path.write_text('[vision]\nmodel="weights.onnx"\n')
    assert load_settings(path).vision.model == tmp_path / "weights.onnx"


def test_fetch_rejects_existing_wrong_weights_without_network(tmp_path):
    (tmp_path / "yolo26n.onnx").write_bytes(b"wrong")
    with pytest.raises(VisionError, match="Existing model"):
        fetch("yolo26n", tmp_path)


def test_status_replaces_previous_contents_instead_of_appending(tmp_path):
    path = tmp_path / "status.json"
    write_json(path, {"tracks": list(range(100))})
    write_json(path, {"tracks": []})
    assert json.loads(path.read_text()) == {"tracks": []}
    assert not path.with_suffix(".json.tmp").exists()


def test_analysis_failure_marks_status_stopped_and_unknown(tmp_path, monkeypatch):
    import securitypi.vision_cli as module

    class BrokenDetector:
        def __init__(self, *args, **kwargs):
            pass

        def predict(self, image):
            raise VisionError("failed inference")

    monkeypatch.setattr(module, "Detector", BrokenDetector)
    settings = Settings()
    settings.vision.model = Path("dummy.onnx")
    settings.storage.directory = tmp_path
    with pytest.raises(VisionError):
        run_analysis(settings, Namespace(seconds=1, report=None, snapshot=None))
    status = json.loads((tmp_path / "vision-status.json").read_text())
    assert status["state"] == "stopped" and status["reason"] == "failed"
    assert not status["monitoring"]
    assert status["parking"]["availability"] == "unknown"


def test_labelled_evaluation_matches_once_and_penalizes_wrong_classes(tmp_path):
    label = tmp_path / "labels.txt"
    label.write_text("0 .15 .25 .1 .3\n2 .65 .25 .1 .3\n")
    result = evaluate(
        [detection(), detection(score=0.8), detection(2, (0.6, 0.1, 0.7, 0.4))], label
    )
    assert result == {"true_positive": 2, "false_positive": 1, "false_negative": 0}


def test_identity_expiry_uses_elapsed_time_even_with_slow_updates():
    tracker = Tracker(fps=10, lost_seconds=1)
    first = tracker.update([detection()], 0)[0]
    for now in (0.5, 1.0, 1.5):
        tracker.update([], now)
    returned = tracker.update([detection()], 2)
    returned += tracker.update([detection()], 2.1)
    assert returned[-1].id != first.id


def test_calibration_history_is_bounded_and_needs_repeated_observations():
    calibration = Calibration(seconds=30)
    cars = [parked(1, 0.1), parked(2, 0.5)]
    calibration.update(cars, 0, "new")
    early = calibration.update(cars, 100, "stable")
    assert early["state"] == "learning"
    for now in range(101, 400):
        result = calibration.update(cars, now, "stable")
    assert len(calibration.history) == 120
    assert result["state"] == "candidate_geometry"
    assert result["available_spaces"] is None


def test_green_boxes_are_raw_detections_without_track_ids_or_confirmation():
    from securitypi.vision_cli import annotate

    image = np.zeros((200, 300, 3), np.uint8)
    detections = [
        Detection(cls, 0.2, (x, 0.3, x + 0.1, 0.7))
        for cls, x in ((0, 0.1), (2, 0.3), (3, 0.5), (9, 0.7))
    ]
    preview = annotate(image, detections, "")
    for detection in detections:
        x = round(detection.box[0] * 300)
        assert tuple(preview[100, x]) == (0, 220, 0)
    assert not image.any()


def test_decoder_excludes_non_road_classes():
    result = decode(
        np.array([[[10, 10, 100, 100, 0.8, 9], [120, 10, 200, 100, 0.8, 79]]]), (640, 640, 3), 640
    )
    assert result == []


def test_analysis_publishes_unconfirmed_detections_and_skips_tracking_when_alerts_off(
    tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    import securitypi.tracking as tracking
    import securitypi.vision_cli as module
    from securitypi.capture import Frame

    class Detector:
        def __init__(self, *args, **kwargs):
            pass

        def predict(self, image):
            return [
                Detection(cls, 0.2, (x, 0.3, x + 0.1, 0.7))
                for cls, x in ((0, 0.1), (2, 0.3), (3, 0.5), (9, 0.7))
            ]

    class Source:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            if getattr(self, "done", False):
                return None
            self.done = True
            return Frame(
                np.zeros((200, 300, 3), np.uint8), 1, datetime.now(UTC), module.time.monotonic()
            )

    def unexpected_tracker(*args, **kwargs):
        pytest.fail("Tracking is reserved for enabled notifications")

    monkeypatch.setattr(module, "Detector", Detector)
    monkeypatch.setattr(module, "create_source", lambda _: Source())
    monkeypatch.setattr(tracking, "Tracker", unexpected_tracker)
    settings = Settings(vision={"model": "dummy.onnx"}, storage={"directory": tmp_path})
    assert run_analysis(settings, Namespace(seconds=0, report=None, snapshot=None)) == 0
    state = json.loads((tmp_path / "vision-status.json").read_text())
    assert len(state["detections"]) == 4
    assert state["people_visible"] == 1
    assert state["tracks"] == state["person_arrivals"] == []
    assert not (tmp_path / "tracks.sqlite3").exists()


@pytest.mark.parametrize(
    "shape",
    [
        (720, 1280),
        (480, 640),
        (1080, 1920),
        (721, 1280),
        (1280, 720),
        (180, 320),
        (700, 1000),
        (540, 960),
    ],
)
def test_preprocessing_preserves_model_input_pixels_and_original_image(shape):
    image = np.random.default_rng(8).integers(0, 256, (*shape, 3), dtype=np.uint8)
    original = image.copy()
    side = max(shape)
    square = np.full((side, side, 3), 114, dtype=np.uint8)
    square[: shape[0], : shape[1]] = image
    expected = cv2.dnn.blobFromImage(square, 1 / 255, (640, 640), swapRB=True)
    np.testing.assert_array_equal(input_blob(image, 640), expected)
    np.testing.assert_array_equal(image, original)


@pytest.mark.parametrize(
    "shape",
    [
        (720, 1280),
        (721, 1281),
        (360, 640),
        (641, 359),
        (90, 160),
        (1280, 720),
        (17, 19),
        (640, 640),
    ],
)
def test_reusable_blob_preserves_every_float32_value_across_frames(shape):
    rng = np.random.default_rng(42)
    output = np.empty((1, 3, 640, 640), dtype=np.float32)
    for _ in range(2):
        image = rng.integers(0, 256, (*shape, 3), dtype=np.uint8)
        expected = input_blob(image, 640)
        actual = input_blob(image, 640, out=output)
        assert actual is output
        np.testing.assert_array_equal(actual, expected)
