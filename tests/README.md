# Test suite

Tests for the Omani Receptionist engine. Scope, layering, and coverage
targets are defined in [`PLAN.md` §14](../PLAN.md#14-testing-strategy).

## How to run

```bash
pytest                  # full suite (uses asyncio_mode = auto)
pytest -m unit          # fast checks only — no Docker, no network
pytest -m integration   # needs docker-compose stack up (Postgres, Redis)
pytest --cov            # with coverage report (config in pyproject.toml)
pytest tests/unit -q    # narrow to one folder, quiet output
```

CI runs `pytest -m unit` on every push and the full suite nightly.

## Layout

| Folder | What lives here | Marker |
|---|---|---|
| `tests/unit/` | Pure-Python tests, no I/O outside `tmp_path` | `@pytest.mark.unit` |
| `tests/integration/` | Tests that hit real Postgres / Redis via docker-compose | `@pytest.mark.integration` |
| `tests/dialect/` | Golden Omani conversation tests (≥40 pairs, ≥90% pass) | `@pytest.mark.dialect` |
| `tests/e2e/` | Smoke tests through a real channel adapter | `@pytest.mark.e2e` |

Shared fixtures (e.g. `repo_root`, `tmp_business_dir`, `valid_config_yaml`)
live in [`conftest.py`](./conftest.py).

## Adding a new test

1. Pick the right folder by what the test *touches*, not what it covers
   (a config-loader test that only uses `tmp_path` is a `unit` test even
   though it tests config code).
2. Name the file `test_<thing>.py` and the functions `test_<behavior>()`.
3. Mark every function with the matching `@pytest.mark.<folder>` marker —
   `--strict-markers` is on, so unknown markers fail the run.
4. Prefer `parametrize` over copy-pasted test bodies.
5. No `time.sleep`, no real network, no test depending on another test.

## Markers

Registered in [`pyproject.toml`](../pyproject.toml) under
`[tool.pytest.ini_options].markers`: `unit`, `integration`, `dialect`,
`e2e`, `slow`. Anything else trips `--strict-markers`.
