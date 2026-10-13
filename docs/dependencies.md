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
