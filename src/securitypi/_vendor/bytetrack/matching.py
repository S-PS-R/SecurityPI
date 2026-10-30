"""ByteTrack matching primitives using only NumPy and lapx.

Adapted from ifzhang/ByteTrack d1bf0191 (MIT; see LICENSE).
Only the three operations called by BYTETracker are retained.
"""

import lap
import numpy as np


def linear_assignment(cost_matrix, thresh):
    if cost_matrix.size == 0:
        return np.empty((0, 2), dtype=int), tuple(range(cost_matrix.shape[0])), tuple(
            range(cost_matrix.shape[1])
        )
    _, rows, columns = lap.lapjv(cost_matrix, extend_cost=True, cost_limit=thresh)
    matches = np.array([(i, j) for i, j in enumerate(rows) if j >= 0], dtype=int).reshape(-1, 2)
    return matches, np.flatnonzero(rows < 0), np.flatnonzero(columns < 0)


def iou_distance(first, second):
    a = np.array([t.tlbr for t in first], dtype=float).reshape(-1, 4)
    b = np.array([t.tlbr for t in second], dtype=float).reshape(-1, 4)
    intersection = np.maximum(0, np.minimum(a[:, None, 2:], b[None, :, 2:])
                              - np.maximum(a[:, None, :2], b[None, :, :2])).prod(axis=2)
    area_a = np.maximum(0, a[:, 2:] - a[:, :2]).prod(axis=1)
    area_b = np.maximum(0, b[:, 2:] - b[:, :2]).prod(axis=1)
    return 1 - intersection / np.maximum(area_a[:, None] + area_b[None, :] - intersection, 1e-9)


def fuse_score(cost_matrix, detections):
    return 1 - (1 - cost_matrix) * np.array([d.score for d in detections])[None, :]
