"""Bounded analysis and reproducible model benchmarks, using the same detector."""

import json
import subprocess
import sys
import time
import uuid
from dataclasses import asdict

import cv2
import numpy as np

from securitypi.activity import Activities
from securitypi.capture import Frame, create_source, save_snapshot
from securitypi.capture_cli import artifact_path
from securitypi.dataset import DatasetCollector
from securitypi.labels import LABELS
from securitypi.models import sha256
from securitypi.scene import SceneGuard
from securitypi.snapshots import PersonSnapshots
from securitypi.state import write_json
from securitypi.vision import Detector, VisionError, evaluate


def annotate(image, detections, status):
    """Draw model observations immediately; tracking never gates the green boxes."""
    image = image.copy()
    height, width = image.shape[:2]
    color = (0, 220, 0)
    for detection in detections:
        x1, y1, x2, y2 = (np.array(detection.box) * [width, height, width, height]).astype(int)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        label = f"{LABELS[detection.class_id]} {detection.confidence:.0%}"
        text_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
        text_x = max(0, min(x1, width - text_width - 4))
        cv2.putText(
            image, label, (text_x, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
        )
    cv2.putText(image, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
    return image


def peak_memory_mib():
    try:
        import resource
    except ImportError:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value / (1024 * 1024 if sys.platform == "darwin" else 1024), 2)


def benchmark_one(model, images, runs, threads, labels=None, backend="opencv"):
    """No camera ownership or tracking; isolate detector preprocessing/inference/postprocess."""
    started = time.perf_counter()
    detector = Detector(model, threads=threads, backend=backend)
    load_ms = (time.perf_counter() - started) * 1000
    timings, detections, inputs = [], [], []
    metrics = {"true_positive": 0, "false_positive": 0, "false_negative": 0}
    cpu_started, wall_started = time.process_time(), time.perf_counter()
    for path in images:
        image = cv2.imread(str(path))
        if image is None:
            raise VisionError("Cannot decode benchmark input image.")
        inputs.append({"name": path.name, "sha256": sha256(path)})
        detector.predict(image)  # Warm up each image; exclude from latency samples.
        for _ in range(runs):
            t = time.perf_counter()
            result = detector.predict(image)
            timings.append((time.perf_counter() - t) * 1000)
        detections.append({"input": path.name, "detections": [asdict(d) for d in result]})
        if labels is not None:
            label = labels / (path.stem + ".txt")
            counts = evaluate(result, label)
            inputs[-1]["labels_sha256"] = sha256(label)
            for key in metrics:
                metrics[key] += counts[key]
    if labels is not None:
        tp, fp, fn = metrics.values()
        metrics.update(
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
            iou_threshold=0.5,
            scope="small labelled smoke set; not representative field accuracy",
        )
    return {
        "model": model.name,
        "sha256": sha256(model),
        "model_bytes": model.stat().st_size,
        "backend": "OpenCV DNN CPU" if backend == "opencv" else "ONNX Runtime CPU",
        "opencv": cv2.__version__,
        "threads": threads,
        "input_size": 640,
        "confidence": 0.15,
        "inputs": inputs,
        "runs_per_image": runs,
        "load_ms": round(load_ms, 2),
        "latency_median_ms": round(float(np.median(timings)), 2),
        "latency_p95_ms": round(float(np.percentile(timings, 95)), 2),
        "detector_fps": round(1000 * len(timings) / sum(timings), 2),
        "cpu_core_equivalents": round(
            (time.process_time() - cpu_started) / (time.perf_counter() - wall_started), 2
        ),
        "process_peak_rss_mib": peak_memory_mib(),
        "detections": detections,
        "accuracy": metrics
        if labels is not None
        else "not measured; unlabelled counts are not accuracy",
    }


def run_benchmark(settings, args):
    report = artifact_path(args.report, settings.storage.directory)
    results = []
    for model in args.models:
        # Separate processes make peak RSS comparable and release each model before the next.
        command = [
            sys.executable,
            "-m",
            "securitypi",
            "_benchmark-one",
            "--config",
            str(args.config),
            "--model",
            str(model),
            "--runs",
            str(args.runs),
            "--threads",
            str(args.threads),
            "--backend",
            args.backend,
            "--images",
            *map(str, args.images),
        ]
        if args.labels is not None:
            command.extend(["--labels", str(args.labels)])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if completed.returncode:
            raise VisionError("Benchmark worker failed; check model and input paths.")
        results.append(json.loads(completed.stdout))
    value = {"results": results, "scope": "detector only; excludes camera/streaming/tracking"}
    write_json(report, value)
    print(json.dumps(value))
    return 0


def run_analysis(settings, args):
    from securitypi.tracking import PersonArrivals, Tracker

    config = settings.vision
    report = artifact_path(
        args.report or settings.storage.directory / "vision-status.json", settings.storage.directory
    )
    snapshot = artifact_path(
        args.snapshot or settings.storage.directory / "vision-preview.jpg",
        settings.storage.directory,
    )
    if snapshot.suffix.lower() not in (".jpg", ".png") or report.suffix.lower() != ".json":
        raise VisionError("Use .jpg/.png preview and .json report paths.")
    started, last_write, last_preview, next_due = time.monotonic(), 0, 0, 0
    rate_started, rate_count, rate_sequence = None, 0, 0
    analysis_fps, capture_fps, decoded_fps = 0.0, 0.0, 0.0
    rate_decoded = 0
    count, tracks, last = 0, [], None
    detections = []
    run_id = uuid.uuid4().hex
    status = {
        "monitoring": False,
        "state": "starting",
        "people_visible": 0,
        "parking": {"availability": "unknown", "available_spaces": None},
    }
    write_json(report, status)
    reason, exit_code = "duration_limit", 0
    last_scene_state = None
    person_snapshots = None
    try:
        if config.model is None:
            raise VisionError("Set vision.model to a local approved ONNX file first.")
        detector = Detector(
            config.model,
            threads=config.threads,
            confidence=config.confidence,
            backend=config.backend,
        )
        collector = DatasetCollector(settings.storage.directory, settings.dataset)
        tracker = (
            Tracker(config.analysis_fps, config.lost_seconds, settings.activity.stationary_seconds)
            if settings.home_assistant.notifications_enabled or settings.snapshots.enabled
            else None
        )
        activities = Activities(settings.activity)
        arrivals = PersonArrivals(settings.home_assistant.person_seconds)
        person_snapshots = PersonSnapshots(settings.storage.directory, settings.snapshots, run_id)
        guard = SceneGuard()
        with create_source(settings.camera) as source:
            while args.seconds == 0 or time.monotonic() - started < args.seconds:
                # USB worker drains encoded frames; decode only when analysis requests one.
                if settings.camera.source == "usb" and next_due > time.monotonic():
                    time.sleep(max(0, next_due - time.monotonic()))
                frame = source.read()
                if frame is None:
                    reason = "end_of_file"
                    break
                now = time.monotonic()
                if now < next_due:
                    time.sleep(min(1 / settings.camera.fps, next_due - now))
                    continue
                state = guard.check(frame.image) if tracker is not None else "unverifiable"
                if tracker is not None and (
                    state in ("new", "moved")
                    or (state == "unverifiable" and last_scene_state != state)
                ):
                    tracker = Tracker(
                        config.analysis_fps,
                        config.lost_seconds,
                        settings.activity.stationary_seconds,
                    )
                last_scene_state = state
                t = time.perf_counter()
                detections = detector.predict(frame.image)
                inference_ms = (time.perf_counter() - t) * 1000
                detection_values = [dict(asdict(d), label=LABELS[d.class_id]) for d in detections]
                collector.update(
                    frame,
                    detection_values,
                    config.model.name,
                )
                sample_time = (
                    frame.media_seconds
                    if settings.camera.source == "video"
                    else frame.monotonic_seconds
                )
                tracks = tracker.update(detections, sample_time) if tracker is not None else []
                person_snapshots.update(frame, tracks)
                observations = activities.update(tracks, frame.image, sample_time, state)
                person_arrivals, new_person = arrivals.update(tracks, frame.captured_at)
                count += 1
                grabbed = (
                    frame.captured_frames if frame.captured_frames is not None else frame.sequence
                )
                if rate_started is None:
                    rate_started, rate_count, rate_sequence = now, count, grabbed
                    rate_decoded = frame.sequence
                elif now - rate_started >= 5:
                    analysis_fps = (count - rate_count) / (now - rate_started)
                    capture_fps = (grabbed - rate_sequence) / (now - rate_started)
                    decoded_fps = (frame.sequence - rate_decoded) / (now - rate_started)
                    rate_started, rate_count, rate_sequence = now, count, grabbed
                    rate_decoded = frame.sequence
                status = {
                    "run_id": run_id,
                    "monitoring": True,
                    "state": "analyzing",
                    "frames_analyzed": count,
                    "captured_at": frame.captured_at.isoformat(),
                    "model": config.model.name,
                    "inference_backend": config.backend,
                    "inference_ms": round(inference_ms, 2),
                    "analysis_fps": round(analysis_fps, 2),
                    "capture_fps": round(capture_fps, 2),
                    "decoded_fps": round(decoded_fps, 2),
                    "capture_age_ms": round((now - frame.monotonic_seconds) * 1000, 2),
                    "captured_frames": frame.captured_frames,
                    "frames_decoded": frame.sequence,
                    "detections": detection_values,
                    "people_visible": sum(d.class_id == 0 for d in detections),
                    "tracks": observations,
                    "snapshots": {
                        "written": person_snapshots.written,
                        "dropped": person_snapshots.dropped,
                        "errors": person_snapshots.errors,
                    },
                    "person_arrivals": person_arrivals,
                    "road_zone_status": activities.zone_status,
                    "parking": {"availability": "unknown", "available_spaces": None},
                }
                last = frame
                next_due = now + 1 / config.analysis_fps
                if now - last_write >= 0.5 or new_person:
                    write_json(report, status)
                    last_write = now
                if now - last_preview >= 1 / config.preview_fps:
                    preview = annotate(
                        frame.image,
                        detections,
                        f"Objects {len(detections)} | {analysis_fps:.1f} FPS",
                    )
                    save_snapshot(
                        Frame(preview, frame.sequence, frame.captured_at, frame.monotonic_seconds),
                        snapshot,
                        jpeg_quality=75,
                    )
                    last_preview = now
    except KeyboardInterrupt:
        reason, exit_code = "interrupted", 130
    except Exception:
        reason, exit_code = "failed", 2
        raise
    finally:
        if person_snapshots is not None:
            person_snapshots.close()
        status.update(
            monitoring=False, state="stopped", reason=reason, process_peak_rss_mib=peak_memory_mib()
        )
        write_json(report, status)
        if last is not None:
            preview = annotate(
                last.image,
                detections,
                f"Stopped | people last seen: {status['people_visible']}",
            )
            save_snapshot(
                Frame(preview, last.sequence, last.captured_at, last.monotonic_seconds),
                snapshot,
                jpeg_quality=75,
            )
    print(json.dumps(status))
    return exit_code
