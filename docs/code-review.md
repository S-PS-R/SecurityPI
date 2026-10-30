# Function review and regression record

October 30, 2026. Review covers every named function/method/nested helper in the owned Python modules; unchanged functions are explicitly retained when their contracts remain appropriate. This is a source review plus measured regressions, not certification of field accuracy.

## Scope

| Module | Named functions | Review disposition |
|---|---:|---|
| `__init__.py` | 0 | Version declaration only. |
| `__main__.py` | 0 | CLI entry point only. |
| `activity.py` | 3 | Reviewed brightness evidence, road-zone invalidation and bounded per-track state; retain conservative unknown states. |
| `api.py` | 9 | Fix preview timestamp check to use the opened file descriptor; preserve loopback routes, auth boundary and bounded responses. |
| `capture.py` | 24 | Retain single camera ownership, demand decode, native-call timeout/reconnect and child release. No extra capture thread/model added. |
| `capture_cli.py` | 4 | Retain config override validation, storage-confined artifact paths, EOF/interrupt behavior and release-before-encoding. |
| `cli.py` | 1 | Reviewed every command dispatch, lazy optional imports and argument validation; keep existing command contracts. |
| `config.py` | 7 | Reviewed every validator and path resolver; retain strict bounds and secret-safe errors. |
| `dataset.py` | 3 | Retain finite collection, restart timing, exclusive sample creation and review preservation; completed pilot stays blocked. |
| `history.py` | 5 | Correct legacy 14-day track retention to seven days; reuse the same day constant in metadata and expiry. |
| `labels.py` | 0 | Reviewed COCO mapping; no class/model label changes. |
| `logging.py` | 3 | Retain JSON logs without raw config/credentials. |
| `models.py` | 2 | Retain explicit pinned download, size/hash checks, bounded directory and failed-download cleanup. |
| `notifications.py` | 9 | Reviewed candidates, redirect refusal, durable outbox, retries/cancellation, dedup and worker lifecycle; no phone sends during review. |
| `scene.py` | 5 | Retain scene movement checks and bounded geometric candidates. Unknown parking/visibility remains intentional, not dead code to delete. |
| `snapshots.py` | 7 | Remove duplicate pre-write scan; use one lstat and ISO timestamp parse per owned regular file; preserve quotas/expiry/private permissions. |
| `soak.py` | 7 | Reviewed process-family resources, child termination and finite loop; add a preflight refusal when a fresh analyzer already owns monitoring. |
| `state.py` | 4 | Retain schema validation, bounded reads and stale/future timestamp rejection; old artifacts remain compatible. |
| `thermal.py` | 21 | Move Linux-only fcntl import behind platform guard; retain finite loads, kernel-curve verification, LED restoration and safety stops. No stress runs resumed. |
| `tracking.py` | 4 | Reviewed observation timing, short-gap identity, stationary anchors and bounded metadata; retain notification semantics. |
| `vision.py` | 6 | Reuse float32 NCHW tensor with exact pixel equivalence; retain original no-output-buffer helper path, model sizes/classes/thresholds and CPU backend. |
| `vision_cli.py` | 5 | Reviewed benchmark isolation, annotations, source lifecycle and bounded writers; no competing camera or silent model switch. |

Owned named definitions reviewed: **129**. Protocol methods are included. Vendored ByteTrack base, Kalman, matching and association functions were reviewed at the adapter boundary and for bounded removed-track state; upstream attribution/license and algorithm are retained. No broad vendor reformat/rewrite.

## Reproductions and changes

- Snapshot-named directories were incorrectly counted as JPEGs; new regression failed before the regular-file fix. Invalid dates, symlinks and unrelated files remain excluded.
- A preview replacement could make fresh path metadata validate stale bytes already opened; the replacement-race regression returned200 before the fix and503 after it.
- Track history reported14 days despite the established seven-day policy; an eight-day track regression failed before correction.
- Windows test collection could import Linux-only fcntl; platform guard/lazy import and portable pure-function tests preserve CI coverage. Actual baseline Windows CI also exposed POSIX-only permission assertions and an oversized parametrized test ID overflowing the Windows environment; permission checks are now platform-specific and IDs are bounded.
- Relative history paths could raise ValueError before SQLite error handling; resolving the read-only URI now returns unavailable without creating a database.
- Soak preflight now rejects an existing fresh analyzer or occupied API port before starting children or writing run artifacts.
- A caller-owned reusable model tensor now avoids per-frame float-array allocation. Eight image shapes, two successive random frames each, are bit-identical to the original OpenCV tensor conversion.

## Measured results

- Snapshot inventory: alternating scans over the same1,000 synthetic files, nine measured per method after warmup: median74.236→42.597ms (42.6% lower). Temporary files were automatically removed. One gallery scan per completed write replaces two. This is not an end-to-end inference FPS claim.
- Conversion-only probe, square640 BGR,35 alternating measured samples:8.562→2.398ms; exact float32 equality. This measures conversion, not full inference.
- Actual pinned model: all12 existing images and all23 detections exactly match the previous input-conversion path; no weights, confidence threshold, camera settings or inference threads changed. Unlabelled agreement is not field accuracy.

| Live measurement, 30-second windows | Before | After |
|---|---:|---:|
| Median analysis FPS | 4.09 | 4.17 |
| Median inference milliseconds | 197.775 | 199.005 |
| Median service memory MiB | 154.80 | 149.63 |
| Median capture age milliseconds | 11.85 | 12.24 |
| Maximum capture age milliseconds | 14.11 | 13.99 |
| CPU cores consumed | 1.665 | 1.678 |
| CPU temperature °C | 53.45 | 53.45 |

These short windows demonstrate maintained operation around 4.1 FPS, not a statistically established end-to-end speedup or CPU reduction. The controlled conversion/inventory probes isolate their respective savings.

## Operational verification

After each source batch, focused tests plus real authenticated Home Assistant API/camera and live model freshness/class checks are performed. Analyzer changes use its existing user service; real-model comparisons pause/restore that worker, never run a competing detector. API reload requires an administrator terminal step. No synthetic notifications are sent; the deferred person/iPhone field test remains pending.

Local verification: **178 tests passed**, Ruff checks passed, 54 Python files already formatted, dependency consistency passed, and no whitespace errors. Baseline GitHub Ubuntu Python 3.11/3.12 passed; baseline Windows failures informed the portability fixes above. Follow-up CI is reported in the linked commit checks.

The analyzer runs the reviewed code and authenticated Home Assistant API/camera checks passed. The system API remains on its previous process until the requested administrator restart; its new preview/history/storage behavior is verified by regression tests but is not yet claimed as deployed. Deferred person/iPhone and field-accuracy acceptance remain pending.

## Cleanup and publication

Baseline source and sanitized test history were published as commit6b9919f before raw artifact deletion. Cleanup removed173 generated files plus temporary conversion tools:63,097,979 bytes (60.17 MiB). Models, private training/reviews, live HA database/media, configuration, credentials, outbox and Tailscale remained protected. Source regression tests are retained. No raw camera data or private device details were uploaded.

## Function inventory

- **activity.py:** `light_evidence`, `Activities.__init__`, `Activities.update`.
- **api.py:** `create_app`, `create_app.health`, `create_app.no_cache`, `create_app.status`, `create_app.vision`, `create_app.track_history`, `create_app.storage`, `create_app.notifications`, `create_app.preview`.
- **capture.py:** `FrameSource.read`, `FrameSource.close`, `FrameSource.__enter__`, `FrameSource.__exit__`, `SyntheticSource.__init__`, `SyntheticSource.__enter__`, `SyntheticSource.__exit__`, `SyntheticSource.read`, `SyntheticSource.close`, `_finite`, `_backend`, `_send_frame`, `_usb_frames`, `_opencv_worker`, `NativeSource.__init__`, `NativeSource.__enter__`, `NativeSource.__exit__`, `NativeSource._receive`, `NativeSource._connect`, `NativeSource._reset`, `NativeSource.read`, `NativeSource.close`, `create_source`, `save_snapshot`.
- **capture_cli.py:** `add_capture_arguments`, `camera_config`, `artifact_path`, `run_capture`.
- **cli.py:** `main`.
- **config.py:** `CameraSettings.nonempty_video_path`, `CameraSettings.validate_file_source`, `StorageSettings.nonempty_directory`, `HomeAssistantSettings.require_phone`, `HomeAssistantSettings.no_inline_credentials`, `ActivitySettings.valid_polygon`, `load_settings`.
- **dataset.py:** `DatasetCollector.__init__`, `DatasetCollector.update`, `DatasetCollector._collect`.
- **history.py:** `TrackHistory.__init__`, `TrackHistory.update`, `TrackHistory.flush`, `TrackHistory.close`, `read_tracks`.
- **logging.py:** `JsonFormatter.format`, `logging_config`, `configure_logging`.
- **models.py:** `sha256`, `fetch`.
- **notifications.py:** `notification_candidates`, `NoRedirect.redirect_request`, `send_notification`, `NotificationQueue.__init__`, `NotificationQueue.close`, `NotificationQueue.recent`, `NotificationQueue.tick`, `NotificationQueue._enqueue`, `run_notifications`.
- **scene.py:** `SceneGuard.__init__`, `SceneGuard.check`, `curb_candidates`, `Calibration.__init__`, `Calibration.update`.
- **snapshots.py:** `snapshot_directory`, `inventory`, `cleanup`, `PersonSnapshots.__init__`, `PersonSnapshots.update`, `PersonSnapshots._write`, `PersonSnapshots.close`.
- **soak.py:** `process_usage`, `host_resources`, `limit_reason`, `stop_workers`, `run_soak`, `run_soak.request_stop`, `run_soak.child_limits`.
- **state.py:** `write_json`, `read_json`, `read_json.invalid_constant`, `read_vision`.
- **thermal.py:** `phase_at`, `led_pixels`, `Display.__init__`, `Display.show`, `Display.close`, `safety_reason`, `Workload.__init__`, `Workload.start`, `Workload.stop`, `token_from`, `request`, `Health.__init__`, `Health.run`, `Health.close`, `read_hardware`, `summarize`, `verify_fan_curve`, `run_thermal`, `run_thermal.interrupt`, `load_worker`, `load_worker.preview`.
- **tracking.py:** `PersonArrivals.__init__`, `PersonArrivals.update`, `Tracker.__init__`, `Tracker.update`.
- **vision.py:** `evaluate`, `decode`, `input_blob`, `Detector.__init__`, `Detector._load_onnxruntime`, `Detector.predict`.
- **vision_cli.py:** `annotate`, `peak_memory_mib`, `benchmark_one`, `run_benchmark`, `run_analysis`.
