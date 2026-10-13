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

Remote CI outcome will be recorded after the first push. Local sandbox restrictions
prevented some temporary-file/thread/socket operations; the same commands passed
with authorized execution outside that sandbox. This is an execution-environment
constraint, not a change to the application or its OS requirements.

No Pi, webcam, Sense HAT, Home Assistant, or iPhone behavior has been verified in
this milestone. Those features are deliberately absent from the implementation.
