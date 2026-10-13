# Milestone 1 verification

October 12, 2026 (America/New_York).

- Windows x64, Python 3.12.14.
- Installed pinned requirements and the local editable project in `.venv`, then
  independently installed from `requirements/dev.txt` into a second clean
  `.local/verify-venv` environment.
- Clean environment: 15 pytest checks passed; Ruff lint and formatting passed;
  `pip check` reported no broken requirements.
- Module CLI help/config validation and installed `securitypi` entry point work.
- Real loopback server returned health `ok`, but monitoring `false`, camera
  `not_started`, parking `unknown`, and Home Assistant `not_connected`.
- Reviewed staged paths and ignore rules: environments, runtime data, and personal
  config are excluded. No credentials or camera footage were included.
- CI uses GitHub's official checkout/setup-python actions pinned to verified
  release commit SHAs. Four jobs cover Windows/Ubuntu and Python 3.11/3.12.

Remote CI passed on all four jobs for code commit
[`19958b9`](https://github.com/S-PS-R/SecurityPI/commit/19958b91fb9812e545633d4b88144351fb017979):
Ubuntu/Windows with Python 3.11 and 3.12, each running installation, dependency
consistency, lint/format, all 15 tests, CLI help, and example-config validation.
See [the verified Actions run](https://github.com/S-PS-R/SecurityPI/actions/runs/38332248340).
The following documentation-only completion commit does not change tested code.

Local sandbox restrictions
prevented some temporary-file/thread/socket operations; the same commands passed
with authorized execution outside that sandbox. This is an execution-environment
constraint, not a change to the application or its OS requirements.

No Pi, webcam, Sense HAT, Home Assistant, or iPhone behavior was verified in
milestone 1. See the milestone 2 section below for subsequent Windows camera checks.

## Milestone 2 candidate

October 12, 2026 (America/New_York), Windows x64/Python 3.12.14.

- Added headless OpenCV 4.14.0.94 and NumPy 2.4.6 from verified PyPI releases.
- 26 portable tests passed, including actual generated MJPEG video decoding/EOF,
  source ownership, retry limits, blocked worker open/read, reconnect sequence,
  local artifact isolation, and partial interruption. Lint/format and `pip check` passed.
- Windows device identity: Logitech c922 Pro Stream Webcam. Driver-supported modes
  enumerated with the existing FFmpeg DirectShow CLI.
- Real capture: 30 frames at 1280×720, approximately 9.98 delivered frame-interval
  FPS, no reconnects. Startup-inclusive rate is lower; see [capture details](capture.md).
- Missing camera index: three failed attempts and expected exit code 2.
- Private samples remain inside ignored `data/`. No camera photo is published.
- Pi capture/performance, physical unplug/replug, and final day/night window view
  are pending. This is a candidate push, not full hardware acceptance.

All four Windows/Ubuntu Python 3.11/3.12 CI jobs passed for code commit
[`84645fd`](https://github.com/S-PS-R/SecurityPI/commit/84645fdbb2d23db2633f388efc87fd435b7ee839).
See [the milestone 2 Actions run](https://github.com/S-PS-R/SecurityPI/actions/runs/38335532235).
The documentation-only evidence update does not change tested code. Full milestone
2 remains pending the field checks in [window-validation.md](window-validation.md).
