# Architecture decision: Home Assistant first

Accepted October 12, 2026 after the established-tool assessment.

- Phone: official Home Assistant iPhone app; reuse dashboards, authentication,
  mobile notifications, and automation interfaces.
- Host: keep Pi OS; consider Home Assistant Container on the Pi. Measure its
  memory/CPU together with analysis and media before accepting a deployment.
- Domain service: Python for parking calibration/state, activity rules, and
  adapters. FastAPI exposes domain state; SQLite will hold events and an outbox.
- Media: FFmpeg plus one MediaMTX instance is the preferred independent path.
  Avoid competing camera owners and repeated encoding.
- Inference/tracking: select assessed pretrained models/runtime/helpers after
  exact Windows/ARM package checks and Pi benchmarks. Do not train a detector or
  implement a tracker from scratch for the first release.
- Frigate: conditional alternative if suitable hardware is established; reuse
  its NVR/tracking/event features if selected instead of deploying duplicate ones.
- Remote access: private Tailscale path, with media/API authorization added before
  exposure. An MCP connection is optional assistant tooling, not the frame loop.

The intended pipeline is camera owner → shared media/analysis feed → detector and
tracker → parking/activity rules → local evidence/events → Home Assistant adapter
→ dashboard/mobile notification. Media transport runs independently of inference.

Milestone 1 implements only the configuration, CLI, JSON logging, and local HTTP
foundation. It sends no state to Home Assistant and opens no camera. Both synthetic
and USB source names are accepted as future configuration, but neither captures
frames yet. Status never mistakes process liveness for monitoring readiness.

No custom React/PWA build or Node dependency is required. `app/` reserves space
for Home Assistant dashboard examples. A custom UI is a later optional extension.
