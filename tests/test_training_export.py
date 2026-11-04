"""Private training exports must follow human approvals and keep original class IDs."""

import hashlib
import json
import os
import zipfile

import cv2
import numpy as np
import pytest

from securitypi.training_export import export_dataset, yolo_label


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    sid = "20261028T003158Z"
    annotation = {"class_id": 2, "label": "car", "box": [0.1, 0.2, 0.5, 0.6]}
    data = {
        "sample_id": sid,
        "image": sid + ".jpg",
        "width": 80,
        "height": 60,
        "captured_at": "2026-10-28T00:31:58+00:00",
        "model_suggestions": [{"label": "truck", "confidence": 0.9}],
        "review": {
            "status": "human_approved",
            "approved_for_training": True,
            "uncertain_regions": [],
            "annotations": [annotation],
        },
        "human_review_events": [{"action": "bounding_boxes_approved", "annotations": [annotation]}],
    }
    assert cv2.imwrite(str(source / data["image"]), np.zeros((60, 80, 3), np.uint8))
    path = source / (sid + ".json")
    path.write_text(json.dumps(data))
    return source, path, data


def test_export_is_raw_private_portable_and_does_not_invent_holdouts(sample, tmp_path):
    source, path, data = sample
    original = (source / data["image"]).read_bytes()
    before_review = path.read_bytes()
    # Review illustrations and unrelated JSON must never enter training.
    (source / "review-preview.jpg").write_bytes(b"overlay")
    (source / "review-progress.json").write_text("{}")
    destination = tmp_path / "export"
    plan = tmp_path / "plan.md"
    plan.write_text("Do not train without independent validation.")
    result = export_dataset(source, destination, plan=plan)
    assert result["split_counts"] == {"train": 1, "val": 0, "test": 0}
    assert not result["training_ready"]
    assert result["label_counts"] == {"car": 1}
    assert result["samples"][0]["image_sha256"] == hashlib.sha256(original).hexdigest()
    assert (destination / "images/train" / data["image"]).read_bytes() == original
    assert path.read_bytes() == before_review
    assert (destination / "labels/train" / (path.stem + ".txt")).read_text().startswith("2 ")
    assert not list((destination / "images/val").iterdir())
    assert not list((destination / "images/test").iterdir())
    config = (destination / "dataset.yaml").read_text()
    assert "  0: person\n  1: bicycle\n  2: car\n" in config and "  79: toothbrush" in config
    assert "path:" not in config
    with zipfile.ZipFile(destination / "training-export.zip") as archive:
        assert archive.testzip() is None
        assert not any("preview" in n for n in archive.namelist())
        assert archive.read("images/train/" + data["image"]) == original
        assert archive.read("TRAINING_PLAN.md") == plan.read_bytes()
    for line in (destination / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o700
        assert (destination / "training-export.zip").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("problem", ["pending", "uncertain", "edited", "escape", "dimensions"])
def test_changed_samples_are_rejected_without_partial_export(sample, tmp_path, problem):
    source, path, data = sample
    if problem == "pending":
        data["review"]["approved_for_training"] = False
    elif problem == "uncertain":
        data["review"]["uncertain_regions"] = [{"box": [0, 0, 1, 1]}]
    elif problem == "edited":
        data["review"]["annotations"] = []
    elif problem == "escape":
        data["image"] = "../other.jpg"
    else:
        data["height"] = 999
    path.write_text(json.dumps(data))
    destination = tmp_path / "export"
    with pytest.raises(ValueError):
        export_dataset(source, destination)
    assert not destination.exists()


def test_excluded_image_is_not_exported_and_existing_export_is_not_overwritten(sample, tmp_path):
    source, path, data = sample
    other = json.loads(json.dumps(data))
    other["review"].update(approved_for_training=False, excluded_from_training=True)
    (source / "20261028T023158Z.json").write_text(json.dumps(other))
    destination = tmp_path / "export"
    result = export_dataset(source, destination)
    assert len(result["samples"]) == 1 and len(result["excluded"]) == 1
    assert not (destination / "images/train/20261028T023158Z.jpg").exists()
    marker = destination / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="already exists"):
        export_dataset(source, destination)
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("box", [[0, 0, 0, 1], [-0.1, 0, 1, 1], [0, 0, float("nan"), 1]])
def test_invalid_box_never_becomes_a_training_label(box):
    with pytest.raises(ValueError):
        yolo_label({"class_id": 2, "label": "car", "box": box})


def test_class_mapping_and_coordinate_conversion_are_not_reindexed():
    label = yolo_label({"class_id": 2, "label": "car", "box": [0.1, 0.2, 0.5, 0.6]})
    assert [float(v) for v in label.split()] == pytest.approx([2, 0.3, 0.4, 0.4, 0.4])
    with pytest.raises(ValueError, match="COCO"):
        yolo_label({"class_id": 0, "label": "car", "box": [0.1, 0.2, 0.5, 0.6]})
