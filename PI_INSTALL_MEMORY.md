# Pi installation memory and handoff

Updated October 12, 2026. Read this file when the user clones SecurityPI onto the
Raspberry Pi and asks for installation. This is a saved plan, not evidence that
installation or hardware acceptance has already happened.

## User decisions to retain

- Develop source on Windows and publish to public `S-PS-R/SecurityPI`.
- The user will clone the repository on the Pi and request installation later.
- Run hardware acceptance checks on the Pi after installation, rather than
  requiring them during ongoing PC implementation. Keep their results pending
  until measured; they do not block portable development of subsequent milestones.
- Existing hardware: Pi 4, 4 GB RAM, Pi OS, Logitech c922 USB webcam, Sense HAT V2,
  and a fan on the main board. Exact Pi OS version/architecture are unverified.
- Use the official Home Assistant iPhone app as the eventual phone interface.
  Keep Pi OS; Home Assistant Container is the proposed integration route.
- Prefer established FFmpeg/MediaMTX/inference components. Full Frigate deployment
  remains conditional on suitable detection hardware/performance.
- Keep private recordings, photos, tokens, device state, and detailed scene notes
  in ignored local storage. Publish only non-sensitive verification summaries.

## Current baseline; re-check on the installation date

Version 0.2.0 implements CLI/config/logging/local API plus synthetic, local-video,
and USB capture diagnostics. Code commit `84645fd` passed 26 tests and four
Windows/Ubuntu Python 3.11/3.12 CI jobs. Windows c922 delivery was approximately
1280×720 at 10 FPS; that does not establish Pi performance.

The current API is loopback-only and does not start capture. Inference, security
recording, streaming services, Home Assistant integration/notifications, and
systemd supervision are not yet implemented. These may have advanced by the time
this file is used: read current README, MILESTONES, requirements, and CLI help
before deciding what to install. Do not claim 24/7 security readiness from a
successful package installation or capture smoke test.

## 1. Establish the real Pi execution context

The repository clone does not give a Windows-hosted assistant access to the Pi.
Use a shell on the Pi or the user's explicitly identified SSH connection. Verify
the host before running Linux package/device commands. Do not guess credentials,
SSH targets, the checkout path, or the installed OS. Keep credentials out of chat
and Git. Record whether access is direct or via SSH in the local install notes.

User's initial clone, from their chosen directory on the Pi:

```sh
git clone https://github.com/S-PS-R/SecurityPI.git
cd SecurityPI
```

For an existing checkout, inspect `git status --short` and its remote before
updating. Preserve local changes and personal configuration; use a fast-forward
update only when appropriate. Do not reclone over an existing directory.

## 2. Inventory before changing the machine

Run from the actual Pi checkout:

```sh
pwd
git status --short
git remote -v
git rev-parse HEAD
cat /etc/os-release
uname -m
getconf LONG_BIT
python3 --version
id
free -h
df -h .
```

Check camera nodes, device access, and whether the webcam is already in use.
Record OS release, architecture, Python version, available space, camera node,
and the installed commit in `data/pi-install-notes.md` after creating local storage.
Avoid including credentials, private network details, or images in public notes.

The present package supports Python 3.11–3.13. A 64-bit userspace and compatible
ARM64 wheels are the expected path. A 64-bit CPU/kernel alone does not prove that
Python/userspace is 64-bit. Inspect Python's platform/wheel compatibility too.
If this Pi has 32-bit Pi OS or an incompatible Python version, resolve a compatible
installation plan first. Do not bypass package constraints, replace system Python,
or reflash/major-upgrade the OS automatically.

## 3. Install the minimum host prerequisites

Check what is already installed. For a compatible Debian-based Pi OS, the expected
packages are `python3-venv` and `v4l-utils`:

```sh
sudo apt update
sudo apt install python3-venv v4l-utils
```

Check the proposed package changes before accepting them. Install FFmpeg through
the OS package manager only when a relevant media check/milestone needs it. Leave
existing Sense HAT/fan configuration intact. USB capture does not require enabling
the legacy CSI camera stack or installing Picamera2.

Resolve any missing shared-library import error using the packages for this exact
OS release; do not blindly copy older package names or mix system OpenCV and pip
OpenCV variants in one environment. See [Pi dependency notes](docs/pi-development.md).

## 4. Create a Pi-native Python environment

If `.venv` already exists, inspect its Python/platform and installed project before
reusing it. Do not silently delete it. Never copy the Windows `.venv` onto the Pi.

For a new environment, after confirming the selected Python is supported:

```sh
python3 -m venv .venv
.venv/bin/python -m pip --version
.venv/bin/python -m pip install --only-binary=:all: -r requirements/runtime.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/python -m securitypi --version
.venv/bin/python -m securitypi --help
.venv/bin/python -m securitypi check-config --config config/example.toml
```

Use a supported explicit interpreter instead of `python3` if needed. The binary-only
dependency step deliberately fails when suitable wheels are unavailable, rather
than unexpectedly compiling OpenCV/NumPy on the Pi. Inspect compatibility and
choose a supported combination before proceeding. Use a sufficiently recent pip
for the available wheel tags; update pip inside the venv if required.

For on-Pi portable tests, install `requirements/dev.txt` into the same environment,
then run pytest/Ruff. Runtime operation does not require the test tools. Use the
venv; do not use `sudo pip` or bypass externally-managed system-Python protections.

## 5. Hardware-free smoke test, then identify the webcam

```sh
.venv/bin/python -m securitypi capture --config config/example.toml --frames 30 --snapshot data/pi-synthetic.jpg --report data/pi-synthetic.json
v4l2-ctl --list-devices
```

Select the actual c922 capture node. For example, only if `/dev/video0` is that node:

```sh
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

Inspect device ownership/access. If video-group membership is required, apply the
smallest appropriate change for the actual user and explain any new-login step.
Do not make device nodes world-writable. Device indices can change after reconnect;
do not assume index zero is always the c922 or that Windows modes match Linux.

Copy `config/usb.example.toml` to ignored `config/local.toml` only if the local file
does not already exist. Adjust device index, backend, format, resolution/FPS, and
storage for the actual Pi. Paths inside TOML resolve relative to the TOML file.
Try a conservative 640×480/10 FPS mode if the 720p candidate is unsuitable.

## 6. Actual Pi capture and deferred hardware checks

Once the device index and local profile are correct:

```sh
.venv/bin/python -m securitypi camera-info --config config/local.toml
.venv/bin/python -m securitypi capture --config config/local.toml --frames 100 --snapshot data/pi-usb-check.jpg --report data/pi-usb-check.json
```

Verify decoded dimensions, image quality, requested versus reported format, and
delivered FPS. Test another capture after exit to check released ownership. Follow
[docs/window-validation.md](docs/window-validation.md) for physical unplug/replug,
bounded failure, Ctrl+C, frame freshness, final mount, and day/night/glare/occlusion
checks. The user will perform physical placement/unplugging and inspect private
samples on the Pi. Daytime checks may need to wait until daylight.

Where available, record `vcgencmd measure_temp` and `vcgencmd get_throttled`, CPU/RAM,
power/storage issues, and fan/HAT clearance. HAT ambient temperature is not CPU
temperature. Keep LEDs from reflecting into the window. These checks are separate
from the later combined streaming/inference performance and 72-hour soak test.

## 7. Install only the features actually ready

Use the current milestone state to determine whether Home Assistant Container,
MediaMTX/FFmpeg services, model weights/runtime, Tailscale, or systemd files are
ready for installation. Do not install a duplicate media server, an unreviewed
model, or a placeholder systemd service. Keep configuration/secrets outside source
control, service privileges limited, and unauthenticated development APIs local.

For the current baseline, the optional API smoke test is:

```sh
.venv/bin/python -m securitypi serve --config config/local.toml
```

In a second Pi terminal, check `/api/health` and `/api/status` at
`http://127.0.0.1:8000`. A healthy process still reports monitoring not started;
this command does not stream the camera to the phone. Stop with Ctrl+C.

## 8. Preserve a reproducible result

Record installed commit, OS/Python/architecture, dependency/import results, camera
node/modes, measured settings/FPS, and pass/fail/pending hardware checks locally.
Update GitHub's verification/milestone documents with non-sensitive summaries only.
Keep unperformed day/night and soak checks pending. If installation fails, retain
the cause and next action rather than marking deployment or 24/7 readiness complete.

Sources checked when writing this handoff: [Raspberry Pi OS documentation](https://www.raspberrypi.com/documentation/computers/os.html)
and [Python virtual-environment installation guidance](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/).
Re-check release-dependent installation details on the actual installation date.
