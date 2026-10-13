# Milestone 2 hardware/window acceptance

Software/Windows capture can be verified now. The following field checks require
actual placement and Pi access. They remain pending; do not mark the whole milestone
complete based on CI, a room snapshot, or the Windows driver mode list.

## 1. Verify the Pi capture path

- Record Pi OS release, architecture, Python version, camera node, power supply,
  storage, and camera mounting. Create a Pi-native venv; do not copy the Windows venv.
- Install the pinned requirements after verifying compatible wheels. The selected
  PyPI release publishes Linux ARM64 wheels; installing on this Pi is still required.
- Enumerate formats using the commands in [capture.md](capture.md), then run its
  camera-info/capture commands with the correct index/backend.
- Confirm image dimensions, delivered FPS, color, autofocus, and a second capture
  after the first exits. Record CPU/temperature if available; this is not yet the
  combined inference/streaming benchmark.

## 2. Check physical unplug/replug

Run capture with `--frames 0`. Unplug the webcam, reconnect within the configured
retry budget, and verify fresh frames resume and sequence continues. Repeat with
the camera absent longer than the budget: expect exit code 2 and released ownership.
Check the device index again after reconnect; rerun if the OS assigned a new index.
Run another capture to verify the camera is not left locked. Stop using Ctrl+C;
expect reason `interrupted`, bounded worker shutdown, and exit code 130.

## 3. Assess the actual window view

- Secure the camera near clean glass. Disable/dim indoor light and Sense HAT LEDs
  reflected in the pane; compare a dark hood if necessary.
- Capture daylight and night samples from the final mount, including curb/parking,
  doorstep, pedestrians, headlights, rain/glare/screens, and partial occlusions.
- Inspect whether a person/vehicle is large and clear enough at the important
  locations. Record blind spots and how much of each parking area is visible.
- Compare with room lights on/off. Do not point camera IR emitters into the glass
  if applicable; reflection can overwhelm the scene. Camera night capability is
  still unknown. A wider image does not establish enough detail for detection.
- If the door and curb cannot both be seen clearly, change placement or plan a
  second view. Darkness/occlusion must later yield unknown parking, not free.

Example Windows sample (Pi uses `.venv/bin/python` instead):

```powershell
.venv\Scripts\python.exe -m securitypi capture --config config/usb.example.toml --frames 100 --snapshot data/window-day.jpg --report data/window-day.json
```

Repeat with distinct `window-night` names. These commands take only a final
snapshot and metadata, not an evidence video; event recordings are a later milestone.
Keep private samples and detailed scene notes inside ignored `data/`.

## Acceptance record

Copy this checklist to `data/window-acceptance.md` locally:

- [ ] Pi OS/runtime and native camera capture verified.
- [ ] Pi-supported modes enumerated; actual dimensions/FPS recorded.
- [ ] Physical reconnect within budget recovers; prolonged loss exits clearly.
- [ ] Ctrl+C releases ownership and a second capture succeeds.
- [ ] Final mount covers door and intended parking areas in daylight.
- [ ] Night/reflection/glare/occlusion limitations documented.
- [ ] Placement changes/second-view requirements identified.

Only summarize non-sensitive results in GitHub. Do not commit private images,
addresses, identifiable footage, or detailed views of the home's surroundings.
