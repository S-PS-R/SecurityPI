"""Explicit downloads of pinned official weights, with size and hash checks."""

import hashlib
import urllib.request
from pathlib import Path

from securitypi.vision import VisionError

MODELS = {
    "yolov8n": (12851049, "b2bc52f40e8e1c532427d5bde3575a5d5b571b739fab2c6df443733ed1589cbd"),
    "yolo26n": (9941957, "2e947b787d9e787b93a16772a5f55b1d4d8c4d86f53146149c5d6a642442d6f7"),
}
RELEASE = "https://github.com/ultralytics/assets/releases/download/v8.4.0"


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str, directory: Path):
    size, expected = MODELS[name]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.onnx"
    if target.exists():
        if target.stat().st_size != size or sha256(target) != expected:
            raise VisionError(
                "Existing model differs from the pinned artifact; move it explicitly."
            )
        return target
    # The two approved weights together are under 24 MiB. Do not accumulate versions.
    used = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    if used + size > 32 * 1024 * 1024:
        raise VisionError("Model directory would exceed its 32 MiB download budget.")
    temporary = target.with_suffix(".part")
    created = False
    try:
        with urllib.request.urlopen(f"{RELEASE}/{name}.onnx", timeout=30) as response:
            with temporary.open("xb") as stream:
                created = True
                remaining = size
                while block := response.read(min(1024 * 1024, remaining + 1)):
                    remaining -= len(block)
                    if remaining < 0:
                        raise VisionError("Model download exceeds the expected size.")
                    stream.write(block)
        if temporary.stat().st_size != size or sha256(temporary) != expected:
            raise VisionError("Model checksum or size verification failed.")
        temporary.replace(target)
    finally:
        if created:
            temporary.unlink(missing_ok=True)
    return target
