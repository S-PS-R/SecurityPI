# Opt-in cooling comparison

From the checkout, with Home Assistant and the existing analyzer running:

```sh
.venv/bin/python -m securitypi thermal-test --config config/local.toml --case lid-off
```

Each run lasts 30 minutes: normal 5, two authenticated Home Assistant previews plus
history requests and isolated synthetic snapshot writes 20, then the same workload
plus four low-priority single-threaded NumPy workers 5. No camera or detector is
started. Stop with Ctrl+C or stop the owning systemd unit. Added workers have parent
watchdogs and finite deadlines. Existing fan control and thermal protection remain active.

CPU temperature is displayed once per second on the named 8×8 Sense framebuffer;
original pixels are restored on normal stop, exceptions and SIGINT/SIGTERM. SIGKILL
or power loss cannot run cleanup. Keep a saved original framebuffer file when
running through systemd if recovery from a forced stop is needed.

Private logs live under ignored `data/thermal-tests/`: CSV capped at 2 MiB per run,
new runs refused after 20 MiB existing data (24 MiB total allowance). Scratch writes
use three JPEGs below 2 MiB each, immediately removed; no training/evidence files
are touched. Safety stops include 80°C, active throttle flags, 10 consecutive fan
stall samples, camera older than three seconds, low RAM/disk and Home Assistant loss.
A safety stop is an incomplete test, never a successful cooling result.

After stopping added load and cooling toward baseline, fit the lid and repeat with
`--case lid-on`, after the operator confirms. Compare these original-curve runs
before changing the fan. Preview the boot-config patch without modifying it:

```sh
python3 deploy/thermal/fan-curve.py candidate
```

Only after the original-curve comparison, apply from an administrator terminal:

```sh
sudo python3 deploy/thermal/fan-curve.py candidate --apply
sudo reboot
```

The helper backs up config.txt, changes only its marked block, retains existing
PWM levels and sets 5°C hysteresis. After reboot verify trip temperatures and
restore the same application services before `--case lid-on-tuned`. Use `stronger`
and `--case lid-on-stronger` only if the candidate misses the agreed targets.
No boot service enablement is changed by this CLI.
