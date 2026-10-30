"""Bounded Linux hardware soak. No recordings, no push delivery, no new dependencies."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from securitypi.state import read_vision, write_json


def process_usage(groups):
    """RSS includes shared pages more than once: a conservative process-family budget."""
    rss, ticks = 0, 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) in groups:  # pgrp, excluding pid/comm
                ticks += int(fields[11]) + int(fields[12])
                rss += int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    return rss / 1048576, ticks / os.sysconf("SC_CLK_TCK")


def host_resources(directory):
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    return {
        "available_memory_mib": int(memory["MemAvailable"].split()[0]) / 1024,
        "free_disk_mib": shutil.disk_usage(directory).free / 1048576,
        "temperature_c": float(thermal.read_text()) / 1000 if thermal.exists() else None,
    }


def limit_reason(sample):
    if sample["rss_mib"] > 650:
        return "process_memory_limit"
    if sample["available_memory_mib"] < 256:
        return "host_memory_limit"
    if sample["free_disk_mib"] < 256:
        return "disk_limit"
    if sample["temperature_c"] is not None and sample["temperature_c"] >= 80:
        return "temperature_limit"
    return None


def stop_workers(workers):
    for worker in workers:
        if worker.poll() is None:
            try:
                worker.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 45
    for worker in workers:
        try:
            worker.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        # Clean surviving capture children too, even if their parent exited first.
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        worker.wait()


def run_soak(settings, args):
    import fcntl
    import resource

    directory = settings.storage.directory
    if read_vision(directory)["monitoring"]:
        raise ValueError("Analysis is already active; stop it before starting a soak.")
    family = socket.AF_INET6 if settings.server.host == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((settings.server.host, settings.server.port))
        except OSError:
            raise ValueError(
                "API port is already in use; stop its service before a soak."
            ) from None
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / "soak.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("Another soak already owns this storage directory.") from None
    report_path = directory / "soak-status.json"
    duration = args.seconds
    started = time.monotonic()
    report = {
        "state": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "duration_seconds": duration,
        "supervisor_pid": os.getpid(),
        "samples": 0,
        "peak_rss_mib": 0,
        "peak_temperature_c": None,
        "scope": "camera + detector + tracking + loopback API + notification dry run",
        "phone_delivery": "not_tested",
        "real_push_enabled": False,
    }
    workers, logs = [], []
    reason = "failed"

    def request_stop(_signum, _frame):
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, request_stop)

    def child_limits():
        os.nice(5)
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1048576, 8 * 1048576))

    try:
        write_json(report_path, report)
        base = [sys.executable, "-m", "securitypi"]
        commands = [
            base + ["analyze", "--config", str(args.config), "--seconds", str(duration)],
            base + ["serve", "--config", str(args.config)],
            base
            + ["notify", "--config", str(args.config), "--seconds", str(duration), "--dry-run"],
        ]
        for name, command in zip(("analysis", "api", "notifications"), commands, strict=True):
            log = (directory / f"soak-{name}.log").open("w")
            logs.append(log)
            workers.append(
                subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    preexec_fn=child_limits,
                    env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                )
            )
        report["worker_pids"] = [w.pid for w in workers]
        write_json(report_path, report)
        last_cpu, last_time = 0, started
        opener = build_opener(ProxyHandler({}))
        host = "[::1]" if settings.server.host == "::1" else settings.server.host
        with (directory / "soak-samples.jsonl").open("w") as samples:
            while time.monotonic() - started < duration:
                time.sleep(min(30, max(0, duration - (time.monotonic() - started))))
                now = time.monotonic()
                if now - started >= duration:
                    reason = "duration_limit"
                    break
                if any(w.poll() is not None for w in workers):
                    reason = "worker_exited"
                    break
                rss, cpu = process_usage({w.pid for w in workers})
                sample = {"elapsed_seconds": round(now - started, 1), "rss_mib": round(rss, 2)}
                sample.update(host_resources(directory))
                sample["cpu_core_equivalents"] = round((cpu - last_cpu) / (now - last_time), 2)
                last_cpu, last_time = cpu, now
                vision = read_vision(directory)
                sample.update(
                    frames_analyzed=vision.get("frames_analyzed", 0),
                    frame_age_seconds=vision["age_seconds"],
                )
                try:
                    with opener.open(
                        f"http://{host}:{settings.server.port}/api/vision", timeout=3
                    ) as r:
                        sample["api_monitoring"] = json.loads(r.read(131072))["monitoring"]
                except (OSError, ValueError, KeyError):
                    sample["api_monitoring"] = False
                samples.write(json.dumps(sample, allow_nan=False) + "\n")
                samples.flush()
                report.update(
                    last_sample=sample,
                    samples=report["samples"] + 1,
                    peak_rss_mib=max(report["peak_rss_mib"], sample["rss_mib"]),
                )
                temp = sample["temperature_c"]
                if temp is not None:
                    report["peak_temperature_c"] = max(report["peak_temperature_c"] or temp, temp)
                write_json(report_path, report)
                reason = limit_reason(sample)
                if reason:
                    break
                if not vision["monitoring"] or not sample["api_monitoring"]:
                    reason = "stale_monitoring"
                    break
            else:
                reason = "duration_limit"
    except KeyboardInterrupt:
        reason = "interrupted"
    except Exception:
        reason = "failed"
        raise
    finally:
        stop_workers(workers)
        if reason == "duration_limit" and any(
            worker.returncode not in (0, 130, -signal.SIGINT) for worker in workers
        ):
            reason = "worker_failed"
        for log in logs:
            log.close()
        report.update(
            state="complete" if reason == "duration_limit" else "stopped",
            reason=reason,
            ended_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=round(time.monotonic() - started, 1),
            worker_exit_codes=[w.returncode for w in workers],
        )
        write_json(report_path, report)
        signal.signal(signal.SIGTERM, previous_term)
        lock.close()
    print(json.dumps(report))
    return 0 if reason == "duration_limit" else 2
