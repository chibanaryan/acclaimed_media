---
name: deploy
description: Deploy to Heroku production. Use when asked to deploy, push to production, or push to Heroku.
---

# Complete Deployment Workflow

Use this workflow when making changes that need to be deployed to production.

**Production URLs:** https://acclaimedmedia.org/ (landing page), https://games.acclaimedmedia.org/, https://music.acclaimedmedia.org/

## Steps

### 1. Update DEVLOG.md (if warranted)

**When to Update:**
- Bug fixes that resolve user-reported issues or known problems
- Performance improvements or optimizations
- New features or functionality additions
- Significant refactoring or architectural changes
- API or database schema modifications
- Deployment issues or critical fixes

**When NOT to Update:**
- Minor style or formatting changes
- Documentation-only updates (unless substantive)
- Test-only commits with no production changes
- Dependency version bumps without notable behavior changes

**Format Guidelines:**
- Keep entries concise - 8 bullet points maximum per day
- Use brief, imperative language (e.g., "Fix double-load on first search character")
- Group changes by date (one date header per day of work)

### 2. Build Tailwind CSS for production

```bash
venv/bin/python manage.py tailwind build
```

### 3. Minify JavaScript files

```bash
./scripts/minify_js.sh
```

### 4. Fetch main

```bash
git fetch origin
```

(No local `collectstatic`: Heroku runs it on build; see the commit skill.)

### 5. Review the change

Follow step 5 of the commit skill (`.claude/skills/commit/SKILL.md`)
exactly: a `/code-review` at `high` of everything not yet on `origin/main`,
every finding fixed or waived out loud, and a one-line summary in the
final message. If there is nothing new to push (HEAD is already on
`origin/main`), there is nothing to review; skip the step.

### 6. Stage the change

As in the commit skill: read `git status --short`, then `git add -u` and
add new files by path.

### 7. Commit with descriptive message

```bash
git commit -m "Your commit message here"
```

### 8. Push to main branch

```bash
git push origin HEAD:main
```

If rejected because `main` moved, rebase, re-run the tests and push again,
as in the commit skill.

### 9. Wait for CI

Heroku builds whatever it is pushed; CI is what runs the Postgres suite,
the production-only install, the manifest-storage renders and the browser
smoke test, none of which the pre-commit hook runs. Deploy a green commit:

```bash
gh run list --branch main --limit 1
gh run watch <run id> --exit-status
```

If it fails, fix it and go round again; do not deploy.

### 10. Back up the database if migrations ship

```bash
git fetch heroku
git diff --name-only heroku/main..HEAD | grep /migrations/ \
  && heroku pg:backups:capture -a acclaimedgames
```

`heroku rollback` puts the old code back but does **not** undo migrations;
a backup is the way back from a bad one (`heroku pg:backups:restore`).

### 11. Deploy to Heroku

```bash
git push heroku HEAD:main
```

### 12. Check it is up

```bash
for host in acclaimedmedia.org games.acclaimedmedia.org music.acclaimedmedia.org; do
  curl -sf "https://$host/healthz/" >/dev/null && echo "ok $host"
done
heroku releases -a acclaimedgames -n 1
```

`/healthz/` answers 200 only when Django can reach the database. If it
fails, `heroku logs --tail -a acclaimedgames`, and `heroku rollback` if the
release is at fault.

## Pre-commit Hook Handling

Pre-commit hooks will run tests and enforce code quality before allowing the commit.
They run after the review (step 5), so they test the reviewed and fixed code.

**If pre-commit hooks fail**: Fix issues immediately, do NOT skip or work around them:
- **Coverage failures**: Add tests or proper exclusions (not workarounds)
- **Linting failures**: Fix the code to comply with standards
- **Test failures**: Fix the failing tests or broken code

Commits will be blocked if any tests fail, coverage drops below 100%, or linting fails.
