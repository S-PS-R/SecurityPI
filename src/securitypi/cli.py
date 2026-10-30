"""CLI: validate configuration or start the localhost foundation API."""

import argparse
import logging
import sys
from pathlib import Path

from securitypi import __version__
from securitypi.config import ConfigError, load_settings
from securitypi.logging import configure_logging, logging_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SecurityPI local security service")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "check-config",
        "cleanup-snapshots",
        "serve",
        "capture",
        "camera-info",
        "analyze",
        "benchmark",
        "_benchmark-one",
        "model-fetch",
        "notify",
        "soak",
        "thermal-test",
    ):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", type=Path, required=True, help="Non-secret TOML file")
        if command in ("capture", "camera-info"):
            from securitypi.capture_cli import add_capture_arguments

            add_capture_arguments(subparser, info_only=command == "camera-info")
        if command == "analyze":
            subparser.add_argument("--seconds", type=float, default=30)
            subparser.add_argument("--report", type=Path)
            subparser.add_argument("--snapshot", type=Path)
        if command == "notify":
            subparser.add_argument("--seconds", type=float, default=30)
            subparser.add_argument("--dry-run", action="store_true")
        if command == "thermal-test":
            subparser.add_argument(
                "--case",
                required=True,
                choices=("lid-off", "lid-on", "lid-on-tuned", "lid-on-stronger"),
            )
        if command == "soak":
            subparser.add_argument("--seconds", type=float, default=28800)
        if command in ("benchmark", "_benchmark-one"):
            subparser.add_argument("--backend", choices=("opencv", "onnxruntime"), default="opencv")
            subparser.add_argument("--images", type=Path, nargs="+", required=True)
            subparser.add_argument("--runs", type=int, default=5)
            subparser.add_argument(
                "--labels", type=Path, help="Optional COCO-format label directory"
            )
            subparser.add_argument("--threads", type=int, choices=(1, 2, 4), default=2)
            if command == "benchmark":
                subparser.add_argument("--models", type=Path, nargs="+", required=True)
                subparser.add_argument("--report", type=Path, required=True)
            else:
                subparser.add_argument("--model", type=Path, required=True)
        if command == "model-fetch":
            subparser.add_argument("--name", choices=("yolov8n", "yolo26n"), required=True)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"securitypi: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level)
    logger = logging.getLogger("securitypi")
    if args.command == "cleanup-snapshots":
        import json

        from securitypi.snapshots import cleanup

        try:
            print(json.dumps(cleanup(settings.storage.directory, settings.snapshots)))
            return 0
        except OSError:
            logger.error("Snapshot cleanup failed; check storage permissions.")
            return 2
    if args.command == "thermal-test":
        from securitypi.thermal import run_thermal

        try:
            return run_thermal(settings, args)
        except (OSError, ValueError, StopIteration) as exc:
            logger.error("Thermal preflight failed: %s", exc)
            return 2
    if args.command == "soak":
        import math

        if (
            sys.platform != "linux"
            or not math.isfinite(args.seconds)
            or not 60 <= args.seconds <= 86400
        ):
            logger.error("Soak requires Linux and --seconds between 60 and 86400.")
            return 2
        from securitypi.soak import run_soak

        try:
            return run_soak(settings, args)
        except (OSError, ValueError):
            logger.error("Soak could not run; check local storage, existing workers and logs.")
            return 2
    if args.command == "notify":
        import math
        import sqlite3

        from securitypi.notifications import run_notifications

        try:
            if not math.isfinite(args.seconds) or not 0 <= args.seconds <= 86400:
                raise ConfigError("--seconds must be between 0 and 86400; 0 runs until Ctrl+C.")
            return run_notifications(settings, args)
        except ConfigError as exc:
            logger.error("%s", exc)
            return 2
        except (OSError, sqlite3.Error):
            logger.error("Notification worker failed; check local storage and permissions.")
            return 2
    if args.command in ("analyze", "benchmark", "_benchmark-one", "model-fetch"):
        import json
        import math
        import subprocess

        from securitypi.capture import CaptureError
        from securitypi.vision import VisionError
        from securitypi.vision_cli import benchmark_one, run_analysis, run_benchmark

        try:
            if args.command == "analyze":
                if not math.isfinite(args.seconds) or not 0 <= args.seconds <= 86400:
                    raise VisionError("--seconds must be between 0 and 86400; 0 runs until Ctrl+C.")
                return run_analysis(settings, args)
            if args.command == "model-fetch":
                from securitypi.models import fetch

                print(fetch(args.name, settings.storage.directory / "models"))
                return 0
            if not 1 <= args.runs <= 50 or not 1 <= len(args.images) <= 16:
                raise VisionError("Use 1–50 runs and 1–16 input images per benchmark.")
            if args.command == "_benchmark-one":
                print(
                    json.dumps(
                        benchmark_one(
                            args.model,
                            args.images,
                            args.runs,
                            args.threads,
                            args.labels,
                            args.backend,
                        )
                    )
                )
                return 0
            if len(args.models) > 2:
                raise VisionError("Compare at most two models per benchmark.")
            return run_benchmark(settings, args)
        except ImportError:
            logger.error("Analysis tracking requires requirements/vision.txt in this venv.")
            return 2
        except (VisionError, ConfigError, CaptureError) as exc:
            logger.error("%s", exc)
            return 2
        except (OSError, subprocess.SubprocessError):
            logger.error("Vision command failed; check input paths, storage and process limits.")
            return 2
    if args.command == "check-config":
        logger.info("Configuration valid. No hardware or network connections started.")
        return 0

    if args.command in ("capture", "camera-info"):
        from securitypi.capture import CaptureError
        from securitypi.capture_cli import run_capture

        try:
            return run_capture(settings, args)
        except (CaptureError, ConfigError) as exc:
            logger.error("%s", exc)
            return 2
        except OSError:
            logger.error("Cannot write capture artifact. Check storage permissions and free space.")
            return 2

    import uvicorn

    from securitypi.api import create_app

    logger.info("Starting loopback status bridge; run analyze separately to monitor the camera.")
    uvicorn.run(
        create_app(settings),
        host=settings.server.host,
        port=settings.server.port,
        log_config=logging_config(settings.log_level),
        access_log=False,
    )
    return 0
