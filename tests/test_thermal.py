"""Thermal safeguards are exercised without a camera, fan or LED device."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from securitypi.thermal import Display, Workload, led_pixels, phase_at, safety_reason, summarize


def healthy():
    return dict(
        temperature_c=60,
        throttle_flags=0,
        available_memory_mib=600,
        free_disk_mib=1000,
        camera_fresh=True,
        frame_age_s=0.5,
        ha_status=200,
        ha_age_s=1,
    )


@pytest.mark.parametrize(
    ("seconds", "phase"),
    [
        (0, "normal"),
        (299.9, "normal"),
        (300, "application"),
        (1499.9, "application"),
        (1500, "cpu_peak"),
        (1799.9, "cpu_peak"),
        (1800, "complete"),
    ],
)
def test_phases(seconds, phase):
    assert phase_at(seconds) == phase


@pytest.mark.parametrize(
    ("temp", "colour"),
    [(64.9, 12 << 5), (65, (6 << 11) | (12 << 5)), (74.9, (6 << 11) | (12 << 5)), (75, 6 << 11)],
)
def test_led(temp, colour):
    pixels = led_pixels(temp)
    assert len(pixels) == 128
    assert {int.from_bytes(pixels[i : i + 2], "little") for i in range(0, 128, 2)} == {0, colour}
    assert pixels[:16] == bytes(16)
    with pytest.raises(ValueError):
        led_pixels(float("nan"))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux framebuffer I/O")
def test_framebuffer_restore_and_reject_layout(tmp_path):
    root = tmp_path / "sys"
    fb = root / "fb4"
    fb.mkdir(parents=True)
    (root / "fbcon").mkdir()
    dev = tmp_path / "dev"
    dev.mkdir()
    for name, text in dict(
        name="RPi-Sense FB", virtual_size="8,8", bits_per_pixel="16", stride="16"
    ).items():
        (fb / name).write_text(text)
    original = bytes(range(128))
    (dev / "fb4").write_bytes(original)
    display = Display(root, dev)
    display.show(62)
    assert (dev / "fb4").read_bytes() != original
    display.close()
    assert (dev / "fb4").read_bytes() == original
    (fb / "virtual_size").write_text("1920,1080")
    with pytest.raises(ValueError, match="layout"):
        Display(root, dev)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("temperature_c", 80),
        ("temperature_c", None),
        ("temperature_c", float("nan")),
        ("throttle_flags", 1),
        ("available_memory_mib", 255),
        ("free_disk_mib", 255),
        ("camera_fresh", False),
        ("frame_age_s", 3.1),
        ("ha_age_s", 16),
        ("ha_status", 500),
    ],
)
def test_safety_stops(key, value):
    sample = healthy()
    assert safety_reason(sample) is None
    sample[key] = value
    assert safety_reason(sample)
    assert safety_reason(healthy(), 9) is None
    assert safety_reason(healthy(), 10) == "commanded fan stalled"
    sample = healthy()
    sample["throttle_flags"] = 0x10000
    assert safety_reason(sample) is None  # historical flags recorded separately


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process groups")
def test_owned_process_group_cleanup():
    load = Workload()
    load.process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    pid = load.process.pid
    load.stop()
    assert load.process.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


def test_summary_does_not_claim_complete():
    rows = [
        dict(
            phase="application",
            elapsed_s=i,
            temperature_c=60 + i / 100,
            detection_fps=4,
            frame_age_s=0.5,
            ha_ms=10,
            fan_rpm=5000,
            available_memory_mib=600,
        )
        for i in range(300)
    ]
    report = summarize(rows, "interrupted")
    assert report["stop_reason"] == "interrupted"
    assert report["duration_s"] == 299
    assert report["phases"]["application"]["still_warming"]
    assert report["phases"]["application"]["peak_c"] == 62.99


@pytest.mark.skipif(sys.platform != "linux", reason="Linux hardware runner")
@pytest.mark.parametrize("failure", [None, "sensor", "budget"])
def test_runner_deadlines_logs_and_cleanup(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace

    import securitypi.thermal as thermal

    (tmp_path / "home-assistant-setup").mkdir()
    (tmp_path / "home-assistant-setup/notifications.env").write_text("SECURITYPI_HA_TOKEN=test")
    calls = []
    clock = [0]

    def sleep(seconds):
        clock[0] += max(seconds, 300)

    monkeypatch.setattr(thermal.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(thermal.time, "sleep", sleep)

    class FakeDisplay:
        original = bytes(128)

        def __init__(self):
            pass

        def show(self, temp):
            calls.append("show")

        def close(self):
            calls.append("restore")

    class FakeHealth:
        def __init__(self, token):
            pass

        def close(self):
            calls.append("health-close")

    class FakeLoad:
        process = None

        def start(self, *args):
            calls.append("load-start")

        def stop(self):
            calls.append("load-stop")

    def reading(*args):
        sample = healthy()
        sample.update(fan_pwm=125, fan_rpm=5000, detection_fps=4, ha_ms=5)
        if failure == "sensor" and "show" in calls:
            sample["temperature_c"] = 80
        return sample

    monkeypatch.setattr(thermal, "Display", FakeDisplay)
    monkeypatch.setattr(thermal, "Health", FakeHealth)
    monkeypatch.setattr(thermal, "Workload", FakeLoad)
    monkeypatch.setattr(thermal, "read_hardware", reading)
    monkeypatch.setattr(thermal, "verify_fan_curve", lambda case: None)
    real_glob = Path.glob
    fan = tmp_path / "fan"
    fan.mkdir()
    (fan / "name").write_text("pwmfan")

    def glob(path, pattern, **kwargs):
        if str(path) == "/sys/class/hwmon":
            return iter([fan])
        return real_glob(path, pattern, **kwargs)

    monkeypatch.setattr(Path, "glob", glob)
    if failure == "budget":
        monkeypatch.setattr(thermal, "CSV_LIMIT", 1)
    rc = thermal.run_thermal(
        SimpleNamespace(storage=SimpleNamespace(directory=tmp_path)),
        SimpleNamespace(case="lid-off"),
    )
    import json

    report = json.loads(next((tmp_path / "thermal-tests").glob("*/summary.json")).read_text())
    assert rc == (0 if failure is None else 2)
    assert calls[-3:] == ["load-stop", "health-close", "restore"]
    if failure is None:
        assert calls.count("load-start") == 1
        assert report["stop_reason"] == "completed"
    else:
        assert report["stop_reason"] != "completed"
    assert next((tmp_path / "thermal-tests").glob("*/samples.csv")).stat().st_size < 10000


def test_fan_patch_preserves_config_and_is_idempotent():
    import importlib.util

    helper = Path(__file__).resolve().parents[1] / "deploy/thermal/fan-curve.py"
    spec = importlib.util.spec_from_file_location("fan_curve", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = "[pi5]\ndtoverlay=nospi10\n[all]\n"
    candidate = module.edited(original, "candidate")
    assert candidate.startswith(original)
    assert candidate.count("_hyst=5000") == 4
    assert module.edited(candidate, "candidate") == candidate
    stronger = module.edited(candidate, "stronger")
    assert stronger.count(module.START) == 1
    assert "fan_temp3=65000" in stronger
    assert "fan_temp4" not in stronger
    assert "dtparam=fan_temp0=45000,fan_temp0_hyst=5000" in candidate
    assert "dtparam=fan_temp1=55000,fan_temp1_hyst=5000" in candidate
    assert "dtparam=fan_temp2=62500,fan_temp2_hyst=5000" in candidate
    assert "dtparam=fan_temp3=70000,fan_temp3_hyst=5000" in candidate
    old_block = (
        original
        + module.START
        + "\n"
        + (
            "dtparam=fan_temp1=45000,fan_temp1_hyst=5000\n"
            "dtparam=fan_temp4=70000,fan_temp4_hyst=5000\n"
        )
        + module.END
        + "\n"
    )
    corrected = module.edited(old_block, "candidate")
    assert "fan_temp4" not in corrected
    assert corrected.count(module.START) == 1
    assert "fan_temp0=45000" in corrected
    with pytest.raises(ValueError):
        module.edited("dtparam=fan_temp1=50000\n", "candidate")
    with pytest.raises(ValueError):
        module.edited(module.START + "\n", "candidate")


@pytest.mark.parametrize(
    "actual",
    [
        [50000, 45000, 55000, 62500],  # Off-by-one firmware parameter mapping.
        [50000, 60000, 67500, 75000],  # Saved configuration without reboot.
        [45000, 55000, 62500, 70000],
    ],
)
def test_effective_curve_required_before_stress(tmp_path, actual):
    from securitypi.thermal import verify_fan_curve

    for index, temperature in enumerate(actual, 1):
        prefix = tmp_path / f"trip_point_{index}"
        prefix.with_name(prefix.name + "_temp").write_text(str(temperature))
        prefix.with_name(prefix.name + "_type").write_text("active")
        prefix.with_name(prefix.name + "_hyst").write_text("5000")
    if actual == [45000, 55000, 62500, 70000]:
        verify_fan_curve("lid-on-tuned", tmp_path)
        (tmp_path / "trip_point_1_hyst").write_text("1000")
    with pytest.raises(ValueError, match="Effective fan curve"):
        verify_fan_curve("lid-on-tuned", tmp_path)


def test_thermal_hardware_runner_rejects_non_linux(monkeypatch):
    from securitypi.thermal import run_thermal

    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="require Linux"):
        run_thermal(None, None)
