# Pi verification and test archive

Updated October 30, 2026 (America/New_York). This document preserves measured
results before generated test artifacts are removed from the Pi. It contains no
private images, device tokens, phone identifiers or private network addresses.
The source regression suite stays in `tests/`; generated diagnostics are not a
substitute for those tests.

## Current deployment and limits

- Raspberry Pi 5, 4 GB RAM, 64-bit Debian 13/Pi OS, Python 3.13.5.
- One USB camera owner, 1280×720 MJPEG at 30 FPS capture. Encoded frames are drained
  continuously; decoding occurs on analysis demand. Local analysis/preview caps5 FPS.
- YOLO26n ONNX, fixed640 input, 9,941,957 bytes. ONNX Runtime CPU1.31.1, two intra-op
  threads, one inter-op thread, sequential execution, CPU arena/spinning disabled.
- Shared class filtering: person, car, motorcycle, bus and truck. Filtering reduces
  downstream work, not the bulk of model inference. No training framework/LLM installed.
- Green detection boxes show threshold-qualified model observations immediately.
  Track IDs are internal for event deduplication and observation/snapshot timing.
- One `Person detected.` event per qualifying track after10 observed seconds;
  brief gaps retain identity within the tracking limit but add no observed time.
- Private full-frame JPEGs at5/10/20 observed seconds: at most3 per person track,
  quality80, bounded two-frame write queue, seven-day retention,500 MiB/10,000 caps.
  Hourly cleanup also runs while analysis is stopped. HA Recorder retains7 days.
- Home Assistant Container and authenticated camera/media access have been checked.
  The user confirmed the iPhone dashboard/camera over cellular through private
  Tailscale HTTPS. Actual receipt of a controlled ten-second person alert remains
  unverified: the user explicitly deferred the field check. No test phone pushes sent.
- Parking geometry/occlusion accuracy, physical reconnect, changed lighting and
  representative field accuracy remain acceptance work. No biometric identification.

## Overnight run — October21–22

The requested eight-hour run was interrupted at7h26m28.6s,33m31.4s short. The
supervisor recorded interruption; three workers exited via SIGTERM. Available
logs did not identify the signal sender. No resource-limit stop/software defect
was established, and the run must not be described as a completed eight-hour soak.

| Measurement | Observed result |
|---|---:|
| Telemetry samples |892, approximately30s apart|
| Analysis throughput |1.9977 FPS,2 FPS target|
| Final analysis count |53,509 frames|
| Maximum sampled frame age |2.5s|
| Peak combined worker RSS |428.0 MiB|
| First/last10min median RSS |422.29 /396.36 MiB|
| Peak sampled CPU temperature |68.3°C|
| Median CPU use |1.24 core equivalents|
| Minimum available host RAM |971.31 MiB|

API monitoring was live at all samples; no sampled safety limit was reached.
Subsequent process/device checks confirmed workers absent and camera released.
Raw running flags left after interruption were correctly treated as stale by the
status reader. The run used notification dry-run and established no phone delivery.
RSS counts shared pages repeatedly; decreasing RSS does not prove leak freedom.

## Capture and runtime improvements — October27–28

Matched approximately48s capture windows, before/after demand decoding:

| Metric | Before | After |
|---|---:|---:|
| Analysis FPS |2.688|3.275|
| CPU core equivalents |2.216|1.607|
| Peak camera memory MiB |206.69|182.05|
| Maximum frame age s |1.4|0.9|
| Peak CPU °C |61.7|60.6|

Afterward the camera still drained29.97–30.04 encoded FPS but decoded3.12–3.42 FPS;
maximum measured delivery age18.17ms. OOM counters were zero.

Pixel-preserving resize-before-pad preprocessing reduced its isolated median
15.088→11.943ms across50 synthetic720p runs; exact input tensor equality was
checked across eight sizes, including odd/small/portrait cases. Full-size inference
input was retained. Smaller inputs512/416/320 were incompatible with this fixed graph.

Matched ONNX Runtime rollout, same pinned640-input model:

| Metric | OpenCV CPU | ONNX Runtime CPU |
|---|---:|---:|
| Existing12-image median detector latency |243.57ms|211.34ms|
| Peak process RSS in image benchmark |139.75 MiB|133.09 MiB|
| Separate40s live throughput |3.393 FPS|3.989 FPS|
| Median camera cgroup memory |172.57 MiB|165.88 MiB|
| Mean CPU core equivalents |1.620|1.654|
| Median live inference |238.44ms|204.85ms|

Live throughput improved17.6%. Final telemetry-disabled restart reached3.92 FPS.
All23 retained detections on the12-image comparison matched at IoU≥0.99;
maximum confidence difference3.815e-6. This is backend agreement, not field accuracy.
Post-rollout maximum full artifact age0.97s, acquisition age16.86ms and CPU61.15°C.
Runtime added approximately62 MiB; the duplicate admission install was removed.
Three-thread mode cost substantially more CPU. OpenCV INT8 was slower and lost
observations, so it was rejected. Neither lower-input nor INT8 mode was deployed.

An earlier four-image labelled smoke comparison (IoU0.5, not representative/mAP):

| Model | Size | Median latency | Peak RSS | TP/FP/FN | Precision/recall |
|---|---:|---:|---:|---|---|
| YOLOv8n |12,851,049 bytes|186.02ms|192.36 MiB|5/0/5|1.00/0.50|
| YOLO26n |9,941,957 bytes|195.93ms|159.69 MiB|6/1/4|0.857/0.60|

## Snapshot and Home Assistant checks

Three synthetic noisy720p JPEGs were615,402 bytes each. Enqueue times1.57/1.84/4.76ms;
enqueue plus background completion26.12/17.40/29.66ms. Three writes succeeded,
zero dropped/errors; temporary synthetic images removed. These isolated numbers
are not a measurement of real-person snapshot load with inference running.

A90s combined early deployment smoke analyzed172 frames: steady1.969 FPS,
maximum frame age2.5s, peak camera RSS259.59 MiB, HA cgroup344.23 MiB and API89.69 MiB,
minimum available RAM998.19 MiB, peak CPU62.25°C. Camera release/offline reporting
passed. Onboarding was pending then; later authenticated HA/iPhone checks supersede
that setup limitation, without establishing controlled person-alert receipt.

Authenticated media access, ten-second observation timing, missed detections,
polling retention, separate tracks, duplicate suppression, snapshot limits/failures,
seven-day deletion and training-file preservation have automated regression coverage.

## Cooling comparison — October29 evening

Each case used the same30min profile:5min normal,20min two authenticated HA preview
clients plus periodic history queries and bounded synthetic JPEG writes,5min the
same plus four low-priority single-threaded NumPy CPU workers. Existing camera,
model, inference threads and application service limits stayed unchanged. Each case
completed1,800 samples. A180s passive cooldown followed the lid-off case.

| Metric | Lid off, original | Lid on, original | Lid on, candidate |
|---|---:|---:|---:|
| App peak CPU °C |60.60|73.25|71.60|
| App final5min mean °C |57.14|71.26|69.40|
| CPU-stress peak °C |62.80|76.00|75.45|
| CPU-stress mean °C |60.22|74.10|73.03|
| App mean detection FPS |3.785|3.734|3.666|
| CPU-stress mean detection FPS |1.878|1.821|1.794|
| CPU-stress maximum frame age s |1.8|1.9|2.0|
| App mean HA response ms |4.85|4.88|5.23|
| CPU-stress mean HA response ms |12.72|13.85|13.45|

Original active thresholds50/60/67.5/75°C; candidate45/55/62.5/70°C. Hysteresis5°C
and existing PWM0/75/125/175/250 retained. No active throttling/undervoltage was
recorded in any sample. LEDs displayed CPU temperature at low fixed brightness;
saved original pixels were restored, workers stopped and HA/camera remained healthy.

The candidate application tail changed+0.21°C (not flagged still warming); its CPU
peak tail changed+2.25°C (still warming). The other CPU peaks were also still warming.
The candidate started warmer66.1°C than original lid-on; ambient room temperature
was not instrumented. These are sequential observations, not laboratory isolation
or proof of indefinite equilibrium. Candidate reduced app final-window mean1.86°C,
but both lid-on curves missed the below65°C app/below75°C CPU-peak targets.

The candidate used maximum fan PWM for most application load; its recorded unit
memory peak130.55 MiB stayed below320 MiB. A stronger40/50/60/65°C curve was prepared
but NOT tested or applied by the agent. The user paused further tuning, preferred
lid-off cooling and asked about a more ventilated enclosure. Do not automatically
resume stress testing. Final recommendation: lid off in a protected location or
improve enclosure ventilation, then measure again if requested.

A fan-helper indexing defect was caught by post-reboot verification BEFORE tuned
stress: firmware names stages`fan_temp0`–`fan_temp3`, not1–4. Corrected helper,
regression test and effective-kernel-curve preflight prevent the wrong curve from
being stressed. Do not infer activation from config.txt without a reboot/kernel check.

## October30 cleanup and model experiment

The user chose VS Code; Firefox retained for its smaller installed package footprint.
Chromium/support packages, Thonny and Geany removed: approximately514 MiB installed
file estimates. Browser profiles/configuration preserved; the system browser resolves
to Firefox. Idle application removal is not evidence of runtime RAM/FPS improvement.

A finite30s single-camera profile analyzed112 frames; final reported3.85 FPS,
213.85ms inference and165.73 MiB peak RSS. Service restoration verified afterward.
Cross-thread cProfile accounting was unsuitable for a precise native/Python timing
split; no optimization gain is claimed from that profile.

Temporary ONNX1.23.2/ml_dtypes0.5.4 tools occupied about47 MiB. An isolated ORT INT8
conversion/calibration attempt stopped with`ValueError: No data is collected` after
about6s (440.3 MiB peak). It produced only a9.5 MiB preprocessing intermediate,
not a validated quantized model. No speed/size/accuracy conclusion or deployment
result exists for that attempt. Live services were automatically restored.

Before removal,173 generated diagnostic/test files totaled13,813,143 bytes and
temporary conversion tools49,284,836 bytes: about60.2 MiB targeted for reclamation.
This archive replaces those raw artifacts after its GitHub push is verified.
Production models,12-image private training pilot/reviews, configuration/credentials,
Home Assistant databases/history, private person snapshots, notification outbox,
Tailscale binaries/state and reusable source regression tests are preserved.

## Acceptance still pending

- Controlled person staying in view25s: one generic alert after10 observed seconds,
  snapshots5/10/20, and actual iPhone receipt confirmed by the user.
- Physical reconnect, sustained unattended acceptance and representative field
  accuracy, especially occluded cars and passing people/vehicles.
- The12-image one-day collection is complete; all samples remain unapproved for
  training,11 have uncertain regions. No further collection/training authorized here.
- No Qwen/LLM deployment/training, extra camera worker or public API exposure.
