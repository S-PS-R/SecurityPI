# PC versus Pi dependencies

The foundation uses Python 3.11–3.13, with 3.12 recommended on Windows. Check the
installed Pi OS release, architecture, and Python version before choosing the
target runtime. Inference wheels may impose additional limits. A 64-bit Pi OS is
the proposed target, not a claim about the user's currently installed image.

On a compatible Linux development environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m securitypi check-config --config config/example.toml
.venv/bin/python -m pytest
```

For an eventual runtime-only install, use `requirements/runtime.txt`, then the
local project without dependency resolution/build isolation. Setuptools is pinned
in the runtime requirements so editable installation works consistently. Build
and maintain a separate environment on the Pi; do not transfer `.venv` from Windows.

Milestone 2 installs OpenCV/NumPy through the runtime requirements. The selected
releases have published ARM64 wheels, but the actual Pi installation is pending.
Inference, FFmpeg/MediaMTX service setup, Sense HAT, GPIO/I2C permissions, systemd,
Home Assistant Container, and Tailscale are not installed by the Python package.
These will have separate official-source installation instructions and hardware
acceptance checks. A USB webcam does not need a CSI/Picamera2 adapter.

CI runs on x64 Windows/Ubuntu and cannot validate ARM wheels, USB capture,
hardware encoding, HAT/fan coexistence, Pi temperature, or locked-iPhone push.
