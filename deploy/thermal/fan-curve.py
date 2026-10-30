#!/usr/bin/env python3
"""Reviewable root-only boot edit; no live fan writes or reboot side effects."""

import argparse
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

START = "# BEGIN SecurityPI cooling"
END = "# END SecurityPI cooling"
CURVES = {"candidate": (45000, 55000, 62500, 70000), "stronger": (40000, 50000, 60000, 65000)}


def edited(text, curve):
    pattern = re.compile(r"(?m)^# BEGIN SecurityPI cooling\n.*?^# END SecurityPI cooling\n?", re.S)
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise ValueError("Malformed existing cooling block")
    outside = pattern.sub("", text)
    if re.search(r"(?m)^\s*(?:dtparam=.*fan_temp|dtoverlay=.*(?:pwm-fan|gpio-fan))", outside):
        raise ValueError("Existing fan override outside managed block; inspect manually")
    block = "[all]\n" + START + "\n"
    for index, temp in enumerate(CURVES[curve]):
        block += f"dtparam=fan_temp{index}={temp},fan_temp{index}_hyst=5000\n"
    block += END + "\n"
    # Replace only our marked block, preserving any existing section directive.
    if START in text:
        return pattern.sub(block.removeprefix("[all]\n"), text)
    return text.rstrip("\n") + "\n\n" + block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("curve", choices=CURVES)
    parser.add_argument("--apply", action="store_true", help="Back up and edit boot config as root")
    args = parser.parse_args()
    path = Path("/boot/firmware/config.txt")
    before = path.read_text()
    after = edited(before, args.curve)
    if not args.apply:
        import difflib

        print(
            "".join(
                difflib.unified_diff(
                    before.splitlines(True),
                    after.splitlines(True),
                    fromfile=str(path),
                    tofile=str(path),
                )
            ),
            end="",
        )
        return
    if os.geteuid() != 0:
        parser.error("--apply requires sudo in the Pi terminal")
    backup = path.with_name("config.txt.securitypi-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(path, backup)
    path.write_text(after)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    print(f"Backup: {backup}\nCurve written. Reboot required; verify kernel trips afterward.")


if __name__ == "__main__":
    main()
