# Milestone 1 dependency decisions

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

Only the backend foundation and test tools are admitted now. Model runtimes,
model weights, media binaries, tracking helpers, and Home Assistant itself will
be pinned separately when needed. Licensing of weights is distinct from their
runtime. No arbitrary forks or floating Git package installs are used.

When updating dependencies: inspect upstream release notes/advisories and Python
support, resolve clean runtime/dev environments, update both requirements and
direct pins, run `pip check`, lint/tests and CI, and record target Pi limitations.
Do not copy a developer environment's unrelated packages into requirements.
