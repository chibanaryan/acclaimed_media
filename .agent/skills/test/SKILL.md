---
name: test
description: Run Django tests with coverage reporting. Use when asked to test, run tests, or check coverage.
---

# Django Tests with Coverage

The suites live in `games/tests/`, `music/tests/`, `core/tests/` and
`books/tests/` (about 4,700 tests). Use the venv's interpreter
(`venv/bin/...`), not a bare `python3` or `pytest`.

## IMPORTANT: No Parallel Coverage Runs

**Never run coverage or pytest with coverage in parallel with other agents.**
Coverage writes to a shared `.coverage` file, so concurrent runs corrupt it.
Wait for any running test or coverage process to finish before starting
another.

## Commands

```bash
# Everything, as the pre-commit hook and CI run it. pytest.ini adds
# -n auto (xdist), coverage of the four apps, and the 100% gate.
venv/bin/pytest

# One file, or a pattern, without the coverage gate (a partial run can
# never reach 100%)
venv/bin/pytest --no-cov games/tests/test_models.py
venv/bin/pytest --no-cov -k "jump_to_rank"

# The same suites under Django's runner, where conftest.py does not apply,
# so a test that leaks cache or process state into the next one fails.
# Run it when a change touches caching, sessions or other process-wide state.
venv/bin/pre-commit run django-tests --hook-stage manual

# On Postgres, production's database, instead of in-memory SQLite
TEST_DATABASE_URL=postgres://... venv/bin/pytest --no-cov
```

## What conftest.py does

- Clears every cache alias between tests.
- Refuses every network connection and DNS lookup that leaves the machine,
  and fails a test that tried, even if the client swallowed the error.
  Patch the client where the code under test reads it.

Settings also blank the IGDB, Wikidata and Discogs credentials under test,
as CI has none, so a local run takes the same paths as CI.

## What needs Node

The tests that run the client code (`core/tests/js/`: filter parity, the
renderers' escaping, `utils-base.js`) need `node` on `PATH`. Without it
they skip locally and fail in CI (`core/tests/node.py:require_node`).

## Warnings that fail

`pytest.ini` turns Django's `RemovedInNextVersionWarning` into an error, so
a test that reaches an API the next release removes fails here first.

## Coverage

`.coveragerc` measures `games`, `books`, `core` and `music`, and omits only
migrations and the tests themselves. The 100% gate covers every management
command and both import handlers since 2026-11-12; until then it left out
six files by name, and before that every command by pattern. A new file is
measured from its first commit, so it arrives with its tests.

## Pre-commit Hooks

`.pre-commit-config.yaml` runs black, flake8 (max line length 88) and pytest
on every commit; a failure blocks the commit. The Django-runner pass above
is a manual-stage hook.
