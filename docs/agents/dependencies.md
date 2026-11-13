<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Dependencies

Python packages are pinned with pip-tools. Edit the `.in` files and never the
`.txt` files, which are compiled from them:

| File | What it is |
|---|---|
| `requirements.in` | What production imports, loosely constrained |
| `requirements.txt` | Its compiled, fully pinned lock - what Heroku installs |
| `requirements-dev.in` | Tests, hooks, `pip-audit`, the debug toolbar, `runserver_plus` |
| `requirements-dev.txt` | Its lock, constrained to `requirements.txt`'s pins |

```bash
pip install -r requirements.txt -r requirements-dev.txt   # local development and tests
pip-compile requirements.in && pip-compile requirements-dev.in   # after editing an .in
pip-compile --upgrade-package django requirements.in && pip-compile requirements-dev.in
```

Always recompile the dev lock after the production one: it repeats every
production pin, and CI installs both locks together so that a dev lock left
on an old pin fails the install rather than testing a version Heroku never
runs.

Each lock's header records the exact `pip-compile` command, flags included;
Dependabot reruns it. Until 2026-10-25 only `psycopg2-binary` was pinned, so
every Heroku build installed whatever was newest that day, test tools
included.

Tailwind CSS and DaisyUI are npm packages in `theme/static_src/`, pinned by
its `package-lock.json`. `node_modules` there and `venv` at the root are
symlinks into the main checkout in every worktree (`scripts/setup_worktree.sh`),
so `npm install` or `pip install` in a worktree changes every checkout's copy.
Replace the symlink with a real install before changing either on a branch.

Two things run that script. Conductor runs it as the workspace setup script
(`.conductor/settings.toml`). Claude Code runs it from a `SessionStart` hook
(`.claude/settings.json`), which covers the desktop app's Worktree toggle
and `claude --worktree`. Claude Code runs hooks in the main checkout, with
`$CLAUDE_PROJECT_DIR` pointing there, even for a worktree session, so the
hook passes `--hook-input` and the script reads the session's directory from
the `cwd` field of the hook's JSON. Until 2026-11-01 the hook `cd`'d to
`$CLAUDE_PROJECT_DIR`, so a worktree session found itself "in the main
checkout" and provisioned nothing. The hook runs on every start and resume,
so it passes `--migrate-new`, which migrates only the session that clones the
database, as Conductor does once at creation; a branch that adds a migration
later still needs `manage.py migrate`. It also writes the venv onto `PATH`
through `$CLAUDE_ENV_FILE`, so `python` and `pytest` in a session are the
venv's, in the main checkout too. The worktrees live in `.claude/worktrees/`,
which is gitignored. Conductor's Run button is `.claude/launch.json` in the
desktop app: `runserver` on a free port the app picks and passes as `$PORT`,
opening on the landing page.

A Claude Code **cloud session** (claude.ai/code, `CLAUDE_CODE_REMOTE=true`)
is a fresh Linux clone with nothing to link or copy, and it cannot reach the
Mac's checkout, whose venv would not run there anyway. So the same hook runs
`scripts/setup_cloud.sh` in the main checkout first: it builds a venv on
`.python-version`'s Python with `uv`, migrates a new `db.sqlite3`, and loads
the release files in `acclaimedgames/test_input_files/` (`import_games_data`,
`import_music_data`), about 20 s with uv's download cache warm. A worktree in
the session then links and copies them as usual. That is the rankings alone,
with no covers, genres, playtimes or accounts: the fetchers and
`sync_from_prod` need credentials the session does not have. Later starts
boot nothing and print nothing, unless a lock file or `.python-version`
changed, which re-syncs the venv; a migration a branch adds later still needs
`manage.py migrate`. A failure is printed to the session, not hidden. No
environment setup script is needed.

The shared venv lives in the main checkout and is built on Homebrew's
`python@3.14`, kept on the patch release production runs (check with
`heroku run -a acclaimedgames -- python --version`, which starts a
one-off dyno). Its interpreter is a symlink into
Homebrew's `opt/` directory, so `brew upgrade python@3.14` moves every
worktree's venv to the new patch with no rebuild; a patch release keeps the
ABI, so the installed packages carry on working. Rebuild only for a new
minor version, from the main checkout, once `.python-version` is bumped
and the locks are recompiled under it:

```bash
V="$(cat .python-version)"; PY="$(brew --prefix python@$V)/bin/python$V"
test -x "$PY" && rm -rf venv && "$PY" -m venv venv \
  && venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

`test -x` comes first because `brew --prefix` prints a path even for a
formula that is not installed, and every worktree's `venv` symlink points
at this one: deleting it before the new interpreter is known to exist
leaves all of them without a venv.

Use Homebrew's Python, not a python.org installer. python.org's macOS
framework builds ship no CA bundle, and their "Install Certificates" step
cannot write one without root, so aiohttp (the HLTB fetch) fails every
certificate check unless a `sitecustomize.py` points `SSL_CERT_FILE` at
certifi - which is what the venv carried until 2026-10-25.

### Keeping dependencies current

Four layers, from automatic to manual:

- **GitHub security features** (enabled 2026-10-25): Dependabot alerts,
  Dependabot security updates (a PR as soon as an advisory lands), secret
  scanning, and push protection, which refuses a push containing a
  recognised credential.
- **Dependabot version updates** (`.github/dependabot.yml`): every Monday,
  one grouped PR of minor and patch bumps per ecosystem (pip, npm), and
  majors one PR each. Django's feature releases get their own PR too, since
  they can remove deprecated APIs. GitHub Actions monthly. Nothing
  is held back: until 2026-10-25 `requirements.in` capped Django below 6.0,
  and the site ran 5.2 on Python 3.11, which no Django 6 release supports.
- **CI** (`.github/workflows/ci.yml`) on every push to `main`, every PR, and
  every Monday:

  | Job | Checks |
  |---|---|
  | `lint` | black, flake8 over every file |
  | `pytest` | the suites with the 100% coverage gate |
  | `django-tests` | `scripts/run_tests.sh`, the runner without conftest, on Postgres 18 (production's version) |
  | `production-install` | `requirements.txt` alone, as Heroku installs it: `check --deploy`, importing every non-test module, `collectstatic`, pages rendered under manifest storage, and the https redirect read from `X-Forwarded-Proto` |
  | `audit` | `pip-audit` on both locks, `npm audit` (any severity). The one job a Monday's scheduled run does |
  | `css` | rebuilds the CSS and fails if it differs from the committed file |
  | `js` | `scripts/minify_js.sh --check`: the same for the minified JS and bundles, and `node --check` on the two scripts terser never parses |
  | `browser` | `scripts/browser_smoke.js`: Chrome over the main pages, failing on a JS, Alpine or CSP error, plus Back and Load More across the engine load, music's takeover leaving a row's POST alone, a year range outside the corpus and leaving it, a games highlight landing, a mobile row opened by keyboard, the CSV button, a failed filter request rolled back on both sites, a failed Back followed by the engine, each site's search box by keyboard, a reversed year range on both sites, a server Load More keeping focus, a theme chosen on `127.0.0.1` staying, and, signed in as the reader `smoke_seed.py` makes, a status chosen on the artist page reaching the row's other half, music's listen menu by keyboard, and games' saved filters saved, applied and deleted |

  `css` exists because Heroku runs only the Python buildpack, so the
  committed `theme/static/css/dist/styles.css` is what ships. An npm bump
  that changes the build fails there until someone rebuilds and looks at it.
  Tailwind 4.1 -> 4.3 was such a bump: it grew the file from 208 KB to
  253 KB (32 KB to 36 KB gzipped), and moved nothing on screen but the music
  Filters header's buttons, by ~3px.

  Node is pinned (`NODE_VERSION: "26"`, one variable for every job): it
  was `lts/*`, which moves each October under a job that compares terser's
  output byte for byte. Nothing bumps it; `/upgrade-deps` has a row.

  A run's concurrency group is its commit on `main` and its ref on a pull
  request. Keyed on the ref alone, GitHub cancelled the run *waiting* in the
  group whenever a newer one queued, whatever `cancel-in-progress` said, so
  the middle of three quick pushes never got a result.

  To run the smoke test locally, start `runserver` without the debug
  toolbar: its handle sits over the sidebar's CSV button, and the CSV check
  fails with "asked for nothing". CI installs `requirements.txt` alone and
  has none.
- **`/upgrade-deps`**, monthly: merge the Dependabot queue, take the majors,
  audit, check page weight, memory and slow transactions, and check the
  runtime end-of-life calendar (Python 3.14 ends October 2030; Django 6.1,
  not an LTS, gets security fixes until December 2027, so 6.2 by then).

A Dependabot PR is a merge to `main` like any other. A dependency-only diff
touches no code or templates, so the `/code-review` gate's skip applies, but
it merges only with CI green, and a major only after reading its changelog.

**`@tailwindcss/typography` pins `postcss-selector-parser` exactly** (at
6.0.10 in 0.5.20), below the 6.1.5 fix for GHSA-rj75-hqrm-r3gf. An
`overrides` entry in `theme/static_src/package.json` holds it at the patched
6.1.5 instead; drop it once the plugin's pin moves past that. Nothing is
waived any more: CI's `npm audit` fails on any severity, as `pip-audit` does.

**What the first Postgres run found** (2026-10-25), none of which SQLite
could show:

- **Two migrations had only ever run incrementally.** `0055` and `0061`
  failed on a fresh database: `0044`'s rename left the old index names
  behind, and `0061` probed for `auth_user` with a SELECT whose failure
  aborts a Postgres transaction. Both now branch on the vendor; production
  applied them long ago, so only new databases see the change.
- **Import threads escape the test transaction.** `_start_import_thread`
  runs an import on its own connection. Under in-memory SQLite Django hands
  every thread the test's connection, so it never mattered; on Postgres the
  thread's writes commit for real and leak into every later test on that
  worker, and one touching a row the test holds deadlocks. Tests that reach
  a thread run it inline (`InlineImportThreadMixin` in
  `games/tests/test_imports.py`).
- **Five import tests had been passing by accident.** Their mocks patched
  `games.utils.*`, which the code stopped reading when it moved to
  `games.services.import_handler`; they passed because the threaded import
  failed with SQLite's "database table is locked", which they took for the
  error they expected. Underneath was a real bug: the streaming batch import
  (`import_batch_with_progress`, the staff import page) passed `"GAMES"`
  where `_validate_prerequisites` compares `constants.TYPE_GAME`, so it
  never validated prerequisites at all.
- **A test assumed a primary key of 1.** Postgres sequences do not rewind
  when a test's transaction rolls back; use the object's `id`.

Set `TEST_DATABASE_URL` to run the suites on Postgres locally; tests
otherwise always use in-memory SQLite. Patch the module that *reads* a name,
not one that re-exports it.
