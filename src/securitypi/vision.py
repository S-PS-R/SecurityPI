"""Small OpenCV ONNX detector. No training framework or automatic downloads."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from securitypi.labels import LABELS


class VisionError(RuntimeError):
    """An actionable, non-sensitive analysis error."""


VEHICLES = {2, 3, 5, 7}
DETECTED_CLASSES = VEHICLES | {0}


@dataclass(frozen=True)
class Detection:
    class_id: int
    confidence: float
    box: tuple[float, float, float, float]  # Normalized x1, y1, x2, y2.


def evaluate(detections, label_path, iou_threshold=0.5):
    """Confidence-ordered precision/recall at a fixed IoU; this is not mAP."""
    truth = []
    for line in label_path.read_text().splitlines():
        if not line.strip():
            continue
        values = [float(value) for value in line.split()]
        if len(values) != 5 or not np.isfinite(values).all():
            raise VisionError("Expected finite COCO labels: class cx cy width height.")
        cls, x, y, width, height = values
        if cls in LABELS:
            truth.append(
                (int(cls), np.array([x - width / 2, y - height / 2, x + width / 2, y + height / 2]))
            )
    unmatched = set(range(len(truth)))
    matched = 0
    for detection in sorted(detections, key=lambda d: -d.confidence):
        best, best_iou = None, 0
        box = np.array(detection.box)
        area = np.prod(box[2:] - box[:2])
        for index in unmatched:
            cls, expected = truth[index]
            if cls != detection.class_id:
                continue
            intersection = np.maximum(
                0, np.minimum(box[2:], expected[2:]) - np.maximum(box[:2], expected[:2])
            ).prod()
            union = area + np.prod(expected[2:] - expected[:2]) - intersection
            iou = intersection / max(union, 1e-9)
            if iou >= iou_threshold and iou > best_iou:
                best, best_iou = index, iou
        if best is not None:
            unmatched.remove(best)
            matched += 1
    return {
        "true_positive": matched,
        "false_positive": len(detections) - matched,
        "false_negative": len(unmatched),
    }


def decode(output, image_shape, input_size, confidence=0.15, nms_iou=0.45, limit=100):
    """Handle COCO YOLOv8 raw heads and YOLO26 end-to-end exports explicitly."""
    height, width = image_shape[:2]
    scale = input_size / max(height, width)  # Top-left square letterbox.
    values = output[0]
    if values.ndim != 2:
        raise VisionError("Unsupported model output: expected one COCO detection tensor.")
    if values.shape[0] == 84:
        values = values.T
        classes = values[:, 4:].argmax(axis=1)
        scores = values[np.arange(len(values)), classes + 4]
        boxes = values[:, :4].copy()
        boxes[:, :2] -= boxes[:, 2:] / 2
        boxes[:, 2:] += boxes[:, :2]
    elif values.shape[1] == 6:
        boxes, scores, classes = values[:, :4], values[:, 4], values[:, 5].astype(int)
    else:
        raise VisionError("Unsupported model output: use an approved COCO ONNX export.")
    valid = (scores >= confidence) & np.isin(classes, list(DETECTED_CLASSES))
    valid &= np.isfinite(boxes).all(axis=1) & np.isfinite(scores)
    boxes, scores, classes = boxes[valid].copy(), scores[valid], classes[valid]
    boxes /= scale
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, width)
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, height)
    valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    boxes, scores, classes = boxes[valid], scores[valid], classes[valid]
    selected = []
    for cls in np.unique(classes):
        indices = np.flatnonzero(classes == cls)
        xywh = boxes[indices].copy()
        xywh[:, 2:] -= xywh[:, :2]
        kept = cv2.dnn.NMSBoxes(xywh.tolist(), scores[indices].tolist(), confidence, nms_iou)
        selected.extend(indices[np.asarray(kept, dtype=int).reshape(-1)].tolist())
    selected = sorted(selected, key=lambda i: -float(scores[i]))[:limit]
    return [
        Detection(
            int(classes[i]),
            float(scores[i]),
            tuple(float(v) for v in boxes[i] / [width, height, width, height]),
        )
        for i in selected
    ]


def input_blob(image, size, *, out=None):
    """Keep the trained letterbox pixels while avoiding source-sized padding.

    Downscaling first is identical when both target dimensions are integers.
    Odd dimensions and upscaling preserve the original padding/resize order.
    A single-owner detector can reuse its float32 NCHW output across calls.
    """
    height, width = image.shape[:2]
    side = max(height, width)
    if side > size and height * size % side == 0 and width * size % side == 0:
        height, width = height * size // side, width * size // side
        image = cv2.resize(image, (width, height))
        side = size
    square = np.full((side, side, 3), 114, dtype=np.uint8)
    square[:height, :width] = image
    if out is None:
        return cv2.dnn.blobFromImage(square, 1 / 255, (size, size), swapRB=True)
    if side != size:
        square = cv2.resize(square, (size, size))
    np.multiply(square.transpose(2, 0, 1)[::-1], np.float32(1 / 255), out=out[0])
    return out


class Detector:
    def __init__(self, model: Path, size=640, threads=2, confidence=0.15, backend="opencv"):
        if not model.is_file() or model.stat().st_size > 64 * 1024 * 1024:
            raise VisionError("Model must be a local ONNX file no larger than 64 MiB.")
        if backend not in ("opencv", "onnxruntime"):
            raise VisionError("Use the opencv or onnxruntime CPU backend.")
        self.backend = backend
        self.size, self.confidence = size, confidence
        self._blob = np.empty((1, 3, size, size), dtype=np.float32)
        cv2.setNumThreads(threads if backend == "opencv" else 1)
        if backend == "onnxruntime":
            self._load_onnxruntime(model, threads)
            return
        try:
            self.net = cv2.dnn.readNetFromONNX(str(model))
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except cv2.error as exc:
            raise VisionError("Cannot load ONNX model with OpenCV CPU backend.") from exc

    def _load_onnxruntime(self, model, threads):
        # Optional CPU inference only; no training framework or automatic downloads.
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise VisionError(
                "Install requirements/onnxruntime.txt or use backend=opencv."
            ) from exc
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_cpu_mem_arena = False
        for name in ("session.intra_op.allow_spinning", "session.inter_op.allow_spinning"):
            options.add_session_config_entry(name, "0")
        try:
            self.net = ort.InferenceSession(
                str(model), sess_options=options, providers=["CPUExecutionProvider"]
            )
            inputs = self.net.get_inputs()
            if (
                len(inputs) != 1
                or inputs[0].shape != [1, 3, self.size, self.size]
                or inputs[0].type != "tensor(float)"
                or len(self.net.get_outputs()) != 1
            ):
                raise ValueError("Expected one fixed-size float32 input and one output")
            self.input_name = inputs[0].name
        except Exception as exc:
            raise VisionError("Cannot load the approved ONNX model with the CPU runtime.") from exc

    def predict(self, image):
        blob = input_blob(image, self.size, out=self._blob)
        if self.backend == "onnxruntime":
            try:
                output = self.net.run(None, {self.input_name: blob})[0]
            except Exception as exc:
                raise VisionError("CPU runtime inference failed; check model input shape.") from exc
            return decode(output, image.shape, self.size, self.confidence)
        try:
            self.net.setInput(blob)
            return decode(self.net.forward(), image.shape, self.size, self.confidence)
        except cv2.error as exc:
            raise VisionError("Inference failed; check the model's fixed input size.") from exc
