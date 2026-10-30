# Home Assistant iPhone interface and notifications

The local integration supplies fresh observations, compact history and a bounded
notification worker. Home Assistant Container and the iPhone connection have been
set up on the Pi; the user confirmed a manual push during pairing. Automated
alert accuracy and delivery still need controlled field checks. This update adds
no runtime dependencies.

## Data path

`analyze` owns the camera and replaces one status JSON and one JPEG. `serve` reads
those artifacts; it never starts inference. Home Assistant polls the loopback
bridge and serves its own authenticated dashboard to the official iPhone app.
The independent `notify` worker reads the same status and calls the registered
Home Assistant mobile-app action. Network delays cannot stall the camera.

- `/api/health`: process readiness only.
- `/api/status`: monitoring summary, distinct from process readiness.
- `/api/vision`: people, temporary track durations, candidate geometry, freshness.
- `/api/preview.jpg`: latest annotated JPEG, not a live video stream.
- `/api/notifications`: worker freshness and counts for the last 100 events.

Frames older than 15 seconds, stopped workers, missing or malformed status yield
unavailable observations. People become `null`, not zero. Parking remains unknown
because learned vehicle geometry cannot establish visibility or legal parking.
Previews are atomic replacements and unavailable when stale. Responses disable
caching. The unauthenticated bridge remains loopback-only; do not forward its
port to a LAN or the internet. Host-local processes remain trusted.

## Connect Home Assistant when ready

Use the existing official iPhone app; no separate app, broker, web framework or
cloud AI service is needed. Home Assistant Container on this Pi must use the
host network for these loopback URLs. A container using bridge networking, a
second computer and an iPhone each have a different `localhost`.

1. Install and onboard Home Assistant following the
   [official Container instructions](https://www.home-assistant.io/installation/raspberrypi-other/).
   Measure its memory use alongside analysis before enabling continuous operation.
   Authenticate through Home Assistant; remote cellular access needs a private VPN
   or another supported secure Home Assistant connection.
2. Copy `deploy/home-assistant/securitypi.yaml` into HA's `packages/securitypi.yaml`.
   Merge this into the existing `configuration.yaml` without duplicating keys:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   Check configuration before restarting HA. The package uses its supported REST
   sensors and excludes verbose track/message attributes from Recorder while
   retaining compact numeric measurements.
   It does not create temporary entities by POSTing `/api/states`.
3. Run `securitypi analyze --config config/local.toml --seconds 0` and, separately,
   `securitypi serve --config config/local.toml`. Do not start these while `soak`
   owns them. Check that the HA entities match the dashboard's entity names;
   existing entities can cause numeric suffixes.
4. Add HA's **Generic Camera** integration with still-image URL
   `http://127.0.0.1:8000/api/preview.jpg`, leaving stream source blank. Name its
   entity `camera.securitypi_preview`. Analysis must be producing fresh frames
   during setup. HA proxies the image to the phone; the phone never uses this
   loopback address directly. HA can retain the last image internally, so the
   dashboard hides its image card whenever monitoring is offline.
5. Add an empty dashboard with URL path `securitypi-dashboard`, open its raw configuration
   editor and paste `deploy/home-assistant/dashboard.yaml`. It uses built-in cards
   for counts, live preview, charts and compact track/alert tables.
   Its overview path matches the push notification link `/securitypi-dashboard/overview`.
6. Sign into the official Home Assistant iPhone app and grant notification access.
   Locate the resulting `notify.mobile_app_<device>` action. Keep the long-lived
   HA token in an environment variable, never TOML, source code or chat.

## Opt-in notifications

In ignored `config/local.toml`, add the actual registered service name:

```toml
[home_assistant]
url = "http://127.0.0.1:8123"
notifications_enabled = true
notify_service = "mobile_app_your_iphone"
token_env = "SECURITYPI_HA_TOKEN"
person_seconds = 10.0
expiry_seconds = 120.0
```

The `SECURITYPI_HA_TOKEN` environment variable must be present in the notification
worker's process. Start with `securitypi notify --config config/local.toml
--seconds 60 --dry-run`. Dry runs use a separate database and cannot consume real
queued events, contact HA or report actual delivery. Once pairing is complete,
run without `--dry-run` for real delivery; `--seconds 0` runs until Ctrl+C.

The current rule sends **Person detected.** once per confirmed person track after
10 observed seconds. Track numbers stay in internal deduplication keys, not visible
phone text. There is no global cooldown. Tracking counts consecutive observations
at the actual processing rate; missed detections do not accumulate observed time.
A qualified event stays available for 120 seconds so a slower notification poll
can still see it after the person leaves. Separate people do not suppress one
another. Up to five ready messages are attempted per worker
poll; a transport failure ends that delivery batch so network problems remain
bounded. History is limited to 100 messages; a separate capped deduplication
table retains active/recent IDs even when visible history rolls over. At most
20 events can be pending; the SQLite database has a 1 MiB page limit. One worker
owns an outbox. Restart retains deduplication, expiry and retry state. A new camera
run or stale monitoring cancels outstanding events from obsolete observations.
The analyzer retains up to 100 arrival records for 120 seconds and writes status
when a new person is confirmed. A brief appearance can still be reported after
the person leaves, provided monitoring is fresh and the event has not expired.

HTTP 408/429/5xx and transport failures retry at increasing intervals, at most
five attempts and never beyond event expiry. Other errors stop retrying that
event. Tokens are not logged or forwarded through redirects/proxies. A stable
notification tag limits stacking after an ambiguous network timeout; delivery is
not exactly-once. `accepted` means HA accepted the request, **not** that the phone
received or displayed it. Current messages describe observations, not intent.
Only the latest 100 event outcomes are counted. No private image is attached to push.

## Acceptance still required

The local HTTP contract is tested against a mock server, including successful
requests, authentication rejection, rate limiting, server failure and redirects.
Queue tests exercise independent person arrivals, restarts, expiry, bounded
retention and dry runs.
The host's existing YAML/Jinja parsers check the dashboard templates separately;
this is not Home Assistant's complete configuration validation.

HA startup and its own configuration validation passed on October 23. Actual
offline data exposed a numeric sensor error; the sensors now use HA's availability
template instead of returning text as a numeric value. The corrected runtime
started without that error. Still pending: iPhone layout, locked-phone receipt,
cellular access, notification timing/false-alert rate and final daytime
camera/person walk tests. A sustained camera soak cannot prove these phone checks.

References: [REST sensors](https://www.home-assistant.io/integrations/rest/),
[configuration packages](https://www.home-assistant.io/docs/configuration/packages/),
[Generic Camera](https://www.home-assistant.io/integrations/generic/),
[REST actions](https://contributors.home-assistant.io/core/internals/rest-api/),
[mobile notifications](https://companion.home-assistant.io/docs/notifications/notifications-basic/).

## Prepared Pi deployment — October 22

`deploy/home-assistant/install.sh` is a reviewable ARM64 bootstrap for this local
checkout. It expects prepared files in ignored `data/home-assistant/` and
`data/home-assistant-setup/securitypi-api.service`. The Pi requires an interactive
sudo password; these files being present does not mean Docker or HA is installed.
Run the script with sudo in a Pi terminal, not by sending a password in chat.

The script installs Debian's Docker Engine and separate CLI if missing, pulls an
official ARM64 image pinned by digest (about 609 MiB compressed when checked),
validates HA configuration, starts the loopback API as the normal user, and starts
HA on port 8123. HA receives a 640 MiB RAM limit, 768 MiB combined RAM/swap limit,
one CPU core, bounded container logs and a 60-second stop timeout. It has no
privileged mode or camera device mapping. The retained `DISABLE_JEMALLOC=true`
setting was suggested for 16 KiB pages by the installation documentation, but
HA 2026.10.2 reports that it now uses mimalloc and ignores that setting. Startup
succeeded on this Pi; allocator performance remains unmeasured.
No existing differing API unit or existing named
container is replaced. Automatic startup on reboot remains off for the trial.

The installer now refuses to start containers if Docker reports that memory or
swap limits are unsupported. This Pi's kernel initially disabled its memory
controller, and Docker silently discarded those limits. A backed-up boot command
line now includes `cgroup_enable=memory`; a reboot is required. After reboot,
verify Docker supports both limits and apply them to the existing trial container
before restarting it. A boot change alone does not restore discarded container
limits. Combined camera/HA resource measurement remains pending.

The minimal configuration loads the dashboard at `/securitypi-dashboard/overview`
and excludes SecurityPI sensor history from Recorder. Account creation and the
Generic Camera integration still happen in HA. The script does not start camera
analysis or send notifications. After startup, verify onboarding availability,
actual HA configuration acceptance and combined resource use before enabling
continuous operation. The previous plain `securitypi` dashboard URL was changed
to include the hyphen required for a YAML dashboard.

## Observation and message clarity — October 26

Current observations now list every detected supported person/vehicle class with
track number, movement and stationary duration. Provisional parking and light
pixel evidence are labelled explicitly; see docs/vision.md for limits and roadway
calibration. The dashboard includes the need to mark/review the roadway.

The notification entity is labelled Phone alerts. Ready to send means the sender
process is healthy and awaiting a qualifying observation; it does not mean an
alert has fired or that a phone received one. The Messages card explains this,
shows the per-track alert policy and displays the latest five event messages
with timestamps/outcomes, alongside totals for the bounded 100-event outbox.

Roadway-stop events reuse that outbox, retries, expiry and per-track deduplication.
They require an active reviewed roadway outline and a vehicle classified as
lingering there. Pending roadway messages are cancelled when the current stop
no longer qualifies. Person-arrival messages can survive leaving the field of
view until their expiry. No alert describes
criminal intent. Manual test receipt does not establish automatic field accuracy.
The worker continues to target only the configured phone; additional roommates'
phones have not yet been added as recipients.

When updating an older local configuration, remove cooldown_seconds. It is no
longer a supported setting. Set person_seconds=0 for first-confirmed-track alerts.
The deduplication table is capped at 500 active/recent keys, independently of the
100-message display history; active keys are refreshed on each worker poll.

## Detection display, notification tracking and retained data

The overview shows raw model detections with green boxes, class labels and
confidence percentages. The retained categories are people, cars, motorcycles,
buses and trucks, subject to the configured confidence/NMS limits. The unchanged
model still computes its original output; filtering is not measured field accuracy. Counts use current detections, including
objects without confirmed tracks. No track numbers appear on detection boxes or
the current observation table. Track IDs remain internal for deduplication.

Tracking supports enabled phone notifications and person snapshots. ByteTrack associates
person/vehicle detections for the existing arrival and roadway-stop rules. It
never gates the visible green boxes. If notifications and snapshots are disabled, the analysis
loop does not construct a tracker. Tracking/parking calibration and per-track
history writes no longer run as display features. Previously saved track summaries
are preserved locally; the legacy history API can read them but no longer receives
new entries from the analyzer. Detection count charts remain available.

Recorder retains compact numeric measurements for seven days, with a 30 s commit
interval. Verbose detection/message attributes are excluded. No long-term
statistics state_class is enabled. HA purges on its daily schedule; reusable free
pages may remain, so retention is not a hard database byte cap. The History tab
shows the count charts. No video is recorded; person snapshots use the bounded seven-day store below.

USB capture continuously grabs encoded frames to drain the driver. Only when
analysis requests a frame does the native worker decode it and transfer pixels
to the parent. There is no parent reader thread decoding unused frames and no
queue of old images. Native-call timeouts, bounded reconnect and process cleanup
remain active. Video-file reads stay sequential and retain their EOF behavior.

The Pi retains30 FPS MJPEG capture and now uses two detector threads, a5 FPS
analysis ceiling and5 FPS preview ceiling. Actual model throughput is lower and
varies with host load. HA Generic Camera uses a5 FPS refresh ceiling, so preview
sampling is not held at its old 2 FPS rate. Preview JPEG quality 75 reduces encoding
and transfer costs. These are annotated inference frames, not interpolated or
predicted boxes. The phone's display rate has not been measured.

`/api/vision` reports separate captured/grabbed, decoded and analyzed rates, raw
detections and notification tracks. `capture_age_ms` is the elapsed time from
OpenCV grab completion to delivery to analysis, excluding model inference. It is
not a hardware exposure timestamp. `/api/storage` reports HA database/WAL/SHM and
filesystem free space; all SecurityPI API endpoints remain loopback-only.


## Person snapshots and seven-day storage

Enable `[snapshots] enabled = true` in the local TOML. The existing analyzer saves
up to three full-frame JPEGs per person track at 5, 10 and 20 observed seconds.
Images are context, not evidence of intent. Two frame copies can queue for a
background writer; overload drops a snapshot instead of blocking analysis.
One delayed update produces at most one JPEG even if it crosses several thresholds.
No second camera reader, model or training runtime is started.

JPEG quality is 80. Defaults are `max_mib = 500`, `max_images = 10000`, with rolling
seven-day expiry. Images live under
`data/home-assistant/media/securitypi-person-events/`; this is already mounted at
`/config/media/securitypi-person-events` inside HA Container. File names contain UTC
capture time and internal run/track/threshold identifiers. They are private files,
not files in HA's public `www` directory. Other signed-in HA users can access the
media according to HA's existing permissions; this is not an admin-only gallery.

The dashboard's **Person snapshots** button opens HA's built-in media browser.
Select **Web browser**, then **securitypi** to view the images. Configuration:

```yaml
homeassistant:
  media_dirs:
    securitypi: /config/media/securitypi-person-events
media_source:
recorder:
  purge_keep_days: 7
  commit_interval: 30
```

`securitypi cleanup-snapshots --config config/local.toml` removes only this module's
recognized snapshot files, leaving training images, models and diagnostics intact.
Install the user service/timer templates in `deploy/systemd`, replacing `@REPO@`
with the checkout's absolute path. The hourly timer runs without the analyzer and
catches up after downtime. The analyzer also cleans at startup and around writes.
`/api/storage` adds `snapshot_count` and `snapshot_mib`. The live vision artifact
includes snapshot written/dropped/error counters for diagnostics.

Recorder purges seven-day history through HA's supported purge action. Its database
can reuse allocated space rather than shrinking immediately. Existing numeric
sensors deliberately have no long-term `state_class`, so they do not retain
indefinite aggregated statistics. Graphs show at most the latest seven days.

## Private remote access

Push notifications use HA's internet push infrastructure and can reach the iPhone
without remote dashboard access. Private dashboard access is a separate connection.
This Pi uses the official ARM64 Tailscale static binaries in ignored `.tools/tailscale`
and a user service with a 128 MiB memory limit and 30% CPU quota. User-space
networking avoids a privileged tunnel and exposes only Home Assistant through
explicit Serve endpoints. HTTPS is used for the Companion app; port 8123 is a
private TCP fallback. It advertises no subnet routes, exit node or SSH service.
No router port-forwarding or public Funnel is used.

Pair the Pi and iPhone with the same Tailscale account. After Pi authorization:

```sh
.tools/tailscale/tailscale --socket=data/tailscale/tailscaled.sock serve --bg --tcp=8123 tcp://127.0.0.1:8123
.tools/tailscale/tailscale --socket=data/tailscale/tailscaled.sock ip -4
```

For HTTPS, enable Serve when Tailscale presents its device-specific setup link,
then run `tailscale --socket=data/tailscale/tailscaled.sock serve --bg
http://127.0.0.1:8123` using the binary in `.tools/tailscale`. HA's `http` settings
must enable `use_x_forwarded_for` and trust only `127.0.0.1` and `::1` as proxies.
In HA 2026.10, HTTP settings may already have migrated into its managed store;
changing YAML then does not update the running configuration. Use HA's supported
HTTP configuration UI/API, verify its trial, and confirm the working settings.
Do not edit its private `.storage/http` file directly.
Use the HTTPS `*.ts.net` URL shown by Serve as the Companion app's external URL.
Keep the LAN address as the internal URL and retain HA login requirements.
The private HTTP fallback is `http://<Pi-Tailscale-IP>:8123`, encrypted in transit
by Tailscale, but iOS may block it under the app's strict connection-security mode.
Confirm the app over cellular with Wi-Fi disabled. Pairing, a successful local API
request and service readiness alone do not prove iPhone receipt or remote access.

References: [HA remote access](https://www.home-assistant.io/docs/configuration/remote/),
[HA authenticated media](https://www.home-assistant.io/integrations/media_source/),
[Tailscale user-space mode](https://tailscale.com/docs/concepts/userspace-networking).

## Starting the deployed Pi after reboot

The camera/notification user units must be installed from the templates in
`deploy/systemd`; transient `systemd-run` definitions disappear after reboot.
The deployed units now exist as persistent files. Their resource limits and
notification environment file are retained. They are manually started; this
change does not enable automatic camera startup at boot.

```sh
sudo systemctl start docker securitypi-api.service
sudo docker start securitypi-homeassistant
systemctl --user start securitypi-vision.service securitypi-notify.service securitypi-tailscale.service
```

Use the normal user for `systemctl --user`; do not prefix it with sudo. Never paste
an administrator password or notification token into chat. Home Assistant Container
retains its existing restart policy, so starting only the API/camera workers does
not start Home Assistant itself.
