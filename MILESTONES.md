# SecurityPI — Raspberry Pi 4 Smart Security System

Created: October 11, 2026. Tool assessment added: October 12, 2026.

## Established-tool assessment before implementation

See [TOOL_ASSESSMENT.md](TOOL_ASSESSMENT.md) for vetted upstream components. The user accepted the recommendation on October 12: use the official Home Assistant iPhone app with our lightweight Python parking/activity service. MediaMTX/FFmpeg are the preferred independent media path; Frigate remains conditional on suitable detector hardware. Dependency admission is recorded in [docs/dependencies.md](docs/dependencies.md).

Public **`S-PS-R/SecurityPI`** creation and implementation pushes are authorized. Repository creation/push status is tracked in the evidence log below. The foundation no longer requires a custom PWA or Node.js build.

## Goal and confirmed equipment

Develop on Windows laptops, push implementation milestones to GitHub, and deploy to a Raspberry Pi that runs independently 24/7. Provide person/vehicle detection, parking occupancy, event recordings, live viewing, and iPhone notifications.

- Raspberry Pi 4 with 4 GB RAM, running Raspberry Pi OS.
- Logitech/Logi HD 1080p USB webcam; exact model and capture formats to verify.
- Sense HAT V2 installed, with a fan on the main board.
- Camera looking outside through a window.
- iPhone companion; Windows-only development computers, no Mac available.
- User has provided GitHub access and authorized implementation pushes. Identify the intended repository/remote when implementation starts.

The Pi must capture, analyze, and record without the development PC or internet. Push delivery requires internet. Remote viewing requires connectivity to the Pi. Hardware gates stay pending until tested on the Pi and iPhone; Windows/Linux CI cannot establish ARM camera support, thermal behavior, or Safari compatibility.

The [original PyImageSearch guide](https://pyimagesearch.com/2019/03/25/building-a-raspberry-pi-security-camera-with-opencv/) inspires capture/event recording, but its refrigerator light-change detector does not meet this scope. Write our own implementation and verify current dependencies.

## Recognition and event semantics

Use pretrained person/vehicle object detection, temporary object tracking, and calibrated zones. Face identity, plates, vehicle ownership, and criminal intent are separate features, outside v1.

| Use case | Method | App output |
| --- | --- | --- |
| Parking availability | User-drawn space polygons, vehicle association, stable occupancy over time | Free / occupied / unknown, with observation age |
| Person at front door | Person foot point enters a doorstep zone with persistence | Person at front door |
| People walking past | Track sidewalk-zone entry or directional line crossing | Person passed by; alerts off by default |
| Activity near a car | Person remains near a monitored vehicle/zone; optionally repeated approaches | Person lingering near vehicle — review clip |

A lingering event is a heuristic, not proof of a break-in. Owners, deliveries, and neighbors can trigger it. Actual tampering recognition needs a separately validated behavior model or corroborating sensors. Record observable activity and evidence first.

Assess only visible configured parking areas. Missing detections alone do not establish a free space: require usable visibility, healthy frames, and consistent evidence. Darkness, occlusion, stale frames, or camera movement produce unknown. For an unmarked curb start with user-defined candidate areas; estimating enough physical clearance for a specific car needs calibration and is a later extension. Availability does not establish parking permission.

## Recommended implementation

**Python** for capture, inference, rules, storage, and backend: OpenCV/NumPy, FastAPI, SQLite metadata/outbox, and pytest. Keep camera, detector, storage, and notification interfaces replaceable. Synthetic frames and recorded video allow development without Pi hardware.

**Official Home Assistant iPhone app** for camera viewing, parking/health tiles, event notifications, and controls. Reuse its dashboard, sessions, mobile notification services, and documented interfaces rather than implementing a custom app. Keep Pi OS; Home Assistant Container is the proposed installation route, subject to combined resource measurements. See [the integration plan](docs/home-assistant.md) and [official phone notifications](https://companion.home-assistant.io/docs/notifications/notifications-basic/).

A custom PWA is now an optional later extension. No Mac, native app build, or Node.js is required for our foundation. Home Assistant is not installed or connected in milestone 1.

**MediaMTX** for streaming: prefer WebRTC and provide HLS fallback. [MediaMTX browser documentation](https://mediamtx.org/docs/read/web-browsers) describes both, noting HLS's higher latency and codec/connectivity requirements. Prototype Safari playback early. MJPEG can support debugging but is not the main phone stream.

Use one camera owner and share its output with analysis, recording, and streaming. Prototype OpenCV capture on Windows; choose a tested V4L2/OpenCV or FFmpeg production path on Pi after checking webcam formats. Do not assume the Logitech camera outputs H.264. Benchmark decoding/encoding, avoid multiple encodes, and do not have competing processes open the webcam. If a media process owns capture, Python consumes its shared feed.

Benchmark **EfficientDet-Lite0 int8** and a smaller **SSD MobileNet** model through a detector adapter. [Google's model documentation](https://developers.google.com/edge/mediapipe/solutions/vision/object_detector) describes these lightweight accuracy/latency tradeoffs. Verify the selected LiteRT/TFLite or alternative runtime on Windows and ARM64, input preprocessing, label map, license, source, and checksum. Do not assume every Python version has an ARM wheel. Use important-region crops when distant objects become too small after full-frame resizing.

Starting benchmark settings: model-sized crops or 640×480 analysis, 1–3 inference cycles/second, and 720p streaming at 10–15 FPS. These are provisional, not performance promises. Short events can be missed at low inference rates. Analyze parking periodically even without motion, since parked cars are stationary. Drop old analysis frames and bound queues rather than accumulating delay.

Pipeline: USB capture → shared media/analysis feed → detector/tracker → parking and zone rules → evidence + event/outbox → Home Assistant adapter → dashboard/mobile notifications. MediaMTX serves live video independently of inference; FastAPI exposes domain state. Prefer supported Home Assistant integration/MQTT discovery for durable entities; a raw REST state update alone is not a complete entity integration.

## Private access and notifications

- Prefer Tailscale on Pi/iPhone with explicit device access rules; test authenticated video/clip access over Wi-Fi and cellular/VPN.
- Protect the domain API and media management endpoints before network exposure. Milestone 1 permits loopback binding only and implements no camera, evidence, or mutation endpoints.
- Reuse Home Assistant account/device registration and mobile-app notify actions. Store service tokens in environment variables or protected files excluded from Git; never embed them in configuration URLs or logs.
- Persist event retries/expiry/deduplication; cooldowns and notification preferences remain in our rules/adapter. No private footage or unlock tokens in notification summaries.
- Home Assistant display entities must preserve free/occupied/unknown and stale/offline semantics. Offline camera is not evidence of free parking.
- Trusted HTTPS/private access and compatible codecs are validated for real iPhone viewing. HTTPS signaling alone does not solve WebRTC media reachability; retain HLS fallback.
- Default alerts: doorstep and configured lingering; parking transitions opt-in, ordinary sidewalk traffic quiet. Test actual iPhone permissions/Focus/locked-phone behavior. No guaranteed emergency delivery claim.
- The phone app can be closed while Pi analysis/recording continue. Push requires external connectivity; local-push behavior has platform/network limitations.

## Window view, Sense HAT, and 24/7 operation

Validate the actual window view in daylight and darkness before substantial app work. Mount securely near glass, minimize indoor reflections, and consider a dark hood. Test sun glare, rain, headlights, window screens, lighting, and object pixel size at the curb/door. If a camera has IR emitters, avoid pointing them into glass; [Axis documents reflections from windows and other reflective objects](https://whitepapers.axis.com/en-us/ir-reflections-in-dome-cameras). This webcam's night capability is unknown. Software cannot recover uncaptured detail. One view may not adequately cover both parking and the door; change placement or add another view if tests require it.

Sense HAT is an optional status/arm-control accessory, not a person detector or AI accelerator. Mock it on PC; verify V2 pin use, fan connection, cable clearance, and airflow. Dim/disable LEDs near the window to avoid reflection. Read CPU temperature/throttling from Pi OS; HAT ambient temperature is not a CPU reading. See [Sense HAT documentation](https://www.raspberrypi.com/documentation/accessories/sense-hat.html).

Use systemd supervision, bounded queues/buffers, log rotation, disk retention, camera reconnect, graceful shutdown, and update rollback. Measure inference + encoding + recording + phone viewer together on this 4 GB Pi. The fan helps cooling but does not establish throughput. Prefer Ethernet when practical. Evaluate existing storage capacity/write endurance; USB SSD or high-endurance SD may be appropriate, but purchases wait for measurements. Estimate recording write budget and reserve free disk space.

Expose CPU/RAM/temperature/throttling, disk usage, frame age, and inference age. Mark degraded states. A powerless Pi cannot send its own offline alert; reliable complete-outage detection needs an optional external heartbeat monitor. Normal operation must not require a Windows laptop left running.

## GitHub push policy

Each milestone is a coherent push with focused commits, relevant passing checks, updated instructions, and evidence recorded below. GitHub implementation pushes are authorized; resolve the intended remote first. Milestone 1 implements the local foundation; hardware features remain pending.

Exclude credentials, device tokens, recordings, databases, virtual environments, and generated artifacts from Git. Use generated or explicitly shareable fixtures; no private footage in CI artifacts. Pin sources and record model/dependency licenses. Hardware-dependent work may be pushed as a candidate but remains incomplete until hardware checks pass.

## Milestones

### Push 0 — Revised scope and constraints

- [x] Record confirmed hardware, Windows-only development, iPhone, and GitHub authorization.
- [x] Add parking, detection, streaming, and iPhone notifications to the core scope.
- [ ] Record exact camera formats, Pi OS version/architecture, iOS version, field of view, storage capacity, and retention preference.
- **Acceptance:** constraints and outstanding feasibility checks are explicit.
- **Commit:** `docs: plan parking detection and iPhone companion`

### Push 1 — Repository and reproducible foundations

- [x] Research established tools/APIs/CLIs/MCP options; record source quality and hardware limitations in `TOOL_ASSESSMENT.md`.
- [x] Select Home Assistant's official iPhone app; document the integration architecture.
- [x] Initialize Git/create public GitHub remote; add README, MIT license, ignore rules, and example configuration.
- [x] Create `src/securitypi/`, `tests/`, `app/` integration documentation, `docs/`, `deploy/`, and `pyproject.toml`.
- [x] Choose Python 3.12 (foundation supports 3.11–3.13); pin runtime/test requirements and document separate Pi setup. Node is unnecessary for the accepted app approach.
- [x] Add CLI, config validation, JSON logging, and local FastAPI health/status foundation.
- [x] Complete fresh Windows environment checks: 15 tests, lint/format, CLI, dependency consistency, and real localhost HTTP smoke test.
- [ ] Verify Windows/Linux GitHub Actions runs after push.
- **Acceptance:** fresh Windows setup and CLI work; invalid config fails clearly without secret values; lint/tests/CI pass without hardware or credentials. Home Assistant integration documentation replaces the custom PWA shell/build criterion.
- **Commit:** `chore: scaffold Python foundation and Home Assistant integration plan`

### Push 2 — USB capture and window feasibility

- [ ] Implement synthetic/video/webcam sources, timestamps, clean shutdown, and bounded recovery.
- [ ] Verify webcam on PC/Pi and enumerate supported formats, resolutions, frame rates.
- [ ] Test real window placement day/night; record door/parking coverage and blind spots.
- **Acceptance:** capture and reconnect work; real samples establish usable detail and any required placement changes.
- **Commit:** `feat: capture USB video and validate window view`

### Push 3 — Person and vehicle inference

- [ ] Implement detector adapter; compare lightweight pretrained models using real inference.
- [ ] Add relevant class filters, confidence thresholds, normalized coordinates, crops, and debug overlays.
- [ ] Maintain a fixed annotated evaluation set separate from tuning samples; record model provenance.
- **Acceptance:** inference works on PC; report precision/recall and misses across day/night/door/parking scenarios. Mocked detections alone do not establish accuracy.
- **Commit:** `feat: detect people and vehicles with local inference`

### Push 4 — Early Pi performance and iPhone video gate

- [ ] Verify selected inference runtime on Pi ARM64; prototype shared capture with MediaMTX and sample recording.
- [ ] Test Safari WebRTC/HLS over trusted HTTPS with inference active; compare webcam formats/encoding paths.
- [ ] Record CPU/RAM/temperature/throttling, inference rate, stream FPS, latency, and dropped frames.
- **Acceptance:** achievable settings are documented before the full app build; record whether acceleration/offload is needed. No 1080p/full-rate AI promise without evidence.
- **Commit:** `perf: validate Pi analysis and iPhone streaming`

### Push 5 — Tracking and calibrated zones

- [ ] Add temporary track association/expiry, person foot points, polygons, directional crossings, and camera-movement invalidation.
- [ ] Handle reconnect, timestamps, repeated detections, and reset; tracks are not identities.
- **Acceptance:** deterministic trajectories verify enter/exit, lingering, cooldown, occlusion expiry, and reset; replay real clips to evaluate association failures.
- **Commit:** `feat: track objects and evaluate scene zones`

### Push 6 — Parking occupancy

- [ ] Implement free/occupied/unknown per space, vehicle association, hysteresis, and observation age.
- [ ] Include stationary cars, relevant vehicle types, periodic analysis, visibility gates, and calibration versioning.
- **Acceptance:** annotated cases cover arrivals/departures, adjacent overlap, passing traffic, darkness, occlusion, stale frames, and camera loss. Proposed target: 90% correct occupancy on clearly observable labeled samples; report unknown rate and false-free cases separately. Final targets follow hardware measurements.
- **Commit:** `feat: estimate parking-space occupancy`

### Push 7 — Doorstep and vehicle activity rules

- [ ] Add doorstep, passing, and lingering-near-vehicle events with persistence/cooldowns and explanations.
- [ ] Define arm/disarm behavior; parking may run independently of security alerts/recording.
- **Acceptance:** evaluate positives and negatives including owners, delivery, pedestrians, repeated approaches, no vehicle, and visibility loss. Report false alerts; avoid claiming crime detection.
- **Commit:** `feat: add doorstep and vehicle activity events`

### Push 8 — Evidence and offline resilience

- [ ] Save snapshots, bounded pre/post-event clips, UTC metadata, SQLite records/outbox, and interrupted-file status.
- [ ] Prefer shared encoded output over huge raw buffers; add safe retention, active-file protection, low-disk handling, and log rotation.
- **Acceptance:** clips play on iPhone; camera/disk/network failure checks pass; cleanup cannot delete unrelated files; one-hour PC run has bounded resources.
- **Commit:** `feat: persist evidence and bound local storage`

### Push 9 — Authenticated integration and private access

- [ ] Add protected domain API/evidence/settings access and a documented Home Assistant entity integration or MQTT discovery adapter with expiry/availability.
- [ ] Reuse Home Assistant sessions/device registration; protect MediaMTX reads/signaling and management APIs, service tokens, and authenticated commands.
- [ ] Test Wi-Fi/cellular/VPN, trusted endpoints, media reachability, and HLS fallback.
- **Acceptance:** untrusted clients cannot read clips/streams or mutate settings; revoked access is enforced; stale states and reconnect behave safely.
- **Commit:** `feat: integrate protected state and private camera access`

### Push 10 — Home Assistant iPhone dashboard

- [ ] Configure live camera, parking-space tiles, event links, health, and acknowledged arm/settings controls in Home Assistant.
- [ ] Install/configure the official iPhone app; verify offline/stale display and foreground playback.
- **Acceptance:** all screens and clip/live links work on the real iPhone over Wi-Fi/cellular private access; Pi monitoring continues with the phone app closed. No custom app/native build is required.
- **Commit:** `feat: add Home Assistant security dashboard`

### Push 11 — Home Assistant mobile notifications

- [ ] Add the notification adapter using documented mobile-app actions, protected credentials, and a mock test transport.
- [ ] Implement persisted retry/expiry/deduplication, preferences/quiet periods, and protected evidence links.
- **Acceptance:** actual locked iPhone receives with app closed; test permission denial, Focus, network loss/restart, and Wi-Fi/cellular. Record latency and ensure expired alerts do not appear fresh.
- **Commit:** `feat: send iPhone alerts through Home Assistant`

### Push 12 — Pi deployment and optional Sense HAT

- [ ] Document cloning a pinned release, dependencies/media services, protected secrets, and existing Pi OS configuration.
- [ ] Add unprivileged systemd services, restart/backoff, health, update/rollback, and dependency ordering.
- [ ] Add optional HAT status/joystick adapter and PC mock; verify fan/GPIO coexistence and LED-off window/night mode.
- **Acceptance:** reboot automatically starts services; camera/media restart recover; HAT absence does not stop recording. Offline recording works; power interruption leaves recoverable state.
- **Commit:** `feat: deploy supervised Pi services and HAT status`

### Push 13 — 24/7 reliability validation

- [ ] Run a 72-hour Pi soak with inference/recording/retention, day/night scenes, periodic iPhone viewing, and push.
- [ ] Exercise reconnect, internet/VPN loss, low disk, restart/reboot; measure event latency and false-alert rate.
- [ ] Review permissions, dependency risks, model licenses, secret handling, pairing/revocation, and media access.
- **Acceptance:** no crashes, unbounded resources, or accumulating analysis delay; agreed performance budget met; unknown/degraded states and recovery work. Publish thermal/throttling data and remaining limitations.
- **Commit:** `test: validate continuous operation and failure recovery`

### Push 14 — Release v1.0

- [ ] Finish installation, calibration, Home Assistant iPhone/notifications/VPN, retention, troubleshooting, and update/rollback guides.
- [ ] Reproduce setup from GitHub on PC/Pi and actual iPhone; tag only after core hardware gates pass.
- **Acceptance:** detect/track → zone/parking rules → record → notify → live/review flow works from documentation without a development laptop. Release notes include measured limits and blind spots.
- **Commit:** `docs: release SecurityPI v1.0 with verified hardware limits`

## Later extensions

- Second camera if one view cannot cover the door and curb; remeasure workload.
- Accelerator or separate always-on inference host only if measurements justify it; check compatibility before purchasing. Sense HAT is not neural acceleration.
- Behavior classification with held-out evaluation and optional corroborating sensors.
- Face identity, plates, make/model, and metric curb-space estimation as separate optical/calibration projects.
- Custom PWA/native app only if a specific Home Assistant interface limitation justifies additional maintenance.
- Optional cloud backup and external complete-outage monitoring.

## Model strategy for development

Retain GPT-6.1 Sol with medium reasoning as proposed default; Luna for scoped routine changes and Astra for difficult design/debugging if needed. [Official model guidance](https://developers.openai.com/api/docs/guides/model-selection) was checked October 11, 2026. Tests and hardware evidence establish quality; cheaper models are not guaranteed to match the strongest model. Work one milestone at a time with concise reports to limit usage. The deployed detector is a local vision model, not a cloud LLM; no OpenAI API subscription is required by the system.

## Push evidence log

| Push | Commit/tag | Checks/result | PC/Pi/iPhone evidence | Status |
| --- | --- | --- | --- | --- |
| 0 | Pending | Revised roadmap and confirmed hardware | Document only; not pushed | Drafted |

Next implementation task: resume milestone 1 using the assessed components. Public `S-PS-R/SecurityPI` is authorized; creation/push remains pending. Home Assistant is selected; retain hardware acceptance gates.
