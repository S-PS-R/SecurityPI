# Lightweight vision candidate

The analyzer uses existing OpenCV DNN/NumPy for COCO ONNX car/person detection.
It adds no PyTorch, Ultralytics Python, SciPy, GUI, or training environment.
ByteTrack's MIT core is attributed under `src/securitypi/_vendor/bytetrack/`;
its only added runtime is `lapx`, pinned in `requirements/vision.txt`.
The Pi venv grew from about 233 to 242 MiB. Two comparison models occupy 21.74 MiB.

## Setup and use

From the checkout, using its native virtual environment:

```sh
.venv/bin/python -m pip install --only-binary=:all: --no-cache-dir -r requirements/vision.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m securitypi model-fetch --config config/local.toml --name yolo26n
```

Downloads are explicit, use the official Ultralytics assets v8.4.0 release, and
verify pinned SHA-256 and exact byte size. Approved models total 22,793,006 bytes;
a 32 MiB download-directory budget prevents accumulated model versions. Existing
differing weights are not overwritten. Model weights retain their upstream
[Ultralytics license](https://www.ultralytics.com/license), independently of this
project's code license. Weights and samples stay in ignored local storage.

Add to ignored `config/local.toml` (model path is relative to TOML):

```toml
[vision]
model = "../data/models/yolo26n.onnx"
threads = 1
analysis_fps = 2.0
calibration_seconds = 300.0
```

```sh
# Bounded smoke check, or continuous analysis until Ctrl+C:
.venv/bin/python -m securitypi analyze --config config/local.toml --seconds 30
.venv/bin/python -m securitypi analyze --config config/local.toml --seconds 0
```

The default processes 2 inference frames/second using one inference thread. A
single camera reader drains USB into one replaceable frame slot: no growing
image queue. There is no video recording, per-frame logging, or stored trajectory
history. Only `data/vision-status.json` and `data/vision-preview.jpg` are replaced
every two seconds and on exit. Explicit `--snapshot`/`--report` paths must remain
inside configured storage. Status contains capture time and stopped/active state;
old observations must not be presented as current counts.

Person and vehicle tracks expose temporary IDs, elapsed time since first seen,
approximate observed time, and stationary duration. Three seconds of loss expires
identity by default, even if processing slows. Short occlusions can preserve an ID;
returning people and ambiguous overlaps can get new IDs. This is not face identity.
Ctrl+C returns 130 and releases capture. The foundation HTTP API remains separate;
no Home Assistant, streaming, alerts, automatic startup or background service is added.

## Automatic calibration and its limits

There are no fixed parking-space polygons or camera coordinates. Vehicles observed
stationary for 30 seconds propose up to four aligned curb-row candidates, with at
least two currently visible, unclipped vehicles per row. Each row learns its own
median projected car span from a bounded history of 120 one-second summaries.
At least 20 consistent summaries are required before a scale is accepted. After
five minutes (configurable), internal gaps can
report an estimated number of cars fitting with a 20% clearance allowance. Large
size variation suppresses estimates rather than accepting unreliable perspective.

ORB background features detect camera translation/rotation/scale and size changes.
Moved or unverifiable scenes invalidate calibration. Camera movement resets tracks.
Restarting analysis learns again. The application keeps bounded current state, not
a training dataset; neural weights do not train themselves on their own predictions.
Confidence thresholds stay explicit defaults. The scene-derived value is car span.

Aligned cars establish a candidate row, not proof of curb visibility, parking
permission, or absence of obstacles. No hidden curb endpoints or completely empty
curb sections are inferred. Gap `estimated_car_capacity` is geometry only:
`availability` stays `unknown` and `visibility_verified=false`. Tree occlusion,
driveways and ambiguous views need further visibility/geometry work before actual
parking availability can be claimed. Missing detections never establish free space.

## Benchmarking

Run the same saved images through each model in a fresh process:

```sh
.venv/bin/python -m securitypi model-fetch --config config/local.toml --name yolov8n
.venv/bin/python -m securitypi benchmark --config config/local.toml \
  --models data/models/yolov8n.onnx data/models/yolo26n.onnx \
  --images data/window-upright-check.jpg data/window-reflection-recheck.jpg \
  --threads 1 --runs 10 --report data/model-benchmark-1thread.json
```

Reports include model size/checksum, input hashes, model-load time, median/p95
preprocessing+inference+postprocessing latency, throughput, CPU core equivalents,
and peak process RSS. Camera, tracking and streaming are excluded. Warm-up is
excluded from latency samples. Input/repeat/model sizes and worker time are bounded.
`--labels DIRECTORY` adds precision/recall at IoU 0.5 for COCO-format text labels
matching image stems; this is not mAP. Unlabelled detection counts are not accuracy.

### Measured Pi 5 baseline, October 20, 2026

Debian 13 ARM64, Python 3.13.5, OpenCV 4.14.0; two saved night images, model input
640-square, confidence 0.15. These short CPU measurements are not a soak test.

| Model | Model MiB | Threads | Median ms | Detector FPS | Peak process MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| YOLOv8n | 12.26 | 1 | 304.88 | 3.28 | 198.67 |
| YOLO26n | 9.48 | 1 | 316.66 | 3.15 | 165.66 |
| YOLOv8n | 12.26 | 2 | 186.07 | 5.38 | 197.89 |
| YOLO26n | 9.48 | 2 | 194.81 | 5.13 | 165.56 |

Initial October 20 default: YOLO26n, one inference thread, 2 FPS analysis. It trades a little speed
for a smaller model and about 33 MiB less process memory here. NCNN remains a
possible future benchmark; it is not installed or claimed fastest locally.

A separate official four-image COCO8 validation smoke set found YOLOv8n 5 true
positives/0 false positives/5 misses and YOLO26n 6/1/4, for people/relevant vehicles
at IoU 0.5 and confidence 0.15. This tiny labelled check verifies real inference,
not field accuracy or a definitive model ranking. The fixed night camera view
misses substantially occluded vehicles, so parking acceptance remains pending.

A 35-second live run processed 70 analysis frames, retained one car's ID, and
reported zero people. A later one-minute one-thread live run stopped with exit 130;
sampled analyzer+camera-worker+resource-tracker RSS peaked at 288.06 MiB (shared
pages counted more than once), versus 285.34 MiB first-half and 288.06 MiB
second-half peaks. This short check does not establish 24/7 memory stability.

Sources: [official ONNX artifacts](https://github.com/ultralytics/assets/releases/tag/v8.4.0),
[OpenCV YOLO integration example](https://github.com/ultralytics/ultralytics/tree/main/examples/YOLOv8-OpenCV-ONNX-Python),
[ByteTrack source](https://github.com/ifzhang/ByteTrack/tree/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99),
and [COCO8](https://github.com/ultralytics/assets/releases/download/v0.0.0/coco8.zip).
Portable tests exercise decoder geometry, labels, tracking/expiry/bounds, row scale,
movement, calibration reset, partial/missing cars and stopped/failure status.
Private evidence and reports remain in ignored `data/`.

## Current observations and stationary vehicle rules

Every detected supported class (person, car, motorcycle, bus, truck) receives a
session-local track number. API and phone observations now preserve the existing
stationary duration and show movement, elapsed/observed times and vehicle activity.
IDs are not identities: occlusion, source gaps, camera movement and restarts can
create new IDs. Missed objects do not get invented track numbers.

Motion is measured in image coordinates using a smoothed centre and an anchor
scaled to object size, with a small minimum tolerance for jitter. Five seconds
without significant displacement defaults to stationary. Slow accumulated drift
resets that timer; a visibility gap resets stationary time instead of counting
unseen time. These are image-motion heuristics, not calibrated speed measurements.

The lightweight light check samples at most one 32x24 crop per vehicle per second.
It reports bright regions or no bright regions visible in dark scenes; daytime,
small/clipped vehicles and inconclusive views report unknown. It is not a trained
headlight detector. Streetlights, reflections, lamps facing away and occlusion
limit the result. A vehicle stationary for 60 seconds with no visible bright lamps
may be labelled possibly parked; that does not establish legal parking, engine
state or an empty space. A stationary car in a configured roadway is never given
that parking label; its stop is reported irrespective of visible lights.

Optional [activity] settings in config/example.toml provide stationary_seconds,
parked_seconds, road_linger_seconds and road_polygon. A polygon is a simple outline
of the roadway, 3–12 normalized [x,y] points for the current rotated camera image.
Vehicle location uses its bottom-centre point. A continuously observed stationary
vehicle in the marked roadway for 30 seconds triggers a roadway-stop candidate.
No road outline means road location is unknown and roadway alerts are suppressed.
A moved or unverifiable scene invalidates the outline until the camera position
and outline are reviewed and analysis restarted. Automatic curb candidates are
not used as proof of road/parking semantics. The roadway is not yet configured on
the local Pi; this is a separate calibration step before road alerts can operate.

No dependencies, models, videos or persistent trajectory history are added. Current
activity memory is limited to currently observed tracks; light evidence is cached
for one second. Existing detection limits cap observations at 100 objects.

Person alerts require ten observed seconds by default. A 100-record/120-second
qualified-event cache bridges the latest-frame output and notification polling
so a person leaving immediately after qualification can still be reported.
The cache retains no photos or clothing descriptors; optional snapshots use a
separate bounded writer. The existing
tracker can match a short occlusion (default loss allowance three seconds); a
longer or ambiguous loss can produce a new ID and therefore a new alert. No
appearance-based re-identification model is installed or claimed.

## Detection display and capture efficiency

The preview draws every current model detection that passes the configured
confidence/NMS limits, for people and road vehicles. Raw detections and notification
tracks are independent. Tracking confirmation cannot hide a detection or reduce
the displayed count. Low-confidence/occluded objects can still be misclassified
or missed; this change is not a field accuracy improvement claim.

The Pi deployment uses two detector threads and5 FPS analysis/preview ceilings,
with the same 640-pixel model input and confidence 0.15. Actual rates vary with host
load. USB input remains 1280x720MJPEG30 FPS. The capture worker continuously drains
encoded frames with grab(), then uses retrieve() only on consumer demand. Only
used pixels cross the process boundary. Sequential video decoding is unchanged.

OpenCV MIL was compared with the existing ByteTrack adapter using a small
synthetic translating texture. MIL was substantially slower even for one object;
this is a throughput comparison, not proof of equivalent field accuracy. KCF and
CSRT are not part of the installed OpenCV build. ByteTrack remains for configured
phone notifications; disabling notifications skips track construction entirely.

Counts and detection confidence are visible on the compact dashboard; only alert
rows show track IDs. Retention and capture metrics are documented in
[the Home Assistant guide](home-assistant.md#detection-display-notification-tracking-and-retained-data).


### People and road vehicles

Live decoding now keeps COCO IDs 0, 2, 3, 5 and 7 (person, car, motorcycle, bus,
truck), before NMS and tracking. Other classes are discarded. This reduces
postprocessing; the existing 80-class ONNX model still performs its full inference.
No inference speedup is promised from class filtering alone. The current fixed
640-pixel model and runtime stay unchanged pending a separate measured comparison.


### CPU inference comparison and smaller allocations

The detector now resizes before padding when the target dimensions are exact
integers and the input is downscaled. This avoids a source-resolution square
allocation. Odd dimensions and upscaling use the original path, preserving edge
pixels. Tests compare the actual float input tensors exactly, including portrait,
odd-size and small images. A synthetic 720p preprocessing probe measured median
15.09 ms before and 11.94 ms after; this is only preprocessing, not overall FPS.

An optional backend runs the same model through ONNX Runtime CPU. Install it with
`python -m pip install --only-binary=:all: -r requirements/onnxruntime.txt`, then set
`vision.backend = "onnxruntime"`. `"opencv"` remains the portable default and rollback
setting. Both backends share preprocessing, class filtering, NMS and box decoding.
No model training, lower input resolution or new weights are needed.

The `benchmark` and `_benchmark-one` commands accept `--backend opencv` or
`--backend onnxruntime`. Benchmark reports name the actual backend. Keep comparisons
sequential and release the existing camera worker when measuring CPU contention.
Do not run two live camera analyzers. The optional backend validates one float32
input of the expected fixed size and one output before inference.

Pi comparison, same YOLO26n 640 input and twelve existing images, two measured
predictions per image after warmup:

| Backend | Threads | Median ms | Peak process RSS MiB | CPU cores |
| --- | ---: | ---: | ---: | ---: |
| OpenCV | 2 | 243.57 | 139.75 | 1.762 |
| ONNX Runtime, default arena | 2 | 209.14 | 166.98 | 1.802 |
| ONNX Runtime, arena disabled | 2 | 211.34 | 133.09 | 1.779 |
| ONNX Runtime, default arena | 3 | 194.78 | 166.38 | 2.391 |

The adapter disables the CPU arena and idle spinning. Two threads balance speed
and resource use; a third used substantially more CPU. All 23 retained detections
matched the OpenCV reference at IoU >= 0.99, with maximum confidence difference
0.00000382. This is backend agreement on a small batch, not field recall or
accuracy; the provisional review labels remain unapproved for training.

The existing model rejected 512/416/320 input shapes. OpenCV INT8 on one probe
image was slower (313.37 ms versus 230.47 ms) and lost the retained detections.
These candidates were rejected and are not live options. Model weights remain
unchanged. Measured live rollout results are recorded in ignored local notes.


The matched live rollout kept 30 FPS USB capture, a 5 FPS analysis/preview ceiling,
two inference threads, the same 640 model input and the same model weights.
Separate 40-second windows measured 3.393 -> 3.989 analyzed FPS (+17.6%), median
camera-cgroup RAM 172.57 -> 165.88 MiB, peak RAM 176.17 -> 168.86 MiB and CPU
1.620 -> 1.654 core equivalents. Median inference was 238.44 -> 204.85 ms.
Maximum full observation age was 0.97 seconds after rollout; no cgroup OOM events
occurred. These are short live measurements with no qualifying person event;
they do not replace the deferred physical alert/snapshot or field-accuracy check.
The local Pi now selects the optional backend; the portable example stays OpenCV.
