"""Single-owner capture with demand-driven IPC and bounded native-call recovery."""

import math
import multiprocessing as mp
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from securitypi.config import CameraSettings


class CaptureError(RuntimeError):
    """Safe operational message, without native errors or supplied file contents."""


@dataclass(frozen=True)
class Frame:
    image: NDArray[np.uint8]  # OpenCV BGR, H×W×3; consumer owns the returned array.
    sequence: int
    captured_at: datetime
    monotonic_seconds: float
    media_seconds: float | None = None


class FrameSource(Protocol):
    info: dict

    def read(self) -> Frame | None: ...
    def close(self) -> None: ...
    def __enter__(self) -> "FrameSource": ...
    def __exit__(self, *_args) -> None: ...


class SyntheticSource:
    def __init__(self, config: CameraSettings):
        self.config = config
        self.sequence = 0
        self.closed = False
        self.info = {
            "source": "synthetic",
            "backend": "synthetic",
            "width": config.width,
            "height": config.height,
            "fps": config.fps,
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def read(self) -> Frame | None:
        if self.closed:
            raise CaptureError("Source is closed.")
        image = np.zeros((self.config.height, self.config.width, 3), dtype=np.uint8)
        box = max(1, min(self.config.width, self.config.height) // 8)
        x = (self.sequence * 7) % max(1, self.config.width - box + 1)
        y = self.config.height // 2
        image[y : min(y + box, self.config.height), x : x + box] = (50, 180, 240)
        self.sequence += 1
        return Frame(image, self.sequence, datetime.now(UTC), time.monotonic())

    def close(self) -> None:
        self.closed = True


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(value) and value > 0 else None


def _backend(config: CameraSettings) -> int:
    if config.source == "video" and config.backend == "auto":
        return cv2.CAP_FFMPEG
    if config.backend == "auto":
        return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_V4L2
    return {
        "dshow": cv2.CAP_DSHOW,
        "msmf": cv2.CAP_MSMF,
        "v4l2": cv2.CAP_V4L2,
        "ffmpeg": cv2.CAP_FFMPEG,
    }[config.backend]


def _opencv_worker(connection: Connection, config: CameraSettings) -> None:
    """Only this process touches the capture object; parent can terminate a hung driver."""
    capture = None
    try:
        if config.source == "video":
            if config.video_path is None or not config.video_path.is_file():
                connection.send(("error", "Video input must be an existing local file."))
                return
            target = str(config.video_path)
        else:
            target = config.device_index
        capture = cv2.VideoCapture(target, _backend(config))
        if not capture.isOpened():
            connection.send(("error", "Cannot open source. Check device, permissions, or codec."))
            return
        negotiated = {}
        if config.source == "usb":
            # Properties are requests. Drivers may coerce or ignore them.
            if config.fourcc:
                negotiated["fourcc"] = bool(
                    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.fourcc))
                )
            for key, prop, value in (
                ("width", cv2.CAP_PROP_FRAME_WIDTH, config.width),
                ("height", cv2.CAP_PROP_FRAME_HEIGHT, config.height),
                ("fps", cv2.CAP_PROP_FPS, config.fps),
            ):
                negotiated[key] = bool(capture.set(prop, value))
        fourcc_value = capture.get(cv2.CAP_PROP_FOURCC)
        code = int(fourcc_value) if math.isfinite(fourcc_value) else 0
        info = {
            "source": config.source,
            "backend": capture.getBackendName(),
            "width": _finite(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": _finite(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": _finite(capture.get(cv2.CAP_PROP_FPS)),
            "fourcc": "".join(chr((code >> (8 * i)) & 255) for i in range(4)) if code else None,
            "property_set_results": negotiated,
        }
        connection.send(("opened", info))
        count = 0
        expected = _finite(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        while connection.recv() == "read":
            ok, image = capture.read()
            captured_at = datetime.now(UTC)
            acquired = time.monotonic()
            if not ok or image is None or image.size == 0:
                if config.source == "video":
                    # Frame-count metadata is optional; known premature EOF is a decode failure.
                    premature = count == 0 or (expected is not None and count < int(expected))
                    connection.send(("error" if premature else "eof", "Video decoding ended."))
                else:
                    connection.send(("error", "Camera stopped returning frames."))
                return
            if image.ndim != 3 or image.shape[2] != 3 or image.nbytes > 64 * 1024 * 1024:
                connection.send(("error", "Unsupported or oversized camera frame."))
                return
            count += 1
            media_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
            media = media_ms / 1000 if math.isfinite(media_ms) and media_ms >= 0 else None
            connection.send(("frame", (image, captured_at, acquired, media)))
    except (cv2.error, EOFError, BrokenPipeError, OSError, ValueError):
        try:
            connection.send(("error", "Native capture failed. Check device or codec."))
        except (OSError, BrokenPipeError):
            pass
    finally:
        if capture is not None:
            capture.release()
        connection.close()


class NativeSource:
    def __init__(self, config: CameraSettings, *, worker_target=_opencv_worker):
        self.config = config
        self.worker_target = worker_target
        self.connection = None
        self.process = None
        self.info = {"source": config.source}
        self.sequence = 0
        self.closed = False
        self.ended = False
        self.reconnects = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _receive(self) -> tuple:
        if not self.connection.poll(self.config.io_timeout_seconds):
            raise CaptureError("Native source timed out.")
        try:
            return self.connection.recv()
        except (EOFError, OSError) as exc:
            raise CaptureError("Capture worker exited unexpectedly.") from exc

    def _connect(self) -> None:
        context = mp.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=self.worker_target, args=(child, self.config), daemon=True
        )
        try:
            self.process.start()
        finally:
            child.close()
        status, value = self._receive()
        if status != "opened":
            raise CaptureError(value)
        self.info = value

    def _reset(self) -> None:
        if self.connection is not None:
            try:
                self.connection.send("close")
            except (OSError, BrokenPipeError):
                pass
            self.connection.close()
            self.connection = None
        if self.process is not None:
            if self.process.pid is not None:
                self.process.join(timeout=0.25)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=1)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=1)
                self.process.close()
            self.process = None

    def read(self) -> Frame | None:
        if self.closed:
            raise CaptureError("Source is closed.")
        if self.ended:
            return None
        retries = self.config.reconnect_attempts if self.config.source == "usb" else 0
        for attempt in range(retries + 1):
            try:
                if self.connection is None:
                    self._connect()
                self.connection.send("read")
                status, value = self._receive()
                if status == "eof":
                    self.ended = True
                    self._reset()
                    return None
                if status != "frame":
                    raise CaptureError(value)
                image, captured_at, acquired, media = value
                self.sequence += 1
                return Frame(image, self.sequence, captured_at, acquired, media)
            except (CaptureError, OSError) as exc:
                self._reset()
                if attempt == retries:
                    detail = str(exc) if isinstance(exc, CaptureError) else "Capture IPC failed."
                    raise CaptureError(
                        f"Source unavailable after bounded recovery: {detail}"
                    ) from exc
                self.reconnects += 1
                time.sleep(self.config.reconnect_delay_seconds)
        raise AssertionError("Unreachable recovery state")

    def close(self) -> None:
        self.closed = True
        self._reset()


def create_source(config: CameraSettings) -> FrameSource:
    return SyntheticSource(config) if config.source == "synthetic" else NativeSource(config)


def save_snapshot(frame: Frame, path: Path) -> None:
    extension = path.suffix.lower()
    if extension not in (".jpg", ".png"):
        raise CaptureError("Snapshot must use .jpg or .png.")
    ok, encoded = cv2.imencode(extension, frame.image)
    if not ok:
        raise CaptureError("Cannot encode snapshot.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded.tobytes())
