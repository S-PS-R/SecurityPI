"""Sparse, bounded raw-image collection using frames the analyzer already owns."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2

from securitypi.state import read_json, write_json


class DatasetCollector:
    """Persist the interval across worker restarts; stop when either budget fills."""

    def __init__(self, directory: Path, config):
        self.directory = directory / "training"
        self.config = config
        self.next_due = None
        self.started_at = None
        self.ends_at = None
        self.blocked = False
        if not config.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                saved = read_json(self.directory / "collection.json")
            except (OSError, ValueError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            if saved.get("state") in ("complete", "full"):
                self.blocked = True
                return
            if saved.get("started_at"):
                self.started_at = datetime.fromisoformat(saved["started_at"])
            # Recover timing from images if status predates the finite-run settings.
            images = sorted(self.directory.glob("????????T??????Z.jpg"))
            if images:
                latest = datetime.strptime(images[-1].stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                self.next_due = latest + timedelta(hours=config.interval_hours)
                if self.started_at is None:
                    self.started_at = datetime.strptime(images[0].stem, "%Y%m%dT%H%M%SZ").replace(
                        tzinfo=UTC
                    )
            if self.started_at is not None:
                if self.started_at.tzinfo is None:
                    raise ValueError("Dataset start must be timezone-aware")
                self.ends_at = self.started_at + timedelta(hours=config.duration_hours)
        except (OSError, ValueError, TypeError):
            self.blocked = True
            logging.getLogger(__name__).warning(
                "Dataset collection unavailable; live analysis continues."
            )

    def update(self, frame, detections, model):
        if not self.config.enabled or self.blocked:
            return
        if self.started_at is None:
            self.started_at = frame.captured_at
            self.ends_at = self.started_at + timedelta(hours=self.config.duration_hours)
        expired = frame.captured_at >= self.ends_at
        if expired:
            self.blocked = True
        if not expired and self.next_due is not None and frame.captured_at < self.next_due:
            return
        # Retry failures on the next interval, never on every inference frame.
        self.next_due = frame.captured_at + timedelta(hours=self.config.interval_hours)
        try:
            self._collect(frame, detections, model, expired=expired)
        except (OSError, ValueError, cv2.error):
            logging.getLogger(__name__).warning("Dataset snapshot failed; live analysis continues.")

    def _collect(self, frame, detections, model, *, expired=False):
        files = [p for p in self.directory.iterdir() if p.is_file()]
        images = [p for p in files if p.suffix == ".jpg"]
        used = sum(p.stat().st_size for p in files)
        status = {
            "state": "collecting",
            "started_at": self.started_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "images": len(images),
            "bytes": used,
            "max_images": self.config.max_images,
            "max_mib": self.config.max_mib,
            "interval_hours": self.config.interval_hours,
            "next_capture_at": self.next_due.isoformat(),
        }
        if expired or len(images) >= self.config.max_images:
            self.blocked = True
            status.update(
                state="complete",
                reason="duration_limit" if expired else "image_limit",
                next_capture_at=None,
            )
            write_json(self.directory / "collection.json", status)
            return
        # Reserve metadata/review-list space as well as the JPEG itself.
        ok, encoded = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError("JPEG encoding failed")
        if used + encoded.nbytes + 65536 > self.config.max_mib * 1048576:
            self.blocked = True
            status.update(state="full", reason="storage_limit", next_capture_at=None)
            write_json(self.directory / "collection.json", status)
            return
        sample_id = frame.captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        image_path = self.directory / (sample_id + ".jpg")
        manifest_path = self.directory / (sample_id + ".json")
        # Never overwrite a sample or its manual review.
        with image_path.open("xb") as stream:
            stream.write(encoded.tobytes())
        manifest = {
            "sample_id": sample_id,
            "captured_at": frame.captured_at.isoformat(),
            "image": image_path.name,
            "width": frame.image.shape[1],
            "height": frame.image.shape[0],
            "model": model,
            "model_suggestions": detections,
            "review": {
                "status": "pending",
                "reviewer": None,
                "approved_for_training": False,
                "annotations": [],
                "uncertain_regions": [],
                "notes": "Suggestions are not training labels.",
            },
        }
        write_json(manifest_path, manifest)
        rows = [
            "# Training image review",
            "",
            "Model suggestions are unverified. No training labels are exported automatically.",
            "",
            "| Captured (UTC) | Raw image | Review |",
            "|:--|:--|:--|",
        ]
        for path in sorted(self.directory.glob("????????T??????Z.json"), reverse=True):
            value = read_json(path)
            image_link = (self.directory / value["image"]).resolve()
            rows.append(
                f"| {value['captured_at']} | [{path.stem}]({image_link}) "
                f"| {value['review']['status']} |"
            )
        (self.directory / "review.md").write_text("\n".join(rows) + "\n")
        status.update(
            images=len(images) + 1,
            last_capture_at=frame.captured_at.isoformat(),
            bytes=sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file()),
        )
        if status["images"] >= self.config.max_images:
            self.blocked = True
            status.update(state="complete", reason="image_limit", next_capture_at=None)
        write_json(self.directory / "collection.json", status)
