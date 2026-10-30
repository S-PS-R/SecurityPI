"""ByteTrack adapter with bounded, time-based presence metadata."""

from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from securitypi.vision import Detection


@dataclass(frozen=True)
class Track:
    id: int
    class_id: int
    box: tuple[float, float, float, float]
    confidence: float
    elapsed_seconds: float
    observed_seconds: float
    stationary_seconds: float
    motion: str = "unknown"


@dataclass
class Presence:
    first_seen: float
    last_seen: float
    observed_seconds: float
    stationary_since: float
    anchor: np.ndarray
    smoothed: np.ndarray
    moved: bool = False


class PersonArrivals:
    """Retain up to 100 tiny arrival records for 120 seconds, never images.

    This bridges the analyzer's latest-frame slot and the slower notification poll.
    Active track IDs remain known after their arrival record ages out.
    """

    def __init__(self, min_seconds=0):
        self.min_seconds = min_seconds
        self.recent = deque(maxlen=100)
        self.known = set()

    def update(self, tracks, captured_at):
        cutoff = captured_at.timestamp() - 120
        while self.recent and self.recent[0][0] < cutoff:
            self.recent.popleft()
        current = {track.id for track in tracks if track.class_id == 0}
        qualified = {
            track.id: track
            for track in tracks
            if track.class_id == 0 and getattr(track, "observed_seconds", 0) >= self.min_seconds
        }
        new = qualified.keys() - self.known
        for key in sorted(new):
            self.recent.append(
                (
                    captured_at.timestamp(),
                    {
                        "id": key,
                        "observed_seconds": getattr(qualified[key], "observed_seconds", 0),
                        "occurred_at": captured_at.isoformat(),
                    },
                )
            )
        self.known = (
            (self.known & current) | set(qualified) | {item[1]["id"] for item in self.recent}
        )
        return [item[1] for item in self.recent], bool(new)


class Tracker:
    def __init__(self, fps=2.0, lost_seconds=3.0, stationary_seconds=5.0):
        from securitypi._vendor.bytetrack.byte_tracker import BYTETracker

        self.lost_seconds = lost_seconds
        self.interval = 1 / fps
        self.stationary_seconds = stationary_seconds
        args = SimpleNamespace(
            track_thresh=0.25, track_buffer=30 * lost_seconds, match_thresh=0.8, mot20=False
        )
        self.trackers = {cls: BYTETracker(args, frame_rate=fps) for cls in (0, 2, 3, 5, 7)}
        self.metadata = {}
        self.last_time = None
        self.previous_visible = set()

    def update(self, detections: list[Detection], now: float) -> list[Track]:
        # A stalled source cannot preserve identity indefinitely merely by skipping updates.
        if self.last_time is not None and (
            now <= self.last_time or now - self.last_time > self.lost_seconds
        ):
            self.__init__(1 / self.interval, self.lost_seconds, self.stationary_seconds)
        self.last_time = now
        expired = {
            key for key, value in self.metadata.items() if now - value.last_seen > self.lost_seconds
        }
        output = []
        alive = set()
        for cls, tracker in self.trackers.items():
            tracker.tracked_stracks = [
                t for t in tracker.tracked_stracks if t.track_id not in expired
            ]
            tracker.lost_stracks = [t for t in tracker.lost_stracks if t.track_id not in expired]
            boxes = np.array(
                [[*d.box, d.confidence] for d in detections if d.class_id == cls], dtype=float
            ).reshape(-1, 5)
            current = tracker.update(boxes, (1, 1), (1, 1))
            alive.update(t.track_id for t in tracker.tracked_stracks + tracker.lost_stracks)
            for track in current:
                key = track.track_id
                box = np.clip(track.tlbr, 0, 1)
                center = (box[:2] + box[2:]) / 2
                if key not in self.metadata:
                    self.metadata[key] = Presence(now, now, 0.0, now, center, center)
                meta = self.metadata[key]
                delta = now - meta.last_seen
                if key in self.previous_visible and delta <= self.lost_seconds:
                    meta.observed_seconds += max(0, delta)
                # Smooth detector jitter; scale movement to the object, not only the image.
                # A fixed anchor also catches slow drift that is tiny between adjacent frames.
                meta.smoothed = 0.4 * center + 0.6 * meta.smoothed
                threshold = max(0.005, float(min(box[2:] - box[:2])) * 0.12)
                moved = np.linalg.norm(meta.smoothed - meta.anchor) > threshold
                if moved or key not in self.previous_visible or delta > self.lost_seconds:
                    meta.stationary_since, meta.anchor = now, meta.smoothed.copy()
                    meta.moved = bool(moved)
                meta.last_seen = now
                stationary = now - meta.stationary_since
                motion = (
                    "stationary"
                    if stationary >= self.stationary_seconds
                    else "moving"
                    if meta.moved
                    else "unknown"
                )
                output.append(
                    Track(
                        key,
                        cls,
                        tuple(float(v) for v in box),
                        float(track.score),
                        now - meta.first_seen,
                        meta.observed_seconds,
                        stationary,
                        motion,
                    )
                )
        self.previous_visible = {track.id for track in output}
        self.metadata = {key: value for key, value in self.metadata.items() if key in alive}
        return output
