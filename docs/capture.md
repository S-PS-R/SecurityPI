# Portable capture

Version 0.2.0 implements synthetic, local-video, and USB sources behind `FrameSource`.
Each frame has an independent BGR uint8 array, continuous sequence, timezone-aware
UTC acquisition timestamp, and monotonic timestamp. Files additionally expose the
decoder's media position when available; that position is not the wall-clock time.

The default source is synthetic, so CI and default commands never open hardware.
`--source usb --device-index N` overrides the configured device. `--video PATH`
selects an existing local file; CLI paths are relative to the current directory,
while TOML paths are relative to the TOML file. No network/video URLs are accepted.
Files stop at EOF and do not reconnect or loop; corrupt/open failures are errors.
Known premature EOF uses available frame-count metadata to flag decode failures;
when the decoder reports no trustworthy frame count, ordinary EOF cannot always
be distinguished from truncation.

## Native-call deadlines and ownership

One spawned worker owns OpenCV capture. The parent requests one frame at a time;
there is no accumulating frame queue. It supervises open/read operations using
`io_timeout_seconds`. USB failures release/reap that worker and reconnect with
`reconnect_attempts` additional attempts and `reconnect_delay_seconds` between them.
A successful read resets the per-read retry budget. Sequence continues across
reconnects; the source is never shared by multiple camera owners.

The process boundary is intentional: native drivers can block inside `read()`
where a thread timeout cannot cancel them. Shutdown sends a close command, waits
0.25 seconds, then terminates a blocked worker (up to 1 second), and kills/reaps if
necessary (up to another second). Normal exit releases OpenCV explicitly; forced
termination relies on OS process-handle cleanup. IPC transfers have bounded frame
size (64 MiB), but Python pipe serialization and OS scheduling are not hard
real-time deadlines. No promise of instant Ctrl+C or reconnect is made.

With defaults, a failing read/open may take several timeout/cleanup intervals plus
retry delays. A reconnect may require both an open deadline and a read deadline.
Reduce retries/delay for quick diagnostics; tune real USB startup on the target
before lowering the default 10-second I/O timeout. A persistent unavailable camera
fails clearly after its finite budget; it does not retry forever.

## Requested versus delivered settings

`backend="auto"` selects DirectShow on Windows USB and V4L2 on Linux USB. Local
video selects FFmpeg. Explicit `dshow`, `msmf`, `v4l2`, or `ffmpeg` are available
for troubleshooting, but the chosen backend must exist on the host.

The worker requests configured width/height/FPS and optional FourCC. `set()` returning
true does not prove a requested mode was used. Reports include the backend's
negotiated/readback properties and the actual decoded frame dimensions. They are
not a list of every supported mode. `frame_interval_fps` measures delivered frame
intervals; `delivery_fps_including_open` also includes startup delay. CLI pacing
limits delivery to the configured FPS; these metrics are not sensor throughput
benchmarks. Stored snapshots use decoded BGR frames, regardless of USB transport.

Acquisition timestamps represent successful software delivery. A driver that
returns a frozen image with successful reads cannot be proven disconnected from
these timestamps alone; physical reconnect and scene-change checks are required.

Sources open no GUI and use `opencv-python-headless`. Snapshot encoding supports
JPG/PNG with explicit output paths inside configured storage; reports require JSON.
On failed capture, old artifacts from previous runs may remain: use the command's
exit status/current report, not the mere existence of an old JPEG, as evidence.

## Enumerating real modes

Use established device CLIs rather than inferring support from OpenCV's `set()`.
An existing FFmpeg on the development PC was used for the c922 enumeration:

```powershell
ffmpeg -hide_banner -list_options true -f dshow -i 'video=c922 Pro Stream Webcam'
```

It prints modes to stderr and may finish with a nonzero status because it is only
enumerating, not capturing an input. Use the actual device name from Windows.
See [FFmpeg DirectShow documentation](https://ffmpeg.org/ffmpeg-devices.html#dshow).

On the Pi, install `v4l-utils` through the OS package manager when validating hardware:

```sh
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
.venv/bin/python -m securitypi camera-info --config config/usb.example.toml
```

Some webcams expose multiple `/dev/video*` nodes; use the actual capture node.
Device indices can change after reconnect. If the index changes, exit with the
bounded error and rerun with the correct index; persistent device-path binding is
a future deployment improvement. See [Linux enumeration API](https://docs.kernel.org/userspace-api/media/v4l/vidioc-enum-fmt.html).

## Confirmed PC evidence

October 12, 2026 (America/New_York): Windows reports `c922 Pro Stream Webcam`.
OpenCV DirectShow captured 30 frames at 1280×720 with about 9.98 delivered FPS;
startup-inclusive delivery was about 3.29 FPS over 9.13 seconds. No reconnects were
needed. Local snapshot/report are in ignored `data/`, not in GitHub.

Readback reported YUY2 even though the MJPG property request returned true. FFmpeg
enumeration separately reported:

| Mode | Driver-advertised FPS range |
| --- | --- |
| YUY2 640×480 | 5–30 |
| YUY2 1280×720 | 5–10 |
| YUY2 1920×1080 | 5 |
| MJPEG 1280×720 | 5–approximately 60 |
| MJPEG 1920×1080 | 5–30 |

These are advertised Windows modes, not measured Pi performance. Explicit FFmpeg
format negotiation should be compared in the later streaming benchmark.
An invalid Windows camera index produced three failed attempts and exit code 2;
unit tests additionally simulate disconnect/reopen and blocked native calls.
Physical unplug/replug, Pi capture, and day/night window geometry remain unverified.
