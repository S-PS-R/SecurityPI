# SecurityPI: established tools, APIs, CLIs, and MCP assessment

Checked October 12, 2026. Research only: no project dependencies installed, no code scaffold created, and no repository created or pushed. Public `S-PS-R/SecurityPI` creation is authorized for the subsequent implementation.

## Accepted architecture (October 12, 2026)

The user accepted the recommendation: Home Assistant's official iPhone app with a lightweight local Python domain service, and established media/inference components added only when needed. This historical assessment predates implementation. Current implementation/verification status lives in README and the milestone evidence log. Frigate remains a conditional alternative, not an installed dependency.

## Recommendation

Build a small integration and parking-rule project around maintained components. Do not implement codecs, WebRTC transport, an inference runtime, or a tracker from scratch. Keep the choice of phone interface open: the user wants to understand the existing app's role before choosing it.

For the existing Pi 4/4 GB/USB webcam, the conservative baseline is **FFmpeg + one media server + one lightweight local inference runtime + reusable tracking/zone helpers + our calibrated parking rules**. Use an established phone interface if desired. Benchmark combined capture, encoding, inference, recording, and viewing before declaring any configuration suitable for 24/7 operation.

**Frigate is the strongest complete-system reuse candidate**, but it is conditional on hardware suitability. It already has detection/tracking, stationary-object handling, recordings, zones/loitering, HTTP/MQTT interfaces, an iPhone-installable PWA, and Web Push. Its docs describe CPU detection as testing-only and recommend acceleration. The existing Pi has no confirmed neural accelerator. This is a hardware-fit limitation, not a quality rejection. See [overview](https://docs.frigate.video/), [detectors](https://docs.frigate.video/configuration/object_detectors/), [zones](https://docs.frigate.video/configuration/zones/), and [stationary objects](https://docs.frigate.video/configuration/stationary_objects/).

## Evidence and selection criteria

I checked upstream repositories through GitHub metadata and release endpoints, plus primary documentation. Approximate star counts below were observed on the assessment date. All repositories listed with counts were unarchived. Stars establish adoption, not correctness or security. Maintenance, documented interfaces, release cadence, license, platform support, and our own hardware checks matter too. This is not a source-code security audit.

| Component | Upstream adoption | Useful interface / existing capability | Decision and limitation |
| --- | --- | --- | --- |
| [Home Assistant Core](https://github.com/home-assistant/core) | 91k stars; release 2026.10.1, Oct 10 | Official MCP, REST/WebSocket APIs, dashboards, automations | Strong optional app/automation foundation; combined workload still needs measuring |
| [Official Home Assistant iOS app](https://github.com/home-assistant/iOS) | 2.4k stars; maintained alongside Core | Existing native iPhone interface and notification delivery | Saves phone-app work; does not perform our camera inference |
| [Frigate](https://github.com/blakeblackshear/frigate) | 36.5k stars; v0.18.0, Sep 12 | NVR, detection/tracking, zones, clips, HTTP/MQTT, PWA/push | Prefer over rebuilding an NVR if hardware gate passes; CPU-only Pi deployment is not the recommended production path |
| [MediaMTX](https://github.com/bluenviron/mediamtx) | 20.4k stars; v1.21.2, Oct 8 | Media server, recording, WebRTC/HLS/RTSP, documented control API | Preferred independent media server for the lightweight path |
| [go2rtc](https://github.com/AlexxIT/go2rtc) | 14.4k stars; v1.9.14, Jan 19; repository activity Sep 6 | HTTP API, camera protocol bridges, USB webcam support through FFmpeg | Strong alternative, especially within Frigate/Home Assistant; do not deploy a duplicate media stack |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | 65k stars; current upstream activity | `ffmpeg`/`ffprobe` CLIs for capture, codecs, recording, media inspection | Reuse; verify camera formats and Pi acceleration rather than assuming them |
| [OpenCV](https://github.com/opencv/opencv) | 91k stars; current upstream activity | Python/native APIs for image processing and calibration | Reuse only required modules; avoid unnecessary GUI/contrib dependencies |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | 22k stars; v1.31.0, Oct 9 | CPU inference API; documented Windows x64/Linux ARM64 packages | Benchmark candidate; compatible model and target Python wheel must be verified |
| [Google LiteRT](https://github.com/google-ai-edge/LiteRT) | 3.5k stars; official Google project, current activity | On-device inference for compatible models | Alternative runtime candidate; select one runtime after testing, not both by default |
| [Roboflow Supervision](https://github.com/roboflow/supervision) | 51k stars; current activity | Reusable detections, zone/annotation/tracking tooling | Evaluate required helpers/current tracker API before implementing our own algorithms; assess dependency weight on Pi |
| [Ultralytics](https://github.com/ultralytics/ultralytics) | 62k stars; frequent releases | YOLO inference/export tooling | Model candidate, not automatic dependency; upstream AGPL-3.0 and model terms require an explicit license decision |
| [Tailscale](https://github.com/tailscale/tailscale) | 37k stars; current activity | VPN CLI, device access rules, private HTTPS Serve | Reuse for private remote access; account/service terms are separate from source license |
| [GitHub CLI](https://github.com/cli/cli) | 47k stars; current activity | `gh repo create`, PR/workflow commands | Official CLI is appropriate for the authorized public repository; connector access does not establish CLI login |
| [Eclipse Mosquitto](https://github.com/eclipse-mosquitto/mosquitto) | 11k stars; current activity | MQTT broker and publish/subscribe CLIs | Add only if Home Assistant/Frigate or durable device-state integration calls for it |
| [FastAPI](https://github.com/fastapi/fastapi) | 103k stars; current activity | Typed HTTP API and OpenAPI schema | Suitable for our domain API; do not duplicate an upstream API merely to add another server |

Potential custom UI foundations are also established: [React](https://react.dev/) and [Vite](https://vite.dev/guide/). They are not required if an existing phone interface meets the need.

## What the phone apps would do

**Home Assistant's official iPhone app** would display our camera, parking-space status, health, and event controls through its dashboard, receive notifications, and open relevant footage. The Pi vision/rule engine publishes states/events to Home Assistant through its existing APIs or MQTT. Notifications use its mobile-app integration. The app is not a replacement for a detector, and does not establish that a person is committing a crime. See [notification documentation](https://companion.home-assistant.io/docs/notifications/notifications-basic/), [REST API](https://developers.home-assistant.io/docs/api/rest/), [camera integration](https://www.home-assistant.io/integrations/generic/), and [MQTT sensors](https://www.home-assistant.io/integrations/sensor.mqtt/).

Keep the existing Pi OS if using Home Assistant: its [Container installation](https://www.home-assistant.io/installation/raspberrypi-other/) is documented for Raspberry Pi. This differs from replacing Pi OS with Home Assistant OS; Container does not include the Supervisor/app installation facility, so any broker/media service is managed separately. This preserves a normal host environment for the HAT and fan. Nothing has been installed or reflashed.

**Frigate's existing PWA** already provides camera viewing and event review. Its [iOS installation](https://docs.frigate.video/configuration/pwa/) and [Web Push](https://docs.frigate.video/configuration/notifications/) are documented. Push currently covers review alerts, not arbitrary custom parking transitions. It requires authenticated trusted HTTPS, device registration, and outbound connectivity. On iPhone use the Home Screen app; Safari notifications display title/text rather than images. A parking extension may still need a small dashboard and an additional notification integration. Home Assistant is therefore optional rather than mandatory for Frigate viewing.

**Our custom PWA** gives us complete control over parking-map presentation and workflow, but makes us responsible for pairing, sessions, push subscriptions, permission handling, UI, and update behavior. It remains a legitimate option, not a requirement established by the hardware. If the existing app's screens and controls are sufficient, reuse is likely to reduce implementation work; this is an engineering inference, not a measured reliability comparison.

## MCP versus runtime APIs and CLIs

[Home Assistant has an official MCP server](https://www.home-assistant.io/integrations/mcp_server/). It lets an assistant inspect/control exposed entities. Prefer it over an unofficial wrapper if Home Assistant is chosen and assistant access is needed. Its scope should be limited to intended entities. It does not continuously analyze video or replace Home Assistant's ordinary APIs.

The plugin catalog search returned no relevant Home Assistant/Frigate plugin in this session; that catalog result is not proof that no external MCP exists. No unofficial MCP has been selected, connected, or installed. The official Home Assistant integration is the credible MCP candidate identified through primary documentation.

For capture/inference/streaming, documented native APIs and CLIs are the appropriate interfaces. Do not route each frame or alert through an LLM/MCP call: it adds availability, latency, and token requirements to a deterministic local system. GitHub's connected tools are useful for repository inspection; official Git/`gh` remain appropriate for commits, repository creation, and pushing when authenticated.

[MediaMTX's control API](https://mediamtx.org/docs/features/control-api) is documented and localhost-only by default; its [authentication options](https://mediamtx.org/docs/features/authentication) cover media access. [go2rtc's webcam bridge](https://github.com/AlexxIT/go2rtc/blob/master/internal/ffmpeg/device/README.md) directly covers Windows/Linux USB sources. Its [upstream security guidance](https://github.com/AlexxIT/go2rtc#security) warns that API access can expose command-execution capabilities. Protect management interfaces rather than giving the phone unrestricted administrative access.

## What remains our own work

- Calibration for this exact window, doorstep, and parking geometry.
- Reliable free/occupied/unknown states, including occlusion, stale input, camera movement, and stationary vehicles. Zone object counts alone do not solve all these cases.
- Custom event policy, deduplication, confidence/visibility gates, and truthful lingering-event wording.
- Integration, configuration, device-specific performance tests, and documented deployment/recovery.

If Frigate is selected, reuse its tracking, zones, recording, and event interfaces before adding replacements. If the lightweight path is selected, reuse model/runtime/tracking libraries and FFmpeg/media-server recording facilities wherever they meet the requirements.

## Dependency admission rules before implementation

1. Use the upstream package/project identified here, official distribution guidance, and stable pinned versions. Verify artifact checksums where provided; do not install arbitrary forks or floating Git branches.
2. Record each dependency's purpose/license, including model weights separately. FFmpeg licensing varies with build options: use its [official licensing guidance](https://ffmpeg.org/legal.html), not GitHub's unclassified license field.
3. Verify Windows and Pi OS ARM64 support, compatible Python versions, and minimal transitive dependencies. [ONNX Runtime's platform table](https://onnxruntime.ai/docs/get-started/with-python.html) is supporting evidence, not a substitute for installing the exact target wheel.
4. Check relevant upstream release notes/advisories for the pinned release. Add only the component needed by the current milestone, then smoke-test it. No framework gets admitted solely because it has many stars.
5. Benchmark on the actual Pi before production selection. Accelerator purchases, OS changes, and a second always-on inference machine are not assumed.

Research is complete; application architecture is still provisional. Resolve existing phone app versus custom UI, then adapt milestone 1 and resume implementation in the authorized public repository.
