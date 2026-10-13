"""Capture smoke tests: JSON metadata and explicitly requested local artifacts."""

import argparse
import json
import time
from pathlib import Path

from pydantic import ValidationError

from securitypi.capture import CaptureError, create_source, save_snapshot
from securitypi.config import CameraSettings, ConfigError, Settings


def add_capture_arguments(parser: argparse.ArgumentParser, *, info_only: bool) -> None:
    parser.add_argument("--source", choices=("synthetic", "usb", "video"))
    parser.add_argument("--device-index", type=int)
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf", "v4l2", "ffmpeg"))
    parser.add_argument(
        "--video", type=Path, help="Local video file, relative to working directory"
    )
    if not info_only:
        parser.add_argument(
            "--frames", type=int, default=30, help="Frame limit; 0 means until Ctrl+C"
        )
        parser.add_argument(
            "--snapshot", type=Path, help="Last frame .jpg/.png under storage directory"
        )
        parser.add_argument("--report", type=Path, help="JSON report under storage directory")


def camera_config(settings: Settings, args: argparse.Namespace) -> CameraSettings:
    raw = settings.camera.model_dump()
    for arg, key in (
        ("source", "source"),
        ("device_index", "device_index"),
        ("backend", "backend"),
    ):
        if getattr(args, arg) is not None:
            raw[key] = getattr(args, arg)
    if args.video is not None:
        if args.source not in (None, "video"):
            raise ConfigError("--video requires a video source.")
        raw["source"] = "video"
        raw["video_path"] = args.video.resolve()
    elif args.source in ("usb", "synthetic"):
        raw["video_path"] = None
    try:
        return CameraSettings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError("Invalid capture options; check device index and video source.") from exc


def artifact_path(path: Path | None, storage: Path) -> Path | None:
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.is_relative_to(storage.resolve()):
        raise CaptureError("Capture artifacts must stay inside the configured storage directory.")
    return resolved


def run_capture(settings: Settings, args: argparse.Namespace) -> int:
    config = camera_config(settings, args)
    info_only = args.command == "camera-info"
    limit = 1 if info_only else args.frames
    if limit < 0:
        raise CaptureError("--frames must be non-negative.")
    snapshot = None if info_only else artifact_path(args.snapshot, settings.storage.directory)
    report_path = None if info_only else artifact_path(args.report, settings.storage.directory)
    if snapshot is not None and snapshot.suffix.lower() not in (".jpg", ".png"):
        raise CaptureError("Snapshot must use .jpg or .png.")
    if report_path is not None and report_path.suffix.lower() != ".json":
        raise CaptureError("Report must use .json.")

    count = 0
    last = None
    first_acquired = None
    reason = "frame_limit"
    started = time.monotonic()
    next_due = started
    with create_source(config) as source:
        try:
            while limit == 0 or count < limit:
                delay = next_due - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                frame = source.read()
                if frame is None:
                    reason = "end_of_file"
                    break
                last = frame
                if first_acquired is None:
                    first_acquired = frame.monotonic_seconds
                count += 1
                next_due = max(next_due + 1 / config.fps, time.monotonic())
        except KeyboardInterrupt:
            reason = "interrupted"
        elapsed = time.monotonic() - started
        observed = dict(source.info)
        reconnects = getattr(source, "reconnects", 0)
    # Capture ownership is released before any artifact encoding or writes.
    if snapshot is not None and last is not None:
        save_snapshot(last, snapshot)
    report = {
        "source": config.source,
        "reason": reason,
        "frames": count,
        "elapsed_seconds": round(elapsed, 3),
        "delivery_fps_including_open": round(count / elapsed, 3) if elapsed else 0,
        "frame_interval_fps": round((count - 1) / (last.monotonic_seconds - first_acquired), 3)
        if count > 1 and last.monotonic_seconds > first_acquired
        else None,
        "reconnects": reconnects,
        "requested": {
            "width": config.width,
            "height": config.height,
            "fps": config.fps,
            "fourcc": config.fourcc,
            "backend": config.backend,
        },
        "negotiated": observed,
        "last_frame": {
            "width": last.image.shape[1],
            "height": last.image.shape[0],
            "sequence": last.sequence,
            "captured_at": last.captured_at.isoformat(),
            "monotonic_seconds": last.monotonic_seconds,
            "media_seconds": last.media_seconds if config.source == "video" else None,
        }
        if last is not None
        else None,
        "snapshot_saved": snapshot is not None and last is not None,
        "monitoring": False,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 130 if reason == "interrupted" else 0
