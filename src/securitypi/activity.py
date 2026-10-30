"""Bounded current observations; no extra model, recordings or trajectory history."""

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from securitypi.vision import LABELS, VEHICLES


def light_evidence(image, box, dark_scene):
    """Report bright pixels, never claim to identify headlights or prove lights off.

    Daylight, small/clipped vehicles and missing images are inconclusive. At night,
    reflections and street lighting can produce the same evidence as vehicle lamps.
    """
    if not dark_scene or min(box[:2]) <= 0.01 or max(box[2:]) >= 0.99:
        return "unknown"
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (np.array(box) * [width, height, width, height]).astype(int)
    if x2 - x1 < 24 or y2 - y1 < 16:
        return "unknown"
    crop = cv2.resize(image[y1:y2, x1:x2], (32, 24)).astype(np.float32)
    blue, green, red = cv2.split(crop)
    bright = (crop.max(axis=2) >= 240) | ((red >= 180) & (red > green * 1.5) & (red > blue * 1.5))
    return "bright_regions_visible" if bright.mean() >= 0.01 else "no_bright_regions_visible"


@dataclass
class ActivityMemory:
    road_entered: float
    in_road: bool = False
    light_checked: float = float("-inf")
    lights: str = "unknown"


class Activities:
    def __init__(self, settings):
        self.settings = settings
        self.polygon = np.array(settings.road_polygon, dtype=np.float32)
        self.road_invalid = False
        self.current = {}
        self.zone_status = "not_configured"

    def update(self, tracks, image, now, scene_state):
        configured = bool(self.polygon.size)
        if configured and scene_state in ("moved", "unverifiable"):
            self.road_invalid = True
        self.zone_status = (
            "not_configured"
            if not configured
            else "needs_review"
            if self.road_invalid
            else "active"
            if scene_state == "stable"
            else "waiting_for_stable_camera"
        )
        # One tiny ambient sample, then at most one 32x24 crop per vehicle per second.
        dark = float(cv2.resize(image, (64, 36)).mean()) < 65
        current, observations = {}, []
        for track in tracks:
            record = asdict(track)
            record["label"] = LABELS[track.class_id]
            if scene_state != "stable":
                record["motion"] = "unknown"
            memory = self.current.get(track.id, ActivityMemory(now))
            zone = "unknown"
            if self.zone_status == "active":
                x1, _y1, x2, y2 = track.box
                point = ((x1 + x2) / 2, y2)
                zone = (
                    "road"
                    if cv2.pointPolygonTest(self.polygon, point, False) >= 0
                    else "outside_road"
                )
            if zone != "road" or not memory.in_road:
                memory.road_entered = now
            memory.in_road = zone == "road"
            road_seconds = (
                min(track.stationary_seconds, max(0, now - memory.road_entered))
                if zone == "road" and record["motion"] == "stationary"
                else 0
            )
            vehicle = track.class_id in VEHICLES or track.class_id == 3
            if vehicle and now - memory.light_checked >= 1:
                memory.lights = light_evidence(image, track.box, dark)
                memory.light_checked = now
            lights = memory.lights if vehicle else "not_applicable"
            activity = record["motion"]
            if vehicle and record["motion"] == "stationary":
                if zone == "road":
                    activity = (
                        "lingering_in_road"
                        if road_seconds >= self.settings.road_linger_seconds
                        else "stopped_in_road"
                    )
                elif (
                    track.stationary_seconds >= self.settings.parked_seconds
                    and lights == "no_bright_regions_visible"
                ):
                    activity = "possibly_parked"
            record.update(
                activity=activity,
                zone=zone,
                road_stationary_seconds=round(road_seconds, 1),
                light_observation=lights,
            )
            observations.append(record)
            current[track.id] = memory
        self.current = current  # Lost tracks cannot accumulate unseen road time or crop history.
        return observations
