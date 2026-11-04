"""Opt-in, local-only export of human-approved raw images; never trains a model."""

import argparse
import hashlib
import json
import math
import re
import tempfile
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from securitypi.labels import LABELS

SAMPLE = re.compile(r"\d{8}T\d{6}Z")
MAX_BYTES = 25 * 1024**2


def yolo_label(annotation):
    """Retain COCO IDs; convert normalized xyxy to normalized center xywh."""
    cls = annotation["class_id"]
    if type(cls) is not int or cls not in LABELS or annotation.get("label") != LABELS[cls]:
        raise ValueError("Annotation class ID/name must match the COCO mapping.")
    box = annotation["box"]
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("Expected a normalized xyxy box.")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
        raise ValueError("Box coordinates must be finite numbers.")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError("Box must have positive area within the image.")
    values = ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
    return f"{cls} " + " ".join(f"{v:.10f}" for v in values)


def export_dataset(source: Path, destination: Path, *, plan=None, recipe=None):
    """Validate first, stage privately, and refuse to overwrite an existing export."""
    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Export destination already exists; use a new versioned directory.")
    if destination.is_relative_to(source):
        raise ValueError("Export must be separate from the raw training directory.")
    assets = {}
    for name, path in (("TRAINING_PLAN.md", plan), ("rtx3060.yaml", recipe)):
        if path is not None:
            if path.stat().st_size > 131072:
                raise ValueError("Training instructions exceed the size limit.")
            assets[name] = path.read_text(encoding="utf-8")
    records, excluded, used = [], [], 0
    counts = Counter()
    paths = sorted(p for p in source.glob("*.json") if SAMPLE.fullmatch(p.stem))
    if not paths or len(paths) > 1000:
        raise ValueError("Expected between one and 1,000 timestamp-named sample records.")
    for path in paths:
        if path.is_symlink() or path.stat().st_size > 131072:
            raise ValueError("Invalid or oversized sample record.")
        metadata = path.read_bytes()
        data = json.loads(metadata)
        review = data["review"]
        if review.get("excluded_from_training") is True:
            if review.get("approved_for_training") is True:
                raise ValueError("An excluded sample cannot also be approved.")
            excluded.append({"sample_id": path.stem, "reason": review.get("exclusion_reason")})
            continue
        if (
            review.get("approved_for_training") is not True
            or review.get("status") != "human_approved"
            or review.get("uncertain_regions") != []
        ):
            raise ValueError(f"Sample {path.stem} still requires human review.")
        events = [
            e
            for e in data.get("human_review_events", [])
            if e.get("action") == "bounding_boxes_approved"
        ]
        annotations = review["annotations"]
        if not events or events[-1].get("annotations") != annotations:
            raise ValueError("Approved annotations differ from the user's approved boxes.")
        if data["sample_id"] != path.stem or data["image"] != path.stem + ".jpg":
            raise ValueError("Sample ID and raw JPEG name must match the record filename.")
        image = source / data["image"]
        if image.is_symlink() or not image.is_file() or image.stat().st_size > 4 * 1024**2:
            raise ValueError("Expected a local regular raw JPEG under 4 MiB.")
        pixels = image.read_bytes()
        used += len(pixels) + len(metadata)
        if used > MAX_BYTES:
            raise ValueError("Export exceeds its 25 MiB source-data budget.")
        decoded = cv2.imdecode(np.frombuffer(pixels, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.shape[:2] != (data["height"], data["width"]):
            raise ValueError("Raw JPEG dimensions differ from the reviewed sample.")
        labels = "".join(yolo_label(a) + "\n" for a in annotations)
        counts.update(a["label"] for a in annotations)
        records.append((data, pixels, metadata, labels))
    if not records:
        raise ValueError("No human-approved images to export.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".training-export-", dir=destination.parent) as tmp:
        stage = Path(tmp) / "dataset"
        stage.mkdir(mode=0o700)
        for split in ("train", "val", "test"):
            for kind in ("images", "labels"):
                (stage / kind / split).mkdir(parents=True, mode=0o700)
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "format": "YOLO normalized cx cy width height; original 80 COCO IDs",
            "split_counts": {"train": len(records), "val": 0, "test": 0},
            "label_counts": dict(counts),
            "training_ready": False,
            "missing": ["independent reviewed validation data", "independent locked test data"],
            "leakage_group": "single-camera-pilot-20261027-28",
            "excluded": excluded,
            "samples": [],
        }
        for data, pixels, metadata, labels in records:
            sid = data["sample_id"]
            (stage / "images/train" / f"{sid}.jpg").write_bytes(pixels)
            (stage / "labels/train" / f"{sid}.txt").write_text(labels, encoding="utf-8")
            manifest["samples"].append(
                {
                    "sample_id": sid,
                    "captured_at": data["captured_at"],
                    "split": "train",
                    "image_sha256": hashlib.sha256(pixels).hexdigest(),
                    "review_sha256": hashlib.sha256(metadata).hexdigest(),
                    "label_sha256": hashlib.sha256(labels.encode()).hexdigest(),
                    "annotations": data["review"]["annotations"],
                }
            )
        # Without `path`, Ultralytics resolves split paths against this YAML's directory.
        config = "train: images/train\nval: images/val\ntest: images/test\nnames:\n"
        config += "".join(f"  {key}: {value}\n" for key, value in LABELS.items())
        (stage / "dataset.yaml").write_text(config, encoding="utf-8")
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (stage / "README.md").write_text(
            "# Private SecurityPI training pilot\n\n"
            "Raw, unannotated images and human-approved labels only. No review overlays.\n"
            "All pilot frames belong to training; val/test are intentionally empty.\n"
            "Do not reuse these images for validation or claim improvement on them.\n"
            "Original COCO IDs/names retained: person=0, bicycle=1, car=2.\n"
            "One bicycle label covers a user-approved visible tire fragment only.\n"
            "Occlusion/truncation and source hashes are preserved in manifest.json.\n"
            "No training framework, weights, credentials or device config is included.\n"
            "Read TRAINING_PLAN.md (or docs/training-plan.md in the repository) before training.\n"
        )
        for name, content in assets.items():
            (stage / name).write_text(content, encoding="utf-8")
        files = sorted(p for p in stage.rglob("*") if p.is_file())
        checksums = "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(stage).as_posix()}\n"
            for p in files
        )
        (stage / "SHA256SUMS").write_text(checksums)
        with zipfile.ZipFile(stage / "training-export.zip", "x", zipfile.ZIP_STORED) as bundle:
            for path in sorted(stage.rglob("*")):
                if path.name != "training-export.zip":
                    bundle.write(path, path.relative_to(stage).as_posix())
        for path in stage.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        if destination.exists():
            raise ValueError("Export destination was created while preparing the export.")
        stage.rename(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, help="Include a private copy of the evaluation plan.")
    parser.add_argument(
        "--recipe", type=Path, help="Include the proposed external-GPU training YAML."
    )
    args = parser.parse_args()
    result = export_dataset(args.source, args.output, plan=args.plan, recipe=args.recipe)
    print(json.dumps({"splits": result["split_counts"], "labels": result["label_counts"]}))


if __name__ == "__main__":
    main()
