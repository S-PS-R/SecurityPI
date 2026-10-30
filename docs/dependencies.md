# Dependency decisions (milestones 1–2)

Direct packages are pinned in `pyproject.toml`; the resolved runtime/test sets are
in `requirements/`. Install the requirements before installing this project with
`--no-deps --no-build-isolation`. Pins include transitive versions and a Windows-only
colorama marker. They target the supported Python range and are checked by CI.
These are version constraints, not a cryptographic artifact lock.

| Package | Purpose | Upstream license/source |
| --- | --- | --- |
| FastAPI | Domain HTTP foundation / OpenAPI | MIT; [official project](https://github.com/fastapi/fastapi) |
| Pydantic | Typed configuration / response validation | MIT; [official project](https://github.com/pydantic/pydantic) |
| Uvicorn | Local ASGI server | BSD-3-Clause; [official project](https://github.com/Kludex/uvicorn) |
| HTTPX | In-process API tests; future mockable HTTP adapters | BSD-3-Clause; [official project](https://github.com/encode/httpx) |
| pytest | Behavioral checks | MIT; [official project](https://github.com/pytest-dev/pytest) |
| Ruff | Lint and formatting | MIT; [official project](https://github.com/astral-sh/ruff) |
| setuptools | Package/CLI installation | MIT; [official project](https://github.com/pypa/setuptools) |
| opencv-python-headless 4.14.0.94 | USB/file capture and snapshot encoding without GUI dependencies | Packaging MIT; OpenCV Apache-2.0; embedded libraries retain their licenses; [upstream guidance](https://github.com/opencv/opencv-python#licensing) |
| NumPy 2.4.6 | Frame arrays / synthetic sources | BSD-3-Clause; [official license](https://numpy.org/doc/stable/license.html) |

Milestone 2 adds the headless OpenCV 4 series and NumPy. Their PyPI metadata and
Windows/Linux ARM64 wheel availability were checked. NumPy 2.5 requires Python
3.12+, so the Python 3.11-compatible 2.4.6 release is pinned. OpenCV 5 is not selected
for this initial adapter. Do not install multiple OpenCV package variants together:
they share the same `cv2` namespace. Pi installation/performance remain unverified.

Model runtimes, model weights, media-server binaries, tracking helpers, and Home Assistant itself will
be pinned separately when needed. Licensing of weights is distinct from their
runtime. No arbitrary forks or floating Git package installs are used.

When updating dependencies: inspect upstream release notes/advisories and Python
support, resolve clean runtime/dev environments, update both requirements and
direct pins, run `pip check`, lint/tests and CI, and record target Pi limitations.
Do not copy a developer environment's unrelated packages into requirements.

## Pi vision candidate

OpenCV DNN runs explicitly downloaded COCO ONNX models without adding a training
framework or another inference runtime. Optional `requirements/vision.txt` adds
`lapx==0.10.0` (BSD-2-Clause, https://github.com/rathaROG/lapx) for assignment.
The MIT ByteTrack core is vendored at commit
`d1bf0191adff59bc8fcfeaa0b33d3d1642552a99` with its license and adaptation notes.
NumPy solves and vectorized IoU avoid SciPy/cython_bbox/PyTorch dependencies.
Weights use official Ultralytics assets v8.4.0, exact hashes and size limits;
upstream model licensing remains separate. See [vision](vision.md) for measured
footprint, tests, calibration uncertainty and the optional comparison workflow.

The local phone bridge/notification/soak candidate adds no package dependencies:
HTTP delivery, bounded SQLite storage and process/resource supervision use the
Python standard library; the API reuses FastAPI. Home Assistant is not installed
by these commands. Qwen/llama.cpp/Ollama and model-training packages remain absent.


## Optional CPU inference backend — October 28, 2026

`requirements/onnxruntime.txt` adds the CPU-only ONNX Runtime 1.31.1 package
(MIT), flatbuffers 25.12.19 (Apache-2.0), protobuf 7.36.2 (BSD-3-Clause), and the
already-used packaging 26.3. The runtime reuses the pinned NumPy and existing
ONNX weights; it adds no training, CUDA, ONNX-export or language-model stack.
The package set adds approximately 62 MiB on this Pi after removing the isolated
comparison install. Exact downloaded wheel hashes are recorded in ignored local
admission notes. The optional extra is also declared in pyproject.toml.

The official ARM64 CPython 3.13 CPU wheel was installed and exercised on this
16 KiB-page Pi. This is direct target evidence, not an inference from the
platform table. The portable default remains OpenCV, so existing environments
and CI do not require the extra package. Missing optional dependencies fail with
an actionable message; no runtime auto-download or silent backend fallback occurs.

Upstream [installation](https://onnxruntime.ai/docs/install/),
[1.31.1 release](https://github.com/microsoft/onnxruntime/releases/tag/v1.31.1),
[security advisories](https://github.com/microsoft/onnxruntime/security/advisories)
and [thread guidance](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)
were reviewed. The selected provider is explicitly CPUExecutionProvider, with
bounded inference threads, one inter-op thread and idle spinning disabled.
Runtime telemetry is disabled before creating the inference session.
Disabling its CPU memory arena reduced measured peak RSS without materially
changing latency. Detection agreement was checked against OpenCV on the same
twelve existing images; this does not establish field accuracy.
