# Bounded overnight tests

Linux command (eight hours by default):

```sh
securitypi soak --config config/local.toml --seconds 28800
```

The supervisor launches the existing analyzer, loopback API and a **dry-run**
notification worker. It polls frame freshness, API response and Linux resource
counters every 30 seconds. Only one soak may own a storage directory. Stop other
analysis/API workers first. It does not install services or survive a reboot.

The workers use one inference thread at the configured analysis FPS (locally
2 FPS), one latest-frame slot, one overwritten preview and one status artifact.
No video history is recorded. The notification worker uses only the standard
library and a bounded local SQLite outbox. No external notification is sent.

Automatic stop conditions:

- Combined worker RSS exceeds 650 MiB (shared pages count more than once).
- Host available RAM or free disk falls below 256 MiB.
- CPU temperature reaches 80 C.
- Any worker exits early, or monitoring/API becomes stale after startup.
- The requested duration elapses (allowed range 60 seconds to 24 hours).

These are sampled limits, not kernel-enforced instantaneous resource caps. All
owned worker parents receive Ctrl+C on termination, then any surviving capture
children are killed after a 45-second shutdown allowance. The API never acquires
the camera. Worker logs are capped at 8 MiB each; an overrun ends that worker.
The supervisor itself uses a small amount of memory outside the worker RSS total.

Ignored artifacts in `data/`:

- `soak-status.json`: start/end times, PIDs, stop reason, peak RAM/temperature.
- `soak-samples.jsonl`: up to 2,880 samples per 24-hour run, overwritten on restart.
- `soak-analysis.log`, `soak-api.log`, `soak-notifications.log`: bounded worker logs.
- `vision-status.json`, `vision-preview.jpg`: current/final observations only.
- `notifications-dry-run.sqlite3` and `.json`: simulated event outcomes.

A normal end is `state=complete`, `reason=duration_limit`; any other ending needs
investigation. Compare early/late RSS, analyzed-frame increments, API freshness,
temperature, worker exit codes, logs, and camera release. No memory leak or
reliability claim follows from a short smoke test. Person counts and detector
outputs without labels are not accuracy measurements. Physical unplug/replug,
phone receipt, daylight/lighting and a longer full-system soak remain separate.

An optional scheduled chat follow-up can inspect these artifacts while the app
remains open. The detached test process itself does not require the chat to stay
active; it does require this Pi to remain awake and powered.
