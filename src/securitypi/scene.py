"""Conservative scene learning: camera stability, curb candidates, and gap geometry.

Vehicle alignment proposes curb sections; it cannot establish legal parking or
visibility behind trees. Geometric capacity is separate from verified availability.
"""

from collections import deque
from itertools import combinations

import cv2
import numpy as np

from securitypi.vision import VEHICLES


class SceneGuard:
    """Compare a small fixed reference using ORB; invalidate rather than guess."""

    def __init__(self):
        self.orb = cv2.ORB_create(nfeatures=250)
        self.reference = None
        self.size = None

    def check(self, image):
        gray = cv2.cvtColor(cv2.resize(image, (320, 180)), cv2.COLOR_BGR2GRAY)
        points, descriptors = self.orb.detectAndCompute(gray, None)
        size = image.shape[:2]
        if descriptors is None or len(points) < 12:
            return "unverifiable"
        if self.reference is None:
            self.reference, self.size = (points, descriptors), size
            return "new"
        old_points, old_descriptors = self.reference
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(old_descriptors, descriptors, k=2)
        good = [
            pair[0]
            for pair in matches
            if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance
        ]
        if len(good) < 12:
            self.reference = None
            return "unverifiable"
        before = np.float32([old_points[m.queryIdx].pt for m in good])
        after = np.float32([points[m.trainIdx].pt for m in good])
        matrix, inliers = cv2.estimateAffinePartial2D(before, after, method=cv2.RANSAC)
        if matrix is None or inliers.sum() < 10:
            self.reference = None
            return "unverifiable"
        scale = np.hypot(matrix[0, 0], matrix[1, 0])
        moved = (
            size != self.size
            or np.linalg.norm(matrix[:, 2]) > 8
            or abs(scale - 1) > 0.04
            or abs(np.arctan2(matrix[1, 0], matrix[0, 0])) > 0.04
        )
        if moved:
            self.reference, self.size = (points, descriptors), size
            return "moved"
        return "stable"


def curb_candidates(tracks, clearance=1.2):
    """Discover aligned stationary cars, projecting box spans along each candidate curb.

    Only intervals bracketed by currently observed vehicles are measured. Two
    cars are enough to propose a row, but do not establish that it is a curb.
    """
    cars = [
        t
        for t in tracks
        if t.class_id in VEHICLES
        and t.stationary_seconds >= 30
        and min(t.box[:2]) > 0.01
        and max(t.box[2:]) < 0.99
    ][:30]
    sections = []
    while len(cars) >= 2 and len(sections) < 4:
        centers = np.array([[(t.box[0] + t.box[2]) / 2, (t.box[1] + t.box[3]) / 2] for t in cars])
        best = []
        for i, j in combinations(range(len(cars)), 2):
            axis = centers[j] - centers[i]
            norm = np.linalg.norm(axis)
            if norm < 0.08:
                continue
            axis /= norm
            distance = np.abs((centers - centers[i]) @ np.array([-axis[1], axis[0]]))
            group = np.flatnonzero(distance < 0.035).tolist()
            if len(group) > len(best):
                best = group
        if len(best) < 2:
            break
        group = [cars[i] for i in best]
        points = centers[best]
        _, _, vt = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)
        axis = vt[0]
        if axis[np.argmax(np.abs(axis))] < 0:
            axis = -axis
        intervals = []
        for car in group:
            x1, y1, x2, y2 = car.box
            projections = np.array([[x1, y1], [x2, y1], [x1, y2], [x2, y2]]) @ axis
            intervals.append((float(projections.min()), float(projections.max()), car.id))
        intervals.sort()
        lengths = np.array([end - start for start, end, _ in intervals])
        median = float(np.median(lengths))
        # Large perspective/size variation prevents a single safe local scale.
        consistent = float(lengths.max() / max(lengths.min(), 1e-6)) < 1.7
        gaps = []
        end = intervals[0][1]
        for start, stop, _track_id in intervals[1:]:
            if start > end:
                gaps.append(
                    {
                        "start": end,
                        "end": start,
                        "estimated_car_capacity": int((start - end) / (median * clearance))
                        if consistent
                        else None,
                        "availability": "unknown",
                        "visibility_verified": False,
                    }
                )
            end = max(end, stop)
        sections.append(
            {
                "axis": axis.tolist(),
                "center": points.mean(axis=0).tolist(),
                "vehicle_ids": [t.id for t in group],
                "typical_car_span": median,
                "scale_consistent": consistent,
                "gaps": gaps,
                "availability": "unknown",
                "unobserved_edges": "unknown",
                "kind": "candidate_vehicle_row",
            }
        )
        cars = [car for i, car in enumerate(cars) if i not in best]
    return sections


class Calibration:
    def __init__(self, seconds=300.0):
        self.seconds = seconds
        self.started = None
        self.scene_id = 0
        self.history = deque(maxlen=120)
        self.last_sample = None

    def update(self, tracks, now, scene_state):
        if scene_state != "stable":
            self.started = now if scene_state in ("new", "moved") else None
            self.scene_id += 1
            self.history.clear()
            self.last_sample = None
        if self.started is None and scene_state == "stable":
            self.started = now
        elapsed = max(0, now - self.started) if self.started is not None else 0
        sections = curb_candidates(tracks) if scene_state == "stable" else []
        # Learn a robust local span over time, bounded to 120 one-second summaries.
        if sections and (self.last_sample is None or now - self.last_sample >= 1):
            self.history.append([(s["axis"], s["center"], s["typical_car_span"]) for s in sections])
            self.last_sample = now
        ready = False
        for section in sections:
            axis = np.array(section["axis"])
            normal = np.array([-axis[1], axis[0]])
            center = np.array(section["center"])
            samples = [
                span
                for summary in self.history
                for old_axis, old_center, span in summary
                if abs(np.dot(old_axis, axis)) > 0.96
                and abs((np.array(old_center) - center) @ normal) < 0.04
            ]
            section["scale_samples"] = len(samples)
            local_ready = elapsed >= self.seconds and len(samples) >= 20
            ready |= local_ready
            if samples:
                section["typical_car_span"] = float(np.median(samples))
            for gap in section["gaps"]:
                gap["estimated_car_capacity"] = (
                    int((gap["end"] - gap["start"]) / (section["typical_car_span"] * 1.2))
                    if local_ready and section["scale_consistent"]
                    else None
                )
        return {
            "scene_id": self.scene_id,
            "state": "candidate_geometry" if ready else "learning",
            "scene_stability": scene_state,
            "learning_seconds": round(elapsed, 1),
            "required_seconds": self.seconds,
            "sections": sections,
            "available_spaces": None,
            "availability": "unknown",
            "reason": "Geometry does not establish curb visibility or parking permission.",
        }
