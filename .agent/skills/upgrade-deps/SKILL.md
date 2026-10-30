---
name: upgrade-deps
description: Monthly dependency, security and performance upkeep. Use when asked to update packages, upgrade dependencies, check for vulnerabilities, handle Dependabot PRs, or do routine maintenance.
---

# Dependency upkeep

Dependabot opens weekly PRs and CI checks them (see "Keeping dependencies
current" in AGENTS.md). This is the monthly pass for what that leaves over:
reviewing those PRs, upgrades a grouped PR cannot make, and the checks no
bot runs.

Run everything from the repo root with the venv's interpreter
(`venv/bin/python`, `venv/bin/pip-compile`, ...), not bare `python3`.

## 1. Clear the Dependabot queue

```bash
gh pr list --author app/dependabot
gh pr checks <number>
```

- **Patch and minor groups with green CI:** merge them
  (`gh pr merge <number> --squash`). A dependency-only diff touches no code
  or templates, so the `/code-review` gate's skip applies.
- **Majors:** read the package's changelog for breaking changes first, and
  check out the branch and run the app if it is a runtime dependency.
- **A red `css` job** means an npm bump changes the compiled CSS. Check out
  the branch, run `venv/bin/python manage.py tailwind build`, look at `/`, `/music/`
  and a detail page in both themes (lofi and forest) against `main`, then
  commit the rebuilt `theme/static/css/dist/styles.css` to the branch and
  merge it the same day: Dependabot stops rebasing a PR that carries
  someone else's commit, so a later bump in its group would need a fresh
  PR. Watch the compiled size too: Tailwind 4.3 grew it from 208 KB to
  253 KB.
- After merging, `git pull` before anything else here.

## 2. Bump what is left

```bash
venv/bin/pip-compile --upgrade requirements.in
venv/bin/pip-compile --upgrade requirements-dev.in   # always after the line above
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
(cd theme/static_src && npm update && npm outdated)
venv/bin/pre-commit autoupdate
```

Never edit `requirements.txt` or `requirements-dev.txt` by hand: add or
loosen a package in the `.in` file and recompile. `venv` is shared with
every worktree (`scripts/setup_worktree.sh`), so installing into it changes
them all. If the branch must differ, give the worktree its own venv as that
script describes.

`npm outdated` lists the majors `npm update` will not take. Take one by
editing `package.json`, then treat it like a red `css` job above.

**Vendored browser libraries.** htmx and Alpine are copied into
`games/static/games/js/vendor/`, so nothing above sees them. Compare the
versions in that directory's `README.md` with the latest, and check for
advisories against the version we ship:

```bash
npm view htmx.org@1 version          # the 1.x line; 2.x is a deliberate major
npm view alpinejs version
gh api "/advisories?ecosystem=npm&affects=htmx.org@1.9.10" --jq '.[].summary'
gh api "/advisories?ecosystem=npm&affects=alpinejs@3.14.3" --jq '.[].summary'
```

The README says how to update one.

## 3. Audit

```bash
venv/bin/pip-audit -r requirements.txt -r requirements-dev.txt
(cd theme/static_src && npm audit)
```

Fix anything high or critical. A moderate one may be waived only with a
reason recorded beside the CI audit step, as the
`@tailwindcss/typography` one is.

## 4. Test

```bash
DATABASE_URL=sqlite:///db.sqlite3 CACHE_URL=locmemcache:// CORS_ALLOWED_ORIGINS=http://localhost venv/bin/pytest
venv/bin/pre-commit run django-tests --hook-stage manual
venv/bin/python manage.py tailwind build && git diff --stat theme/static/css/dist/styles.css
```

Once a quarter, list Django's deprecation warnings, which are what a later
release removes:

```bash
venv/bin/python -Wd manage.py test games.tests 2>&1 | grep -i "RemovedInDjango" | sort | uniq -c
```

## 5. Performance

Nothing below runs in CI except the query budgets.

- **Query budgets:** `MusicQueryBudgetTests` and
  `GamesHomeGenreQueryBudgetTests` run in CI. A page that has grown an N+1
  since is caught only if it has a budget. Add one when a page gets slow.
- **Page weight:** the anonymous rankings page was 690 KB on 2026-10-18.
  Check it with
  `curl -s https://acclaimedmedia.org/ | wc -c`. Growth spends from
  the dyno's 512 MB (see "Production memory budget" in AGENTS.md).
- **Memory:** `heroku ps -a acclaimedgames`, and `memory.rss.bytes.max` /
  `memory.swap.bytes.max` from the metrics API URL in AGENTS.md over the
  last week. Any swap, or a max near 512 MB, needs a look before anything
  ships that adds weight.
- **Slow transactions:** Sentry's Performance view (traces sample at 10%),
  sorted by p95.

## 6. Runtime calendar

Flag anything within six months of its end of life:

| Runtime | Now | Ends | Next |
|---|---|---|---|
| Python | 3.14 (`.python-version`) | Oct 2030 | 3.15 |
| Django | 6.1 | Dec 2027 | 6.2 LTS, due Apr 2027 |
| Heroku stack | `heroku stack -a acclaimedgames` | Heroku's stack page | |
| Postgres | `heroku pg:info -a acclaimedgames` (18 on 2026-10-25) | | |

Django is uncapped in `requirements.in`, so Dependabot opens its majors
like any other; fix what the deprecation list showed before merging one.
A new Django can need a newer Python (6.0 dropped 3.11): bump
`.python-version`, rebuild the venv and recompile the locks under it.

Keep the local venv on production's Python patch release:
compare `venv/bin/python --version` with `heroku run -a acclaimedgames -- python --version` (a one-off dyno),
and if it is behind, `brew upgrade python@$(cat .python-version)` - the venv follows
Homebrew's symlink, so a patch needs no rebuild. A new minor version does:
see the rebuild command under "Dependencies" in AGENTS.md.

## 7. Ship

`/commit`, or `/deploy` if production should get it now. Both run the
`/code-review` gate. Add a DEVLOG line only for an upgrade with a visible
effect or a security fix.
