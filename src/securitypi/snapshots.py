"""Bounded person JPEGs from existing frames; no camera or model ownership."""

import logging
import re
import time
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Event, Thread

# Only files created by this module are eligible for automatic deletion.
NAME = re.compile(r"\d{8}T\d{12}Z-[a-f0-9]{32}-\d+-\d+\.jpg")
THRESHOLDS = (5, 10, 20)


def snapshot_directory(storage):
    # Already inside HA Container's /config mount; never use its public www directory.
    return storage / "home-assistant" / "media" / "securitypi-person-events"


def inventory(storage):
    directory = snapshot_directory(storage)
    if directory.is_symlink():
        raise OSError("Snapshot directory must not be a symlink")
    records = []
    for path in directory.glob("*.jpg"):
        if NAME.fullmatch(path.name) and not path.is_symlink():
            try:
                stamp = datetime.strptime(path.name.split("-")[0], "%Y%m%dT%H%M%S%fZ")
                records.append((stamp.replace(tzinfo=UTC).timestamp(), path, path.stat().st_size))
            except (FileNotFoundError, ValueError):
                pass
    return sorted(records)


def cleanup(storage, config, now=None):
    """Rolling seven days plus hard limits; leave training and unrelated files alone."""
    now = time.time() if now is None else now
    records = inventory(storage)
    # A power loss can leave one incomplete atomic write. Never remove a live write.
    for path in snapshot_directory(storage).glob("*.jpg.tmp"):
        if NAME.fullmatch(path.name.removesuffix(".tmp")) and not path.is_symlink():
            try:
                if path.stat().st_mtime < now - 3600:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
    total, count = sum(row[2] for row in records), len(records)
    for stamp, path, size in records:
        if (
            stamp > now - 7 * 86400
            and total <= config.max_mib * 1048576
            and count <= config.max_images
        ):
            break
        try:
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        total, count = total - size, count - 1
    return {"snapshot_count": count, "snapshot_mib": round(total / 1048576, 2)}


class PersonSnapshots:
    """At most two queued frame copies; skip rather than block inference on disk."""

    def __init__(self, storage, config, run_id):
        self.storage, self.config, self.run_id = storage, config, run_id
        self.saved = {}
        self.queue = Queue(maxsize=2)
        self.stopping = Event()
        self.errors = self.dropped = self.written = 0
        self.worker = None
        if config.enabled:
            directory = snapshot_directory(storage)
            try:
                if directory.is_symlink():
                    raise OSError("Snapshot directory must not be a symlink")
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                directory.chmod(0o700)
                cleanup(storage, config)
            except OSError:
                self.errors += 1
                logging.getLogger("securitypi").warning("Person snapshot storage unavailable")
                return
            self.worker = Thread(target=self._write, name="person-snapshots", daemon=True)
            self.worker.start()

    def update(self, frame, tracks):
        if not self.worker:
            return
        active = {track.id for track in tracks if track.class_id == 0}
        # Keep brief occlusions without retaining every departed identity indefinitely.
        now = frame.monotonic_seconds
        self.saved = {key: value for key, value in self.saved.items() if now - value[1] <= 180}
        for track in tracks:
            if track.id not in active:
                continue
            seen, _ = self.saved.get(track.id, (set(), now))
            due = [
                value
                for value in THRESHOLDS
                if value <= track.observed_seconds and value not in seen
            ]
            self.saved[track.id] = (seen, now)
            if not due:
                continue
            # One image per actual frame, even if an update crosses multiple thresholds.
            threshold = max(due)
            seen.update(due)
            stamp = frame.captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            name = f"{stamp}-{self.run_id}-{track.id}-{threshold}.jpg"
            if self.queue.full():
                self.dropped += 1
                continue
            try:
                self.queue.put_nowait((frame.image.copy(), name))
            except Full:
                self.dropped += 1
        if len(self.saved) > 500:
            self.saved = dict(sorted(self.saved.items(), key=lambda item: item[1][1])[-500:])

    def _write(self):
        import cv2

        while not self.stopping.is_set() or not self.queue.empty():
            try:
                image, name = self.queue.get(timeout=0.2)
            except Empty:
                continue
            temporary = snapshot_directory(self.storage) / (name + ".tmp")
            try:
                cleanup(self.storage, self.config)
                ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise OSError("JPEG encoding failed")
                if len(encoded) > self.config.max_mib * 1048576:
                    raise OSError("JPEG exceeds snapshot budget")
                with temporary.open("xb") as stream:
                    temporary.chmod(0o600)
                    stream.write(encoded)
                temporary.replace(temporary.with_suffix(""))
                cleanup(self.storage, self.config)
                self.written += 1
            except (OSError, cv2.error):
                self.errors += 1
                logging.getLogger("securitypi").warning("Person snapshot write failed")
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    self.errors += 1
                self.queue.task_done()

    def close(self):
        self.stopping.set()
        if self.worker:
            self.worker.join(timeout=5)
