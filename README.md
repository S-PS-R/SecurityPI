# SecurityPI

Local security and parking analysis for a Raspberry Pi 4, developed on Windows.
The official Home Assistant iPhone app will provide the dashboard, controls,
live viewing, and notifications. Python handles our camera analysis and rules;
established media/inference components will be added when their milestones need them.

**Milestone 1 is a runnable foundation, not an operating security camera.** It
validates configuration and serves process health/status. Camera capture, person
and vehicle detection, recordings, Home Assistant connections, and phone alerts
are not implemented yet. Parking status is explicitly unknown.

## Requirements

- Python 3.12 recommended. The foundation supports Python 3.11–3.13; CI covers
  3.11 and 3.12 on Windows and Linux. Future ARM inference dependencies may narrow
  that range after testing.
- Git for source checkout. No Node.js, Mac, camera, Pi, or Home Assistant instance
  is needed to run foundation checks.
- Target hardware: Pi 4 / 4 GB, Logitech 1080p USB webcam, Sense HAT V2 and fan.

## Windows setup

From the repository root in PowerShell, with Python 3.12 installed:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.venv\Scripts\python.exe -m securitypi --help
.venv\Scripts\python.exe -m securitypi check-config --config config/example.toml
```

If your installation has `python` but no `py` launcher, use
`python -m venv .venv` after checking `python --version`. Explicit virtual-environment
paths avoid PowerShell activation-policy changes.

Run the local API:

```powershell
.venv\Scripts\python.exe -m securitypi serve --config config/example.toml
```

Open [API documentation](http://127.0.0.1:8000/docs),
[process health](http://127.0.0.1:8000/api/health), or
[monitoring status](http://127.0.0.1:8000/api/status). Stop with Ctrl+C.
`health.status=ok` means the process responds, not that a camera is watching.
The status endpoint reports `monitoring=false`, `camera=not_started`, and
`parking=unknown`. This unauthenticated development API accepts localhost binds
only; network access/authentication is a later milestone.

## Checks

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m pip check
```

Tests cover invalid configuration and secret-value suppression, relative paths,
CLI exit codes, health versus monitoring status, and structured logs. GitHub
Actions runs the same foundation checks on Windows and Ubuntu. Hardware acceptance
is tracked separately in [MILESTONES.md](MILESTONES.md).

## Configuration and credentials

Copy `config/example.toml` to `config/local.toml` for personal settings (ignored by
Git). Paths resolve relative to the configuration file. Validation does not create
storage, open cameras, or contact external services. Unknown keys, invalid ranges,
inline URL credentials, and non-local binds are rejected; errors identify fields
without echoing supplied values.

The future Home Assistant adapter will read a token from `SECURITYPI_HA_TOKEN`,
or the environment-variable name in `home_assistant.token_env`. It does not read
or use any token in milestone 1. Keep tokens, personal footage, databases, logs,
and runtime state out of Git. The logger does not automatically scrub arbitrary
messages; application code must never log credentials or raw configuration.

## Project layout

```text
src/securitypi/    CLI, config, JSON logging, FastAPI foundation
tests/            Hardware-free checks
config/           Non-secret example TOML
requirements/     Pinned runtime/development dependencies
app/              Home Assistant interface documentation; no custom app build
docs/             Architecture, dependencies, integration, verification
deploy/           Pi deployment boundary and future service files
.github/workflows/ Windows/Linux CI
```

See [architecture](docs/architecture.md), [Home Assistant plan](docs/home-assistant.md),
[Pi setup boundary](docs/pi-development.md), and [dependency decisions](docs/dependencies.md).
[TOOL_ASSESSMENT.md](TOOL_ASSESSMENT.md) records upstream research before imports.

Code in this repository is MIT licensed. Upstream dependencies and future model
weights retain their own licenses. This system reports observed activity and
uncertainty; a person lingering near a car is not proof of a break-in.
