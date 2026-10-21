# Contributing

Use Python 3.11 or 3.12 and install the development dependencies in a virtual environment:

```bash
python -m pip install -e '.[dev]'
```

Implementation code lives in `src/measure_tiktok/`; tests live in `tests/`. Use package imports rather than changing `sys.path`. Runtime files belong in the configured output directory, not beside source files.

Before submitting a change:

```bash
ruff check .
ruff format --check .
python -m pytest
python -m build
```

Use `ruff check --fix .` and `ruff format .` to apply import and formatting fixes. Keep runtime dependencies in `pyproject.toml`; `requirements.txt` installs the project itself.

Tests should mock browser sessions, HTTP requests, database connections, and firewall commands. Do not require a TikTok account, live network access, or elevated privileges for the ordinary test suite. Changes to measurement timing or fallback detection should explain the effect on results and include relevant regression coverage.

For bug reports, include the command, Python and operating system versions, and a minimal reproduction. Remove credentials, cookie contents, and signed media URLs from shared logs. Never commit `.env`, browser sessions, or private datasets.

A project license is pending maintainer selection; no license has been inferred from dependency licenses.

Shell launchers live at the repository root and in `scripts/`. Validate them with Bash and ShellCheck:

```bash
for script in bash_*.sh scripts/*.sh; do bash -n "$script"; done
shellcheck -x -P SCRIPTDIR bash_*.sh scripts/*.sh
```

The launcher tests substitute a fake Docker executable and cover mounts, command selection, exit codes, VPN health checks, and cleanup. Do not start real VPN sessions or modify host networking from these tests.
