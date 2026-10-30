"""Opt-in, bounded cooling comparison. Never owns the camera or changes fan control."""

import csv
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from pathlib import Path

from securitypi.soak import host_resources
from securitypi.state import read_vision, write_json

DIGITS = (
    ("111", "101", "101", "101", "111"),
    ("010", "110", "010", "010", "111"),
    ("111", "001", "111", "100", "111"),
    ("111", "001", "111", "001", "111"),
    ("101", "101", "111", "001", "001"),
    ("111", "100", "111", "001", "111"),
    ("111", "100", "111", "101", "111"),
    ("111", "001", "010", "010", "010"),
    ("111", "101", "111", "101", "111"),
    ("111", "101", "111", "001", "111"),
)
CSV_LIMIT = 2 * 1024**2
PHASES = ((300, "normal"), (1500, "application"), (1800, "cpu_peak"))


def phase_at(seconds):
    return next((name for end, name in PHASES if seconds < end), "complete")


def led_pixels(temperature):
    if not math.isfinite(temperature):
        raise ValueError("Invalid temperature")
    # Low fixed RGB565 channel intensity: 6/31, 12/63, 6/31.
    colour = (
        12 << 5 if temperature < 65 else ((6 << 11) | (12 << 5) if temperature < 75 else 6 << 11)
    )
    value = min(99, max(0, int(temperature + 0.5)))
    pixels = bytearray(128)
    for offset, digit in ((0, value // 10), (4, value % 10)):
        for y, row in enumerate(DIGITS[digit]):
            for x, bit in enumerate(row):
                if bit == "1":
                    index = ((y + 1) * 8 + offset + x) * 2
                    pixels[index : index + 2] = colour.to_bytes(2, "little")
    return pixels


class Display:
    def __init__(self, root=Path("/sys/class/graphics"), devices=Path("/dev")):
        matches = [
            p
            for p in root.glob("fb*")
            if (p / "name").is_file() and (p / "name").read_text().strip() == "RPi-Sense FB"
        ]
        if len(matches) != 1:
            raise ValueError("Expected one RPi-Sense FB display")
        fb = matches[0]
        if (
            (fb / "virtual_size").read_text().strip() != "8,8"
            or int((fb / "bits_per_pixel").read_text()) != 16
            or int((fb / "stride").read_text()) != 16
        ):
            raise ValueError("Unexpected Sense HAT framebuffer layout")
        self.fd = os.open(devices / fb.name, os.O_RDWR)
        self.original = os.pread(self.fd, 128, 0)
        if len(self.original) != 128:
            os.close(self.fd)
            raise ValueError("Cannot preserve display")

    def show(self, temperature):
        if os.pwrite(self.fd, led_pixels(temperature), 0) != 128:
            raise OSError("Short framebuffer write")

    def close(self):
        try:
            os.pwrite(self.fd, self.original, 0)
        finally:
            os.close(self.fd)


def safety_reason(sample, stalled_seconds=0):
    temp = sample.get("temperature_c")
    if temp is None or not math.isfinite(temp) or not 0 < temp < 120:
        return "temperature sensing failed"
    if temp >= 80:
        return "temperature reached 80 C"
    if sample.get("throttle_flags", 0) & 0xF:
        return "active throttling or undervoltage"
    if stalled_seconds >= 10:
        return "commanded fan stalled"
    if sample.get("available_memory_mib", 0) < 256:
        return "available RAM below 256 MiB"
    if sample.get("free_disk_mib", 0) < 256:
        return "free disk below 256 MiB"
    if not sample.get("camera_fresh") or sample.get("frame_age_s", 99) > 3:
        return "camera output stale"
    if sample.get("ha_age_s", 99) > 15 or sample.get("ha_status") != 200:
        return "Home Assistant unavailable"
    return None


class Workload:
    """One bounded child process; parent death/deadline also ends its children."""

    def __init__(self):
        self.process = None

    def start(self, directory, token_file, seconds):
        env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "securitypi.thermal",
                str(directory),
                str(token_file),
                str(seconds),
            ],
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self):
        if self.process:
            # Always signal the group, even if the supervisor has already exited.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)


def token_from(path):
    for line in path.read_text().splitlines():
        if line.startswith("SECURITYPI_HA_TOKEN="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise ValueError("Home Assistant token missing")


def request(path, token):
    return urllib.request.Request(
        "http://127.0.0.1:8123" + path, headers={"Authorization": "Bearer " + token}
    )


class Health:
    def __init__(self, token):
        self.stop = threading.Event()
        self.latest = {"ha_status": 0, "ha_ms": None, "checked": 0}
        self.token = token
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while not self.stop.is_set():
            start = time.monotonic()
            try:
                with opener.open(request("/api/", self.token), timeout=2) as response:
                    response.read(65536)
                    self.latest = {
                        "ha_status": response.status,
                        "ha_ms": (time.monotonic() - start) * 1000,
                        "checked": time.monotonic(),
                    }
            except (OSError, HTTPException):
                self.latest = {"ha_status": 0, "ha_ms": None, "checked": time.monotonic()}
            self.stop.wait(2)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)


def read_hardware(directory, fan, health):
    vision = read_vision(directory)
    sample = host_resources(directory)
    flags = subprocess.check_output(["vcgencmd", "get_throttled"], timeout=2, text=True)
    sample.update(
        fan_rpm=int((fan / "fan1_input").read_text()),
        fan_pwm=int((fan / "pwm1").read_text()),
        cpu_mhz=int(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").read_text())
        / 1000,
        load_1m=os.getloadavg()[0],
        throttle_flags=int(flags.strip().split("=")[1], 16),
        detection_fps=vision.get("analysis_fps"),
        frame_age_s=vision.get("age_seconds"),
        camera_fresh=vision["fresh"],
    )
    usage = Path("/proc/self/status").read_text().split("VmRSS:")[1].split()[0]
    sample["monitor_rss_mib"] = int(usage) / 1024
    sample["fan_state"] = int(Path("/sys/class/thermal/cooling_device0/cur_state").read_text())
    for service in ("securitypi-vision.service", "securitypi-notify.service"):
        group = (
            Path("/sys/fs/cgroup/user.slice")
            / f"user-{os.getuid()}.slice"
            / (f"user@{os.getuid()}.service/app.slice/{service}/memory.current")
        )
        sample[service.split(".")[0].replace("-", "_") + "_mib"] = (
            int(group.read_text()) / 1048576 if group.exists() else None
        )

    sample.update({k: v for k, v in health.latest.items() if k != "checked"})
    sample["ha_age_s"] = time.monotonic() - health.latest["checked"]
    return sample


def summarize(rows, reason):
    result = {"stop_reason": reason, "samples": len(rows), "phases": {}}
    if not rows:
        return result
    result["duration_s"] = rows[-1]["elapsed_s"]
    for name in ("normal", "application", "cpu_peak"):
        selected = [r for r in rows if r["phase"] == name]
        if not selected:
            continue
        tail = selected[-300:]
        temps = [r["temperature_c"] for r in tail]
        trend = statistics.mean(temps[-60:]) - statistics.mean(temps[:60])
        result["phases"][name] = {
            "samples": len(selected),
            "peak_c": max(r["temperature_c"] for r in selected),
            "final_5min_mean_c": statistics.mean(temps),
            "tail_temperature_change_c": trend,
            "still_warming": trend > 0.5,
            "mean_fps": statistics.mean(r["detection_fps"] or 0 for r in selected),
            "max_frame_age_s": max(r["frame_age_s"] or 0 for r in selected),
            "mean_ha_ms": statistics.mean(r["ha_ms"] or 0 for r in selected),
            "fan_rpm_range": [
                min(r["fan_rpm"] for r in selected),
                max(r["fan_rpm"] for r in selected),
            ],
            "min_available_memory_mib": min(r["available_memory_mib"] for r in selected),
        }
    return result


def verify_fan_curve(case, root=Path("/sys/class/thermal/thermal_zone0")):
    """Read effective kernel trips, never infer activation from config.txt."""
    expected = {
        "lid-off": [50000, 60000, 67500, 75000],
        "lid-on": [50000, 60000, 67500, 75000],
        "lid-on-tuned": [45000, 55000, 62500, 70000],
        "lid-on-stronger": [40000, 50000, 60000, 65000],
    }[case]
    active = sorted(
        (
            p
            for p in root.glob("trip_point_*_temp")
            if p.with_name(p.name.replace("_temp", "_type")).read_text().strip() == "active"
        ),
        key=lambda p: int(p.name.split("_")[2]),
    )
    actual = [int(p.read_text()) for p in active]
    hysteresis = [int(p.with_name(p.name.replace("_temp", "_hyst")).read_text()) for p in active]
    if actual != expected or hysteresis != [5000] * 4:
        raise ValueError(f"Effective fan curve does not match {case}: {actual}, hyst={hysteresis}")


def run_thermal(settings, args):
    if sys.platform != "linux":
        raise ValueError("Thermal hardware tests require Linux")
    import fcntl

    directory = settings.storage.directory
    output = directory / "thermal-tests"
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Explicit budget includes existing runs; no automatic deletion of previous results.
    if sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) > 20 * 1024**2:
        raise ValueError("Thermal log budget (24 MiB) reached")
    lock = (output / ".lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    case = args.case
    path = output / f"{stamp}-{case}"
    path.mkdir(mode=0o700)
    token_file = directory / "home-assistant-setup/notifications.env"
    token = token_from(token_file)
    fan = next(
        p
        for p in Path("/sys/class/hwmon").glob("hwmon*")
        if (p / "name").read_text().strip() == "pwmfan"
    )
    rows, reason, display = [], "interrupted", None
    load = Workload()
    health = Health(token)

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    old = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    start = time.monotonic()
    stalled = 0
    try:
        time.sleep(2.1)
        initial = read_hardware(directory, fan, health)
        problem = safety_reason(initial)
        if problem or initial["available_memory_mib"] < 512:
            raise ValueError(problem or "Preflight requires 512 MiB available RAM")
        verify_fan_curve(case)
        display = Display()
        (path / "led-original.rgb565").write_bytes(display.original)
        trips = {
            p.name: p.read_text().strip()
            for p in Path("/sys/class/thermal/thermal_zone0").glob("trip_point_*_temp")
        }
        write_json(
            path / "metadata.json",
            {
                "case": case,
                "started_at": datetime.now(UTC).isoformat(),
                "initial": initial,
                "trips_millicelsius": trips,
                "schedule_seconds": PHASES,
                "led": "RGB565 6/31 red, 12/63 green",
                "workload": (
                    "2 HA streams; history every 10s; 3 JPEG writes every 30s; 4 NumPy peak workers"
                ),
            },
        )
        start = time.monotonic()
        with (path / "samples.csv").open("w", newline="") as stream:
            writer = None
            previous = None
            while True:
                elapsed = time.monotonic() - start
                phase = phase_at(elapsed)
                if phase == "complete":
                    reason = "completed"
                    break
                if phase != previous:
                    if phase == "application":
                        load.start(path, token_file, 1500)
                    print(
                        json.dumps({"case": case, "phase": phase, "elapsed_s": round(elapsed)}),
                        flush=True,
                    )
                    previous = phase
                sample = read_hardware(directory, fan, health)
                stalled = stalled + 1 if sample["fan_pwm"] > 0 and sample["fan_rpm"] == 0 else 0
                sample.update(
                    timestamp=datetime.now(UTC).isoformat(),
                    phase=phase,
                    case=case,
                    elapsed_s=round(elapsed, 3),
                )
                problem = safety_reason(sample, stalled)
                if load.process and load.process.poll() is not None and elapsed < 1798:
                    problem = "application load worker exited early"
                if problem:
                    reason = problem
                    write_json(path / "stop-sample.json", sample)
                    break
                display.show(sample["temperature_c"])
                rows.append(sample)
                if writer is None:
                    writer = csv.DictWriter(stream, fieldnames=list(sample))
                    writer.writeheader()
                writer.writerow(sample)
                stream.flush()
                if stream.tell() > CSV_LIMIT:
                    reason = "per-run CSV budget reached"
                    break
                if int(elapsed) % 10 == 0:
                    write_json(path / "status.json", sample)
                time.sleep(max(0, start + len(rows) - time.monotonic()))
    except KeyboardInterrupt:
        reason = "interrupted"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    finally:
        # Run every cleanup even if one device/process cleanup fails.
        for sig in old:
            signal.signal(sig, signal.SIG_IGN)
        operations = [load.stop, health.close] + ([display.close] if display else [])
        for operation in operations:
            try:
                operation()
            except (OSError, subprocess.SubprocessError) as exc:
                reason += f"; cleanup failed: {type(exc).__name__}"

        for sig, handler in old.items():
            signal.signal(sig, handler)
        result = summarize(rows, reason)
        stop_sample = path / "stop-sample.json"
        if stop_sample.exists():
            result["stop_sample"] = json.loads(stop_sample.read_text())
        result["case"] = case
        result["finished_at"] = datetime.now(UTC).isoformat()
        write_json(path / "summary.json", result)
        lock.close()
        print(json.dumps(result), flush=True)
    return 0 if reason == "completed" else 2


def load_worker(output, token_file, seconds):
    """Private child entry point with fixed workload, deadlines and parent watchdog."""
    import cv2
    import numpy as np

    cv2.setNumThreads(1)
    os.nice(19)
    parent = os.getppid()
    deadline = time.monotonic() + min(1500, max(1, seconds))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    token = token_from(token_file)
    errors = []
    byte_counts = [0, 0]
    history_requests = bursts = 0
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def preview(index):
        try:
            with opener.open(
                request("/api/camera_proxy_stream/camera.bedroom_securitypi_preview", token),
                timeout=5,
            ) as response:
                if response.status != 200:
                    raise OSError("Preview status failed")
                while not stop.is_set() and time.monotonic() < deadline:
                    chunk = response.read(16384)
                    if not chunk:
                        raise OSError("Preview ended")
                    byte_counts[index] += len(chunk)
        except (OSError, HTTPException):
            errors.append("preview stream failed")

    threads = [threading.Thread(target=preview, args=(i,), daemon=True) for i in range(2)]
    for thread in threads:
        thread.start()
    cpu = []
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    # Deterministic textured image avoids unrealistically tiny all-black JPEGs.
    image[:] = np.random.default_rng(42).integers(0, 256, image.shape, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok or encoded.nbytes > 2 * 1024**2:
        raise ValueError("Synthetic JPEG encoding failed or exceeds budget")
    started = time.monotonic()
    next_history = next_burst = started
    try:
        with tempfile.TemporaryDirectory(prefix="scratch-", dir=output) as scratch:
            while not stop.is_set() and time.monotonic() < deadline and os.getppid() == parent:
                if errors:
                    raise OSError(errors[0])
                now = time.monotonic()
                if now >= next_history:
                    since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
                    url = (
                        "/api/history/period/"
                        + since
                        + (
                            "?filter_entity_id=sensor.securitypi_people_visible,"
                            "sensor.securitypi_vehicles_visible&minimal_response&no_attributes"
                        )
                    )
                    with opener.open(request(url, token), timeout=3) as response:
                        if response.status != 200 or len(response.read(262145)) > 262144:
                            raise OSError("History response failed/exceeds budget")
                    history_requests += 1
                    write_json(
                        output / "load-status.json",
                        {
                            "preview_bytes": byte_counts,
                            "history_requests": history_requests,
                            "snapshot_bursts": bursts,
                            "cpu_workers": len(cpu),
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )
                    next_history = now + 10
                if now >= next_burst:
                    for index in range(3):
                        target = Path(scratch) / f"{index}.jpg"
                        with target.open("wb") as stream:
                            stream.write(encoded.tobytes())
                            stream.flush()
                            os.fsync(stream.fileno())
                        target.unlink()
                    bursts += 1
                    next_burst = now + 30
                if now - started >= 1200 and not cpu:
                    for _ in range(4):
                        cpu.append(
                            subprocess.Popen(
                                [
                                    sys.executable,
                                    "-c",
                                    CPU_CODE,
                                    str(os.getpid()),
                                    str(max(0, deadline - now)),
                                ],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                        )
                if any(p.poll() is not None for p in cpu) and deadline - now > 3:
                    raise OSError("CPU worker exited early")
                stop.wait(0.5)
    finally:
        stop.set()
        for child in cpu:
            if child.poll() is None:
                child.terminate()
        for child in cpu:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)


CPU_CODE = """
import os, sys, time
import numpy as np
parent = int(sys.argv[1])
end = time.monotonic() + min(300, float(sys.argv[2]))
a = np.ones((256, 256), dtype=np.float32)
b = np.empty_like(a)
while time.monotonic() < end and os.getppid() == parent:
    np.matmul(a, a, out=b)
"""

if __name__ == "__main__":
    try:
        load_worker(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]))
    except Exception as exc:
        write_json(Path(sys.argv[1]) / "load-failure.json", {"error_type": type(exc).__name__})
        raise
