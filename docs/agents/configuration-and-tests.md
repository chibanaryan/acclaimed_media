<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Configuration

### Environment Variables

Environment variables are managed via django-environ. Settings reads `.env`,
which the shell's own variables beat, then `.env.development.local` if that
file exists, which beats both: with a `DATABASE_URL` there, point a command
at another database through a settings module, not `DATABASE_URL=... python
manage.py ...`. `.env.example` lists them all.
- `DEBUG` - Enable Django debug mode
- `SECRET_KEY` - Django secret key
- `DATABASE_URL` - The database. Unset, it is SQLite at `db.sqlite3`; Heroku
  sets it to Postgres
- `TEST_DATABASE_URL` - Run the test suites on Postgres rather than in-memory
  SQLite (see "Dependencies")
- `CORS_ALLOWED_ORIGINS` - Comma-separated origins allowed to call the API
  from a browser
- `SENTRY_DSN` - Where errors, traces and CSP reports go. See
  `SENTRY_ENVIRONMENT` below for when anything is sent
- `BREVO_SMTP_USER`, `BREVO_SMTP_KEY` - The SMTP login for outgoing mail
- `SITE_URL` - The origin emailed links are built on, where no request is at
  hand
- `IGDB_CLIENT_ID` - IGDB API client ID
- `IGDB_CLIENT_SECRET` - IGDB API client secret
- `IGDB_USE_PRO_TIER` - Enable IGDB Pro tier (default: False)
- `WIKIDATA_ACCESS_TOKEN` - A Wikimedia BotPassword, `user:password`, sent as
  basic auth: about 2.5x faster for `fetch_wikipedia_metadata`, 4x for the
  weekly refresh
- `BOOKS_ENABLED` - Show the Books links in the nav (default: False). The
  section is staff-only whatever it says
- `HARDCOVER_API_TOKEN` - Optional Hardcover API token for additional book metadata
- `DISCOGS_TOKEN` - Optional Discogs personal access token; raises the music
  metadata rate limit above the 25 requests/minute anonymous tier
- `CACHE_URL` - Cache backend URL. Production uses `dbcache://cache_table`.
  Local dev (`DEBUG`) ignores an unset or `dbcache` URL and uses LocMem; any
  other URL is used as given. Tests set `locmemcache://`, and get LocMem
  without one. A dyno with none does not start (2026-11-12): it fell back
  to a file cache of its own, so an invalidation or the metadata lock
  reached one process. See the Caching section
- `METADATA_AFTER_IMPORT` - Whether an import fetches the metadata it left
  missing (default: on, off under test). See "Imports start their metadata
  fetch"
- `ANON_RENDER_BUDGET_ENFORCE` - Answer 429 to anonymous renders past the
  per-process budget, which otherwise only reports them (default: off). See
  "Caching"
- `SENTRY_ENVIRONMENT` - Sentry's environment tag. Defaults to `production`
  when `DYNO` is set (any Heroku dyno) and `development` everywhere else.
  `core.sentry.event_scrubber` adds allauth's `password1`, `password2`
  and `oldpassword` to the default denylist, which matches whole key names
  and let them through until 2026-11-11, and the CSRF token where it
  travels outside its cookie: htmx's `X-CSRFToken` header and a form's
  `csrfmiddlewaretoken` (2026-11-12; the SDK redacts the session and CSRF
  cookies itself, by their configured names). A request's unhandled exception is
  also logged to the console (`django.request`), so it is in `heroku logs`
  when Sentry is down or over quota.
  `development` sends nothing, neither errors nor CSP reports, even with
  `SENTRY_DSN` in the local `.env`; set any other value to opt a machine in.
  `manage.py shell` never reports, on a dyno either: whoever ran it reads the
  traceback, and each typo in a one-off query filed an issue and an alert.
  That includes `heroku run:detached`, so unwatched work belongs in a command.
  A path that matched no route and was answered 404 or with a redirect is
  traced as `unrouted 404` or `redirect 301` (`core/sentry.py`), not under
  its own name: each scanner probe and slash-less link was a transaction of
  its own. Static files and flat pages, which middleware answers with no
  route matched, keep theirs

### Configuration Files

- **`.python-version`** - Specifies Python 3.14 for Heroku deployment; the local venv tracks production's patch release (see "Dependencies")
- **`.pre-commit-config.yaml`** - Pre-commit hook configuration for code quality enforcement (Black, Flake8, tests)
- **`.coveragerc`** - Coverage configuration. It omits migrations and the tests, and nothing else: every command and both import handlers are under the 100% gate since 2026-11-12, and a new file is measured by default. Until then it left out six files by name (four games commands, games' import handler and the books command, at 62% to 81% or untested), and before that every command and both handlers by pattern
- **`.flake8`** - Flake8 linter configuration (max line length 88; excludes nothing of ours but migrations and `.context/`)
- **`scripts/run_tests.sh`** - The same suites under Django's own test runner; see below

**Two test runners, on purpose.** `pytest` is the gate: the pre-commit hook
runs it on every commit and `pytest.ini` fails the commit under 100%
coverage. `conftest.py` also clears every cache alias between tests, which
hides a test that leaks cache or process state into the next one.
`scripts/run_tests.sh` runs the same four suites under `manage.py test`,
where conftest does not apply, so such a leak fails there. On 2026-10-17 it
found 181 failures and 55 errors that a fully green pytest run had missed,
after the cache was split into aliases. It would nearly double a commit's
test time (~45 s on top of pytest's ~60 s), so it is a manual-stage hook. Run
it when a change touches caching, sessions or any other process-wide state:

```bash
venv/bin/pre-commit run django-tests --hook-stage manual
```

It used to run on every commit from a hand-placed
`.git/hooks/pre-commit.legacy`, until a `pre-commit install` silently replaced
it. Keep hooks in `.pre-commit-config.yaml`, never in `.git/hooks`, which
`pre-commit install` owns and every worktree shares. `tblib` is in
`requirements-dev.txt` so that a failure under `--parallel` reports its traceback
instead of crashing the runner on an unpicklable one.

**Tests cannot reach the network under pytest.** `conftest.py` refuses
every DNS lookup and connection that leaves the machine (loopback stays
open for the Postgres runs), and fails the test even when the client code
swallowed the error. The tests also run without outside credentials:
settings blanks the IGDB, Wikidata and Discogs ones under test, as CI has
none. When the guard was added on 2026-10-26 it caught four tests calling
IGDB and HowLongToBeat for real. Locally they were also fetching a live
Twitch token with the `.env` credentials. Patch the client where the code
under test reads it. The Django runner has no conftest and so no guard.

**Test mode is the `test` subcommand or pytest** (`core.csp.running_tests`),
not "test" anywhere in the arguments: `get_igdb --game test` ran against an
empty in-memory database with blank credentials, on a dyno too, until
2026-11-10.

**A test that needs two timestamps in order sets them** (a day apart, with
`.update()`), and does not sleep between two saves: six did until
2026-11-12, which was slow and at the mercy of the clock's resolution.

**`soup.select()` does not look inside a `<template>`**, from soupsieve 4.0
(the lock went from 3.0.4 to 4.1 on 2026-11-12, for CVE-2026-126190: a
selector matched in quadratic time against deeply nested HTML. Nothing in
production calls `select`; the scrapers use `find` and `find_all`, so only
the tests were ever exposed). A template's contents are no longer part of
the document, as in a browser, and most of what these tests ask about is in
one: an Alpine `x-for` or `x-if` body, a renderer's clone row. Six
assertions failed on the upgrade. The ones that did not fail were the
trouble: an `assertFalse(soup.select(...))` passes whatever a template
holds, an icon check went from 107 icons to 69, and a count of one status
menu a page stopped counting the row template it exists to keep a menu out
of. `core.tests.utils.select_all` selects with the templates seen into;
every absence and exact count over rendered markup uses it, and so do the
tests of template bodies. Three tests were left on `select` on purpose,
because seeing less is what their names say: "the rendered row carries the
same slots" used to be satisfied by the clone template's slots alone.
`find` and `find_all` are not soupsieve and see everything.

**Tests pick a site the way a request does.** The test client's
`testserver` host gets `ROOT_URLCONF`, the games site, so games tests need
nothing. A module of music tests imports the module fixtures
(`from music.tests.site import setUpModule, tearDownModule`), which put the
music URLconf in place for the whole module under both runners; a music
class in a mostly-games module takes `@music_site` instead. A test that
crosses sites names the real host: `core.tests.utils.get_on_site(client,
sites.GAMES, "home")`, over HTTPS, so its links are the production ones.
